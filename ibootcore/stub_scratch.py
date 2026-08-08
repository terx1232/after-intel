#!/usr/bin/env python3
"""
stub_scratch.py -- make the paravirtual stubs hand back a real pointer instead
of zero.

`stub_hypercalls.py` replaces each `hvc` with `movz x0, #0`, which gets past the
"hang if refused" check but also makes the return value zero. Some of these
calls return pointers, so the kernel then dereferences NULL, and patching each
faulting load only reveals the next use of the same missing structure.

Handing back a pointer to mapped, zeroed memory is a better lie. The loads
succeed and read zeros, and the kernel takes whatever path an empty structure
leads to rather than trapping.

Two instructions are available at each site -- the `hvc` and the `cbnz` that
follows it -- which is exactly enough:

    adrp x0, <scratch page>     ; PC-relative, reaches anywhere in the image
    nop                         ; was: cbnz x0, . -- x0 is now non-zero, so
                                ;      leaving the cbnz would hang

The scratch page defaults to one inside __DATA, which the kernel maps
read-write, so a write through the pointer lands somewhere harmless-ish rather
than faulting.

Usage:
    python stub_scratch.py <kernel> --out <patched> [--scratch 0x...]
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys

HVC0 = 0xD4000002
CBNZ_X0_SELF = 0xB5000000
NOP = 0xD503201F


def encode_adrp(rd: int, pc: int, target: int) -> int:
    """ADRP Rd, <page of target>, relative to the instruction at pc."""
    delta = (target & ~0xFFF) - (pc & ~0xFFF)
    imm = delta >> 12
    if not (-(1 << 20) <= imm < (1 << 20)):
        raise ValueError(f"target {target:#x} out of ADRP range from {pc:#x}")
    imm &= 0x1FFFFF
    immlo = imm & 3
    immhi = imm >> 2
    return 0x90000000 | (immlo << 29) | (immhi << 5) | (rd & 0x1F)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("--out", required=True)
    ap.add_argument("--scratch", default="0xfffffe000ad80000",
                    help="a page the kernel maps read-write")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import loadmap
    m = loadmap.parse(args.kernel)
    vb = m["vm_low"]
    scratch = int(args.scratch, 0)

    data = bytearray(open(args.kernel, "rb").read())
    sites = []

    # Find the sites the same way stub_hypercalls does, but accept either the
    # original hvc or a previous movz stub in that slot.
    for seg in m["segments"]:
        if not (seg["initprot"] & 4):
            continue
        n = seg["filesize"] // 4
        base = seg["fileoff"]
        words = list(struct.unpack_from(f"<{n}I", data, base))
        for i in range(n - 1):
            if words[i] in (HVC0, 0xD2800000) and words[i + 1] == CBNZ_X0_SELF:
                va = seg["vmaddr"] + i * 4
                try:
                    adrp = encode_adrp(0, va, scratch)
                except ValueError as e:
                    print(f"  skip {va:#x}: {e}", file=sys.stderr)
                    continue
                struct.pack_into("<I", data, base + i * 4, adrp)
                struct.pack_into("<I", data, base + (i + 1) * 4, NOP)
                sites.append({"vaddr": va, "adrp": adrp})

    open(args.out, "wb").write(bytes(data))
    print(f"\n=== paravirtual stubs -> scratch pointer ===\n")
    print(f"scratch page : {scratch:#018x}")
    print(f"sites patched: {len(sites)}")
    for s in sites[:8]:
        print(f"  {s['vaddr']:#018x}   adrp x0, .. ({s['adrp']:#010x}) ; nop")
    if len(sites) > 8:
        print(f"  ... and {len(sites) - 8} more")
    print(f"\nwrote {args.out} ({len(data):,} bytes)")
    print("\nStill a lie, just a better shaped one: the kernel now reads zeros")
    print("from a real page instead of faulting on a null pointer.")

    if args.json:
        json.dump({"scratch": scratch, "sites": sites},
                  open(args.json, "w", encoding="utf-8"), indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
