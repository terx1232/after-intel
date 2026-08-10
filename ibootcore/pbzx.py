#!/usr/bin/env python3
"""
pbzx.py -- decode the payload stream inside InstallAssistant.

The full macOS system is not shipped as an image. It is 52 chunks in
`AssetData/payloadv2/`, 7.9 GB compressed, that the installer assembles. Each
chunk begins with Apple's pbzx container:

    magic     "pbzx" or "pbzm", four bytes
    uint64    chunk size, big-endian
    then repeating:
        uint64  uncompressed length, big-endian
        uint64  compressed length, big-endian
        bytes   the block - an XZ stream, or stored verbatim when the two
                lengths are equal

Concatenating the decoded blocks of all 52 chunks in order gives the payload
stream. Nothing here is Apple's code: the format is a container, and lzma is in
the standard library.

Usage:
    python pbzx.py payload.000 --out decoded.bin --limit 4
    python pbzx.py payload.000 --peek
"""

from __future__ import annotations

import argparse
import lzma
import struct
import sys

MAGICS = (b"pbzx", b"pbzm")


def blocks(f):
    """Yield decoded blocks from an open pbzx stream."""
    magic = f.read(4)
    if magic not in MAGICS:
        raise ValueError(f"not a pbzx container: {magic!r}")
    (chunk_size,) = struct.unpack(">Q", f.read(8))
    while True:
        head = f.read(16)
        if len(head) < 16:
            return
        ulen, clen = struct.unpack(">QQ", head)
        data = f.read(clen)
        if len(data) < clen:
            return
        if clen == ulen:
            yield data                      # stored
        else:
            yield lzma.decompress(data)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chunk")
    ap.add_argument("--out")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after this many blocks; 0 means all")
    ap.add_argument("--peek", action="store_true",
                    help="decode the first block and show what it looks like")
    args = ap.parse_args(argv)

    with open(args.chunk, "rb") as f:
        out = open(args.out, "wb") if args.out else None
        total = n = 0
        first = b""
        for i, b in enumerate(blocks(f)):
            if i == 0:
                first = b[:64]
            total += len(b)
            n += 1
            if out:
                out.write(b)
            if args.limit and n >= args.limit:
                break
        if out:
            out.close()

    print(f"\n  {n} block(s), {total:,} bytes decoded")
    if args.peek and first:
        text = "".join(chr(c) if 32 <= c < 127 else "." for c in first)
        print(f"  first bytes  {first[:16].hex(' ')}")
        print(f"  as text      {text}")
    if args.out:
        print(f"  wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
