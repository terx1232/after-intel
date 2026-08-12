#!/usr/bin/env python3
"""
findlabel.py -- locate a two-character label tail in arm64 code.

The AEA key labels are assembled register-side, not stored as strings: a MOVZ
carries the length with "AEA_" in the high half, and the remaining characters
arrive as a separate 16-bit MOVZ plus STRH. constscan.py catches the eight-byte
labels; the six- and seven-byte ones need this, which searches for the tail
immediate and prints the surrounding code.

Usage:
    python findlabel.py libAppleArchive.dylib SK
    python findlabel.py libAppleArchive.dylib CK --context 0x50
"""

from __future__ import annotations

import argparse
import struct
import sys

import capstone


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("binary")
    ap.add_argument("tail", help="the two characters after AEA_, e.g. SK")
    ap.add_argument("--context", default="0x40")
    ap.add_argument("--max", type=int, default=3)
    args = ap.parse_args(argv)

    data = open(args.binary, "rb").read()
    imm = int.from_bytes(args.tail.encode()[:2], "little")
    ctx = int(args.context, 0)
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)

    hits = []
    for off in range(0, len(data) - 4, 4):
        (w,) = struct.unpack_from("<I", data, off)
        if (w & 0xFF800000) == 0x52800000 and ((w >> 5) & 0xFFFF) == imm:
            hits.append(off)

    print(f"\n  {args.tail!r} is {imm:#06x}: {len(hits)} site(s) "
          f"{', '.join(hex(h) for h in hits[:8])}\n")
    for s in hits[:args.max]:
        print(f"  --- {s:#x} ---")
        for ins in md.disasm(data[s:s + ctx], s):
            print(f"     {ins.address:#8x}  {ins.mnemonic:<8} {ins.op_str}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
