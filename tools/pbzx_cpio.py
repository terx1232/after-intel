#!/usr/bin/env python3
"""
pbzx_cpio.py -- decode Apple's pbzx payload streams and the cpio archives
inside them, and report the architecture of every Mach-O member.

Installer packages carry their file payload as a `pbzx` stream: a 4-byte magic,
a big-endian flags word, then repeating [uncompressed_size][compressed_size]
[data] triples where each chunk is XZ-compressed. The concatenated output is a
cpio archive.

Both formats are simple enough to read with the standard library alone, which
means an installer's file listing and per-binary architectures can be recovered
on any OS with no Mac and no Apple tooling.

Usage:
    python pbzx_cpio.py <payload> [--json out.json] [--grep REGEX] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import lzma
import os
import re
import struct
import sys
from collections import Counter

PBZX_MAGIC = b"pbzx"
CPIO_NEWC = b"070701"   # SVR4, hex fields, 4-byte aligned
CPIO_ODC = b"070707"    # POSIX portable, octal fields, no alignment
CPIO_TRAILER = "TRAILER!!!"

CPU = {7: "i386", 0x01000007: "x86_64", 12: "arm", 0x0100000C: "arm64", 18: "ppc"}
S_IFMT, S_IFREG, S_IFDIR, S_IFLNK = 0o170000, 0o100000, 0o040000, 0o120000


def pbzx_decode(raw: bytes) -> bytes:
    """Concatenate every chunk of a pbzx stream into the original bytes."""
    if raw[:4] != PBZX_MAGIC:
        raise ValueError(f"not a pbzx stream (magic {raw[:4]!r})")
    out = bytearray()
    i = 12  # magic(4) + flags(8)
    while i + 16 <= len(raw):
        usize, csize = struct.unpack_from(">QQ", raw, i)
        i += 16
        chunk = raw[i:i + csize]
        i += csize
        if csize == usize:
            out += chunk            # stored verbatim
        else:
            out += lzma.decompress(chunk)
    return bytes(out)


def cpio_iter(data: bytes):
    """Yield (name, mode, filedata) for each cpio member.

    Handles both variants Apple uses. `newc` has hex fields and pads names and
    bodies to a 4-byte boundary; `odc` has octal fields and no padding at all.
    Getting the variant wrong yields zero members rather than an error, so the
    magic is checked per record.
    """
    i = 0
    n = len(data)
    while i + 76 <= n:
        magic = data[i:i + 6]

        if magic == CPIO_NEWC:
            if i + 110 > n:
                break
            f = [int(data[i + 6 + k * 8:i + 14 + k * 8], 16) for k in range(13)]
            mode, filesize, namesize = f[1], f[6], f[11]
            i += 110
            name = data[i:i + namesize - 1].decode("utf-8", "replace")
            i += namesize
            i += (-i) % 4
            body = data[i:i + filesize]
            i += filesize
            i += (-i) % 4

        elif magic == CPIO_ODC:
            # magic(6) dev(6) ino(6) mode(6) uid(6) gid(6) nlink(6) rdev(6)
            # mtime(11) namesize(6) filesize(11) == 76 bytes, all octal ASCII.
            try:
                mode = int(data[i + 18:i + 24], 8)
                namesize = int(data[i + 59:i + 65], 8)
                filesize = int(data[i + 65:i + 76], 8)
            except ValueError:
                break
            i += 76
            name = data[i:i + namesize - 1].decode("utf-8", "replace")
            i += namesize
            body = data[i:i + filesize]
            i += filesize

        else:
            break

        if name == CPIO_TRAILER:
            break
        yield name, mode, body


def macho_arch(b: bytes):
    """Return a list of arch names for a Mach-O, or None."""
    if len(b) < 32:
        return None
    m = b[:4]
    if m in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
        ct, cs = struct.unpack_from("<ii", b, 4)
        name = CPU.get(ct)
        if name is None:
            return None
        if ct == 0x0100000C and (cs & 0xFFFFFF) == 2:
            name = "arm64e"
        return [name]
    if m in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
        wide = m == b"\xca\xfe\xba\xbf"
        (nf,) = struct.unpack_from(">I", b, 4)
        if not (1 <= nf <= 32):
            return None
        esz = 32 if wide else 20
        archs = []
        for k in range(nf):
            off = 8 + k * esz
            if off + 8 > len(b):
                break
            ct, cs = struct.unpack_from(">ii", b, off)
            name = CPU.get(ct)
            if name is None:
                return None
            if ct == 0x0100000C and (cs & 0xFFFFFF) == 2:
                name = "arm64e"
            archs.append(name)
        return archs or None
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("payload")
    ap.add_argument("--json")
    ap.add_argument("--grep")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args(argv)

    raw = open(args.payload, "rb").read()
    print(f"\n=== {os.path.basename(args.payload)} ===")
    print(f"pbzx stream : {len(raw)} bytes")
    data = pbzx_decode(raw)
    print(f"decoded     : {len(data)} bytes ({len(data) / len(raw):.2f}x)")

    members, machos = [], []
    kinds = Counter()
    tally = Counter()
    combos = Counter()

    for name, mode, body in cpio_iter(data):
        fmt = mode & S_IFMT
        kinds["dir" if fmt == S_IFDIR else
              "symlink" if fmt == S_IFLNK else
              "file" if fmt == S_IFREG else "other"] += 1
        rec = {"name": name, "mode": mode, "size": len(body)}
        archs = macho_arch(body) if fmt == S_IFREG else None
        if archs:
            rec["archs"] = archs
            machos.append(rec)
            for a in archs:
                tally[a] += 1
            combos["+".join(archs)] += 1
        members.append(rec)

    print(f"cpio members: {len(members)}  "
          f"({', '.join(f'{k}={v}' for k, v in kinds.most_common())})")
    print(f"Mach-O files: {len(machos)}")

    if tally:
        print("\narchitecture slices:")
        for a, n in tally.most_common():
            print(f"    {a:<10}{n:>6}")
        print("\ncombinations shipped:")
        for c, n in combos.most_common():
            print(f"    {c:<22}{n:>6}")

    x86 = [m for m in machos if any(a in ("x86_64", "i386") for a in m["archs"])]
    print(f"\nbinaries carrying an x86 slice: {len(x86)}")
    sel = x86 if not args.grep else [
        m for m in machos if re.search(args.grep, m["name"], re.I)]
    for m in sorted(sel, key=lambda z: -z["size"])[:args.limit]:
        print(f"    {'+'.join(m['archs']):<18}{m['size']:>11}  {m['name'][:78]}")
    if len(sel) > args.limit:
        print(f"    ... and {len(sel) - args.limit} more")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"payload": os.path.basename(args.payload),
                       "decoded_bytes": len(data),
                       "member_count": len(members),
                       "kinds": dict(kinds),
                       "arch_tally": dict(tally),
                       "combos": dict(combos),
                       "machos": machos}, fh, indent=2)
        print(f"\nwrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
