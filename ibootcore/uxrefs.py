#!/usr/bin/env python3
"""
uxrefs.py -- find references to an address in a userland Mach-O.

xrefs.py works on the kernel collection, whose base comes from loadmap.py. A
plain dylib or executable needs its own slide, and its string references pair an
ADRP with an ADD that need not be the very next instruction. This scans for the
page first and then looks a short way ahead for the matching offset, which finds
references the kernel scanner misses.

Written to read Apple's own AEA handling out of `usr/libexec/diskimagesiod`,
extracted from the restore ramdisk.

Usage:
    python uxrefs.py diskimagesiod 0x100260de4
    python uxrefs.py diskimagesiod --string "wrapped-key failed base64 decode"
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import machobase
import xrefs


def find_refs(data: bytes, base: int, target: int, window: int = 12):
    """Yield the address of each ADRP whose ADD completes to `target`."""
    page = target & ~0xFFF
    offset = target & 0xFFF
    for i in range(0, len(data) - 4, 4):
        (w,) = struct.unpack_from("<I", data, i)
        a = xrefs.adrp_page(w, base + i)
        if not a or a[1] != page:
            continue
        reg = a[0]
        for k in range(1, window + 1):
            j = i + 4 * k
            if j + 4 > len(data):
                break
            (w2,) = struct.unpack_from("<I", data, j)
            ai = xrefs.add_imm(w2)
            if ai and ai[1] == reg and ai[2] == offset:
                yield base + i, base + j
                break


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("binary")
    ap.add_argument("target", nargs="?")
    ap.add_argument("--string", action="append", default=[])
    ap.add_argument("--window", type=int, default=12)
    args = ap.parse_args(argv)

    data = open(args.binary, "rb").read()
    base = machobase.text_base(data)

    targets = []
    if args.target:
        targets.append((int(args.target, 0), args.target))
    for s in args.string:
        i = data.find(s.encode())
        if i < 0:
            print(f"  {s!r}: not present")
            continue
        targets.append((base + i, s))

    for addr, label in targets:
        refs = list(find_refs(data, base, addr, args.window))
        print(f"\n  {label!r} at {addr:#x}: {len(refs)} reference(s)")
        for adrp, add in refs:
            print(f"    adrp {adrp:#x}   add {add:#x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
