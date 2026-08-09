#!/usr/bin/env python3
"""
im4p.py -- unwrap an Image4 payload and decompress it.

Apple ships firmware payloads as IM4P: a short DER sequence carrying a
four-character type, a build description and an octet string, which is usually
LZFSE-compressed and starts with the magic `bvx2`.

    SEQUENCE {
        IA5String    "IM4P"
        IA5String    "dtre"                          <- payload type
        IA5String    "EmbeddedDeviceTrees-12661..."  <- what built it
        OCTET STRING <payload>
    }

Written to open `DeviceTree.vma2macosap.im4p`, Apple's own flattened device tree
for the Apple Virtual Machine. Every property in devicetree.py before this was
recovered a piece at a time from driver strings, assertion messages and IOKit
matching dictionaries, at a cost of several boots per property. This is the
same data first-hand.

Usage:
    python im4p.py DeviceTree.vma2macosap.im4p --out devicetree.bin
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import im4m_props


def payload(buf: bytes) -> tuple[str, str, bytes]:
    """Return (type, description, raw payload) from an IM4P."""
    if b"IM4P" not in buf[:32]:
        raise ValueError("does not look like an IM4P")

    strings, octets = [], []
    for tag, body, stop, _d in im4m_props.walk(buf, 0, len(buf)):
        if tag == 0x16:                       # IA5String
            strings.append(buf[body:stop].decode("ascii", "replace"))
        elif tag == 0x04:                     # OCTET STRING
            octets.append(buf[body:stop])
    if not octets:
        raise ValueError("no octet string in the IM4P")
    # The payload is the longest octet string; the short ones are hashes and
    # key material that some payloads carry alongside it.
    blob = max(octets, key=len)
    kind = strings[1] if len(strings) > 1 else "?"
    desc = strings[2] if len(strings) > 2 else ""
    return kind, desc, blob


def decompress(blob: bytes) -> bytes:
    """Inflate the payload if it is compressed, else return it unchanged."""
    if blob[:4] in (b"bvx2", b"bvx1", b"bvxn", b"bvx-"):
        import liblzfse
        return liblzfse.decompress(blob)
    if blob[:4] == b"comp":                   # legacy lzss container
        import struct
        (dlen,) = struct.unpack_from(">I", blob, 0x10)
        raise NotImplementedError(f"lzss payload, {dlen} bytes")
    return blob


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("im4p")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    buf = open(args.im4p, "rb").read()
    kind, desc, blob = payload(buf)
    print(f"\n=== {os.path.basename(args.im4p)} ===\n")
    print(f"  type        {kind}")
    print(f"  built by    {desc}")
    print(f"  payload     {len(blob):,} bytes, magic {blob[:4]!r}")

    out = decompress(blob)
    open(args.out, "wb").write(out)
    print(f"  decompressed{len(out):>8,} bytes -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
