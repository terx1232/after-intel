#!/usr/bin/env python3
"""
machobase.py -- find a Mach-O's __TEXT base and locate a string in it.

The kernel tools in this project all assume the collection's load map. Reading a
userland dylib needs the same two facts from a plain Mach-O: where __TEXT is
mapped, so file offsets can be turned into addresses, and where a given string
sits, so its references can be found the way strctx.py and xrefs.py find them in
the kernel.

Usage:
    python machobase.py /path/to/binary
    python machobase.py /path/to/binary --find "Can't decrypt wrapped key"
"""

from __future__ import annotations

import argparse
import struct
import sys

LC_SEGMENT_64 = 0x19
MH_MAGIC_64 = 0xFEEDFACF


def segments(data: bytes):
    (magic,) = struct.unpack_from("<I", data, 0)
    if magic != MH_MAGIC_64:
        raise ValueError(f"not a 64-bit Mach-O: magic {magic:#x}")
    ncmds = struct.unpack_from("<I", data, 16)[0]
    off = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, off)
        if cmd == LC_SEGMENT_64:
            name = data[off + 8:off + 24].split(b"\x00")[0].decode()
            vm, vs, fo, fs = struct.unpack_from("<QQQQ", data, off + 24)
            yield name, vm, vs, fo, fs
        off += size


def text_base(data: bytes) -> int:
    for name, vm, _vs, fo, _fs in segments(data):
        if name == "__TEXT":
            return vm - fo
    raise ValueError("no __TEXT segment")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("binary")
    ap.add_argument("--find", action="append", default=[],
                    help="a string to locate; may be repeated")
    args = ap.parse_args(argv)

    data = open(args.binary, "rb").read()
    print(f"\n=== {args.binary} ({len(data):,} bytes) ===\n")
    for name, vm, vs, fo, fs in segments(data):
        print(f"  {name:<16} vm {vm:#014x} +{vs:#x}   file {fo:#x} +{fs:#x}")
    base = text_base(data)
    print(f"\n  slide: file offset + {base:#x} = virtual address")

    for needle in args.find:
        nb = needle.encode()
        i = data.find(nb)
        while i >= 0:
            print(f"  {needle!r}: file {i:#x}  va {base + i:#x}")
            i = data.find(nb, i + 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
