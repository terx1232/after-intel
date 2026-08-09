#!/usr/bin/env python3
"""
bisect_calls.py -- find which call inside a function never returns.

AppleVirtIOPCITransport::start is entered and never reaches its single return
instruction, which was established by trapping that instruction and watching it
not fire. So it blocks inside, in some call that does not come back. Its nub
sits at busy 1 forever, the driver shows as attached, and no child nub is ever
published.

Trapping every call and iterating would cost one boot per call. Bisecting costs
log2 of them. This patches `brk #0` over the call sites from index k onward: if
a trap fires, execution reached call k, so the block is later; if none fires,
the block is at or before k. Six boots settle forty calls.

The trap is `brk #0` because it panics with a full register dump and clobbers
nothing, so the site that fires is read straight off the panic line.

Usage:
    python bisect_calls.py --list
    python bisect_calls.py --from 20 --out patched.kernel
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loadmap

KERNEL = r"D:\macos\ibootcore-build\vma2-msi.kernel"
FUNC_LO = 0xFFFFFE0008A29E24        # AppleVirtIOPCITransport::start
FUNC_HI = 0xFFFFFE0008A2A54C


def call_sites(data: bytes, base: int, lo: int, hi: int) -> list:
    """Every BL and BLRAA in the range, in address order."""
    out = []
    for pc in range(lo, hi, 4):
        (w,) = struct.unpack_from("<I", data, pc - base)
        if (w & 0xFC000000) == 0x94000000:              # BL
            out.append((pc, "bl"))
        elif (w & 0xFFFFFC00) == 0xD73F0800:            # BLRAA Xn, Xm
            out.append((pc, "blraa"))
        elif (w & 0xFFFFFC1F) == 0xD63F0000:            # BLR Xn
            out.append((pc, "blr"))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kernel", default=KERNEL)
    ap.add_argument("--lo", default=hex(FUNC_LO))
    ap.add_argument("--hi", default=hex(FUNC_HI))
    ap.add_argument("--from", dest="start", type=int, default=0,
                    help="trap call sites from this index onward")
    ap.add_argument("--out")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)

    base = loadmap.parse(args.kernel)["vm_low"]
    data = bytearray(open(args.kernel, "rb").read())
    sites = call_sites(data, base, int(args.lo, 0), int(args.hi, 0))

    if args.list:
        print(f"\n  {len(sites)} call sites in "
              f"{int(args.lo, 0):#x}..{int(args.hi, 0):#x}\n")
        for i, (pc, kind) in enumerate(sites):
            print(f"   {i:>3}  {pc:#018x}  {kind}")
        return 0

    if not args.out:
        ap.error("give --out, or --list")

    shutil.copyfile(args.kernel, args.out)
    out = bytearray(open(args.out, "rb").read())
    sel = sites[args.start:]
    for pc, _ in sel:
        struct.pack_into("<I", out, pc - base, 0xD4200000)
    open(args.out, "wb").write(bytes(out))

    print(f"\n  {len(sites)} call sites, trapping from index {args.start} "
          f"({len(sel)} traps)")
    if sel:
        print(f"  first trapped: {sel[0][0]:#x}   last: {sel[-1][0]:#x}")
    print(f"  wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
