#!/usr/bin/env python3
"""
stub_hypercalls.py -- find every "call a paravirtual service, hang if it is not
there" site in a kernel and stub them all out at once.

XNU's virtual-platform code initialises through a series of SMCCC calls in
Apple's CPU Service Calls range. Each site looks the same:

    movz x0, #<function id>
    hvc  #0
    cbnz x0, .          <- branch to self: hang if the call was refused

On a machine that does not implement those services, every one of them returns
NOT_SUPPORTED and the kernel parks forever on the cbnz. Patching them one at a
time just reveals the next one, so this finds the whole set by pattern and
replaces each `hvc` with `movz x0, #0`, which makes the check fall through as
though the service had succeeded.

This is a bring-up stub, not a fix. Everything reached past these sites runs on
the pretence that services the machine does not provide are present and worked.

Usage:
    python stub_hypercalls.py <kernel> --scan
    python stub_hypercalls.py <kernel> --out <patched>
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys

HVC0 = 0xD4000002        # hvc #0
CBNZ_X0_SELF = 0xB5000000  # cbnz x0, #+0
MOVZ_X0_0 = 0xD2800000   # movz x0, #0

MOVZ_MASK = 0x7F800000
MOVZ_OP = 0x52800000
MOVK_MASK = 0x7F800000
MOVK_OP = 0x72800000


def recover_function_id(words: list, i: int):
    """Walk back a few instructions to recover the SMCCC id put into x0."""
    val = None
    for j in range(max(0, i - 6), i):
        w = words[j]
        rd = w & 0x1F
        if (w & MOVZ_MASK) == MOVZ_OP and rd in (0, 11):
            hw = (w >> 21) & 3
            val = ((w >> 5) & 0xFFFF) << (16 * hw)
        elif (w & MOVK_MASK) == MOVK_OP and rd in (0, 11) and val is not None:
            hw = (w >> 21) & 3
            imm = ((w >> 5) & 0xFFFF) << (16 * hw)
            val = (val & ~(0xFFFF << (16 * hw))) | imm
    return val


def exec_range(path: str):
    b = open(path, "rb").read()
    ncmds = struct.unpack_from("<I", b, 16)[0]
    off = 32
    out = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", b, off)
        if cmdsize == 0:
            break
        if cmd == 0x19:
            name = b[off + 8:off + 24].split(b"\x00")[0].decode("ascii", "replace")
            vmaddr, vmsize, fileoff, filesize, maxprot, initprot = \
                struct.unpack_from("<QQQQii", b, off + 24)
            if initprot & 4:
                out.append((name, vmaddr, fileoff, filesize))
        off += cmdsize
    return b, out


def find_sites(path: str) -> list:
    b, segs = exec_range(path)
    sites = []
    for name, vmaddr, fileoff, filesize in segs:
        n = filesize // 4
        words = list(struct.unpack_from(f"<{n}I", b, fileoff))
        for i in range(n - 1):
            if words[i] == HVC0 and words[i + 1] == CBNZ_X0_SELF:
                sites.append({
                    "segment": name,
                    "vaddr": vmaddr + i * 4,
                    "offset": fileoff + i * 4,
                    "function_id": recover_function_id(words, i),
                })
    return sites


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("--out")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    sites = find_sites(args.kernel)
    print(f"\n=== hypercall-or-hang sites in {os.path.basename(args.kernel)} ===\n")
    print(f"found {len(sites)}\n")
    print(f"{'virtual address':<22}{'segment':<16}{'SMCCC id':>12}")
    print("-" * 52)
    for s in sites:
        fid = f"{s['function_id']:#010x}" if s["function_id"] is not None else "?"
        print(f"{s['vaddr']:#018x}    {s['segment']:<16}{fid:>12}")

    ids = sorted({s["function_id"] for s in sites if s["function_id"] is not None})
    if ids:
        print(f"\ndistinct function ids: {', '.join(f'{i:#010x}' for i in ids)}")

    if args.json:
        json.dump({"kernel": os.path.basename(args.kernel), "sites": sites},
                  open(args.json, "w", encoding="utf-8"), indent=2)
        print(f"\nwrote {args.json}", file=sys.stderr)

    if args.scan or not args.out:
        return 0

    data = bytearray(open(args.kernel, "rb").read())
    for s in sites:
        struct.pack_into("<I", data, s["offset"], MOVZ_X0_0)
    open(args.out, "wb").write(bytes(data))
    print(f"\nstubbed {len(sites)} site(s): hvc #0 -> movz x0, #0")
    print(f"wrote {args.out} ({len(data):,} bytes)")
    print("\nBring-up stub, not a fix. Past these points the kernel believes")
    print("services exist that this machine does not provide.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
