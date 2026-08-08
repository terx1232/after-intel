#!/usr/bin/env python3
"""
hvc_impl.py -- answer the paravirtual CPU service calls instead of stubbing
them.

The vma2 kernel talks to its hypervisor over SMCCC `hvc #0`. QEMU's `virt`
machine implements PSCI and nothing else, and SMCCC 1.3 says an unknown call
returns -1, so every Apple-specific call fails. Where the kernel checks the
result it spins on the spot:

    movz x0, #0xC1000000
    hvc  #0
    cbnz x0, .          <- branch to self

That spin, at 0xfffffe0009e40350, is where an unpatched kernel stops.

The 46 call sites are not all the same kind, and treating them alike is what
made earlier attempts fail:

  * 25 sites are **checkers**: the call is followed by `cbnz x0` or `cbz x0`.
    Only success or failure is read, and the contract is legible from the code
    itself -- zero means success. These can be answered.

  * 21 sites are **consumers**: the call is followed by `str x0, [reg]` or
    `mov xN, x0`, so a real value is expected back. Every one of them builds
    its function id at runtime rather than from an immediate, and all of them
    live in kext text (0xa00c... upward), not in the kernel core -- they run at
    IOKit matching time, long after early boot. What they should return is not
    knowable from this side, so this tool does not touch them. Writing a
    plausible-looking value into a pointer the kernel will dereference is worse
    than leaving the call to fail honestly.

An earlier attempt rewrote checker sites as `adrp x0, <page>` + `nop`, which
loads a *non-zero* address into x0 -- exactly the value that makes `cbnz x0`
spin. Replacing the `hvc` itself with `movz x0, #0` is both smaller and right:
one instruction, the following `cbnz` is left in place and simply falls
through, and nothing else in the function moves.

This answers the calls. It does not perform whatever the hypervisor would have
done as a side effect, and that limit is real: see BRINGUP-LOG.md.

Usage:
    python hvc_impl.py <kernel> --out <patched>
    python hvc_impl.py <kernel> --list
"""

from __future__ import annotations

import argparse
import json
import struct
import sys

HVC0 = 0xD4000002
MOVZ_X0_0 = 0xD2800000          # movz x0, #0


def classify(data: bytes, off: int) -> str:
    """What does the code do with the result of the call at `off`?"""
    if off + 8 > len(data):
        return "unknown"
    nxt = struct.unpack_from("<I", data, off + 4)[0]
    # CBZ/CBNZ, 64-bit form, testing x0
    if (nxt & 0x7F00001F) in (0x34000000, 0x35000000):
        return "checker"
    # STR x0, [Xn, #imm] -- keep the Rt field, not the Rn field. Masking with
    # 0xFFC003FF keeps bits 9:0, which includes Rn, so it never matched.
    if (nxt & 0xFFC0001F) == 0xF9000000:
        return "consumer"
    # MOV Xd, x0, i.e. ORR Xd, XZR, X0
    if (nxt & 0xFFE0FFE0) == 0xAA0003E0:
        return "consumer"
    return "other"


def immediate_id(data: bytes, off: int, vb: int) -> int | None:
    """Rebuild the function id if it is assembled from immediates in x0.

    Note the mask: `w & 0x7F800000` clears bit 31, so comparing that against
    0xD2800000 can never match. It has to be 0xFF800000.
    """
    start = None
    for i in range(1, 12):
        w = struct.unpack_from("<I", data, off - i * 4)[0]
        if (w & 0xFF800000) in (0xD2800000, 0xF2800000) and (w & 0x1F) == 0:
            start = i
        elif start is not None:
            break
    if start is None:
        return None
    fid = 0
    for i in range(start, 0, -1):
        w = struct.unpack_from("<I", data, off - i * 4)[0]
        if (w & 0xFF800000) not in (0xD2800000, 0xF2800000) or (w & 0x1F):
            continue
        hw = (w >> 21) & 3
        v = ((w >> 5) & 0xFFFF) << (16 * hw)
        if (w & 0xFF800000) == 0xD2800000:      # movz replaces the whole reg
            fid = v
        else:                                   # movk replaces one field
            fid = (fid & ~(0xFFFF << (16 * hw))) | v
    return fid


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("--out")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    data = bytearray(open(args.kernel, "rb").read())

    sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
    try:
        import loadmap
        vb = loadmap.parse(args.kernel)["vm_low"]
    except Exception:
        vb = 0xFFFFFE0007004000

    sites = [off for off in range(0, len(data) - 4, 4)
             if struct.unpack_from("<I", data, off)[0] == HVC0]

    rows = []
    for off in sites:
        rows.append({
            "va": vb + off,
            "kind": classify(bytes(data), off),
            "id": immediate_id(bytes(data), off, vb),
        })

    kinds = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1

    print(f"\n=== hvc #0 sites in {args.kernel} ===\n")
    print(f"  total: {len(rows)}")
    for k, v in sorted(kinds.items(), key=lambda x: -x[1]):
        print(f"    {k:<10} {v}")

    ids = {}
    for r in rows:
        if r["id"] is not None:
            ids[r["id"]] = ids.get(r["id"], 0) + 1
    if ids:
        print("\n  function ids visible as immediates:")
        for k, v in sorted(ids.items()):
            owner = (k >> 24) & 0x3F
            name = {1: "CPU Service (Apple)", 4: "Standard Hypervisor",
                    0: "Arm Architecture"}.get(owner, f"owner {owner}")
            print(f"    {k:#010x}  x{v}   {name}")

    if args.list:
        print("\n  checkers (answered), by address:")
        for r in rows:
            if r["kind"] == "checker":
                fid = f"{r['id']:#x}" if r["id"] is not None else "dynamic"
                print(f"    {r['va']:#x}  id {fid}")
        print("\n  consumers (left alone -- return value unknown):")
        for r in rows:
            if r["kind"] == "consumer":
                print(f"    {r['va']:#x}")

    patched = 0
    for r, off in zip(rows, sites):
        if r["kind"] == "checker":
            struct.pack_into("<I", data, off, MOVZ_X0_0)
            patched += 1

    print(f"\n  answered {patched} checker sites with `movz x0, #0`")
    print(f"  left {kinds.get('consumer', 0)} consumer sites untouched")

    # Verify by reading back what was written.
    bad = [r["va"] for r, off in zip(rows, sites)
           if r["kind"] == "checker"
           and struct.unpack_from("<I", data, off)[0] != MOVZ_X0_0]
    if bad:
        print(f"  SELF-CHECK FAILED at {len(bad)} sites", file=sys.stderr)
        return 1
    print("  self-check: every answered site reads back as movz x0, #0")

    if args.out:
        open(args.out, "wb").write(bytes(data))
        print(f"\nwrote {args.out} ({len(data):,} bytes)")
    if args.json:
        json.dump(rows, open(args.json, "w"), indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
