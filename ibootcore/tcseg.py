#!/usr/bin/env python3
"""
tcseg.py -- wrap a bare trust cache module in the segment the kernel expects.

`chosen/memory-map/TrustCache` does not point at a trust cache. It points at a
*segment*, which carries an eight byte header before the first module:

    u32 version          1
    u32 offset           where the first module starts, 8 in practice

Handing the kernel a bare module instead panics in kern_trustcache.c, and the
panic proves the layout rather than merely suggesting it. With a version 2
module at the segment start, the kernel read the module's second word - the
first four bytes of its UUID, 0x53aed140 - as that offset, and reported the
module as beginning at 0xfffffe0059aed140, exactly segment_base + 0x53aed140.
A field that is read as an offset is an offset.

    python tcseg.py basesystem.trustcache --out basesystem-tcseg.bin
    python tcseg.py ipsw-tcseg.bin --show
"""

from __future__ import annotations

import argparse
import struct
import sys
import uuid

ENTRY_SIZE = {0: 22, 1: 22, 2: 24}


def describe_module(data: bytes, off: int = 0) -> str:
    version, = struct.unpack_from("<I", data, off)
    uid = uuid.UUID(bytes=data[off + 4:off + 20])
    count, = struct.unpack_from("<I", data, off + 20)
    size = ENTRY_SIZE.get(version)
    body = len(data) - off - 24
    fit = "exact" if size and body == count * size else "does not fit"
    return (f"    version {version}, uuid {uid}, {count} entries, "
            f"{body} bytes of entries ({fit})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("module", help="a bare trust cache, or a segment with --show")
    ap.add_argument("--out")
    ap.add_argument("--show", action="store_true",
                    help="read the file as a segment and report its modules")
    ap.add_argument("--version", type=int, default=1,
                    help="segment header version")
    args = ap.parse_args(argv)

    data = open(args.module, "rb").read()

    if args.show:
        ver, off = struct.unpack_from("<II", data, 0)
        print(f"\n  segment: version {ver}, first module at {off:#x}, "
              f"{len(data):,} bytes")
        print(describe_module(data, off))
        return 0

    print(f"\n  module: {len(data):,} bytes")
    print(describe_module(data))

    seg = struct.pack("<II", args.version, 8) + data
    if args.out:
        open(args.out, "wb").write(seg)
        print(f"\n  wrote {args.out}: {len(seg):,} bytes "
              f"(8 byte header + module)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
