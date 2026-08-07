#!/usr/bin/env python3
"""
zip_carve.py -- recover zip member listings from a raw disk image, and
optionally decompress members to inspect them.

macOS installer images store the operating system payload as zip archives
inside a disk image inside a package. Reading that chain properly means
implementing APFS. This does not: zip local file headers are self-describing
and, crucially, store the **member name uncompressed**, so a linear scan over
the raw bytes recovers the full file listing without any filesystem support.

Members can then be decompressed individually by offset, which makes it
possible to check what architecture a specific binary was built for without
unpacking 16 GB.

Usage:
    python zip_carve.py <image> --start N --length N [--json out.json]
    python zip_carve.py <image> --start N --length N --grep dyld --archcheck
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
import zlib
from collections import Counter

LFH = b"PK\x03\x04"
LFH_SIZE = 30

METHODS = {0: "store", 8: "deflate", 12: "bzip2", 14: "lzma", 93: "zstd",
           95: "xz", 96: "jpeg", 97: "wavpack", 98: "ppmd"}

# Mach-O identification, for --archcheck.
CPU_NAMES = {7: "i386", 0x01000007: "x86_64", 12: "arm", 0x0100000C: "arm64",
             18: "ppc"}
CHUNK = 8 << 20
OVERLAP = 1 << 16


def parse_lfh(buf: bytes, i: int):
    """Parse a local file header at buf[i:]. Returns a dict or None."""
    if i + LFH_SIZE > len(buf):
        return None
    (_sig, ver, flags, method, _t, _d, crc, csize, usize,
     nlen, elen) = struct.unpack_from("<4sHHHHHIIIHH", buf, i)
    if nlen == 0 or nlen > 4096 or elen > 4096:
        return None
    if method not in METHODS:
        return None
    if i + LFH_SIZE + nlen > len(buf):
        return None
    raw = buf[i + LFH_SIZE:i + LFH_SIZE + nlen]
    try:
        name = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    # Member names are paths; reject anything with control characters.
    if any(ord(c) < 32 for c in name):
        return None
    return {
        "name": name, "method": METHODS[method], "method_id": method,
        "flags": flags, "crc32": crc,
        "compressed_size": csize, "uncompressed_size": usize,
        "data_offset_rel": LFH_SIZE + nlen + elen,
        "streamed": bool(flags & 0x08),
    }


def scan(path: str, start: int, length: int, progress=True) -> list:
    out = []
    seen = set()
    end = start + length
    with open(path, "rb") as fh:
        pos = start
        carry = b""
        carry_pos = start
        while pos < end:
            fh.seek(pos)
            block = fh.read(min(CHUNK, end - pos))
            if not block:
                break
            buf = carry + block
            base = carry_pos
            i = buf.find(LFH)
            while i != -1:
                e = parse_lfh(buf, i)
                if e:
                    e["offset"] = base + i
                    e["data_offset"] = base + i + e.pop("data_offset_rel")
                    key = (e["name"], e["crc32"], e["compressed_size"])
                    if key not in seen:
                        seen.add(key)
                        out.append(e)
                i = buf.find(LFH, i + 1)
            carry = buf[-OVERLAP:]
            carry_pos = base + len(buf) - len(carry)
            pos += len(block)
            if progress:
                print(f"\r  {(pos - start) / 2**30:6.2f} / {length / 2**30:.2f} GiB"
                      f"   members: {len(out)}", end="", file=sys.stderr, flush=True)
    if progress:
        print(file=sys.stderr)
    return out


def read_member_head(path: str, entry: dict, want: int = 4096) -> bytes | None:
    """Decompress the first bytes of a member. Returns None if not possible."""
    if entry["streamed"] and not entry["compressed_size"]:
        return None
    with open(path, "rb") as fh:
        fh.seek(entry["data_offset"])
        raw = fh.read(min(entry["compressed_size"] or want * 40, 1 << 22))
    if entry["method_id"] == 0:
        return raw[:want]
    if entry["method_id"] == 8:
        d = zlib.decompressobj(-zlib.MAX_WBITS)
        try:
            return d.decompress(raw, want)
        except zlib.error:
            return None
    if entry["method_id"] == 12:
        import bz2
        try:
            return bz2.BZ2Decompressor().decompress(raw)[:want]
        except OSError:
            return None
    return None


def macho_arch(head: bytes):
    """Identify a Mach-O header. Returns list of arch names, or None."""
    if not head or len(head) < 32:
        return None
    magic = head[:4]
    if magic in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
        cputype, cpusubtype = struct.unpack_from("<ii", head, 4)
        name = CPU_NAMES.get(cputype)
        if name is None:
            return None
        if cputype == 0x0100000C and (cpusubtype & 0xFFFFFF) == 2:
            name = "arm64e"
        return [name]
    if magic in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
        wide = magic == b"\xca\xfe\xba\xbf"
        (nfat,) = struct.unpack_from(">I", head, 4)
        if not (1 <= nfat <= 32):
            return None
        esz = 32 if wide else 20
        archs = []
        for k in range(nfat):
            off = 8 + k * esz
            if off + 8 > len(head):
                break
            cputype, cpusubtype = struct.unpack_from(">ii", head, off)
            n = CPU_NAMES.get(cputype)
            if n is None:
                return None
            if cputype == 0x0100000C and (cpusubtype & 0xFFFFFF) == 2:
                n = "arm64e"
            archs.append(n)
        return archs or None
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--length", type=int, default=None)
    ap.add_argument("--json", metavar="FILE")
    ap.add_argument("--grep", metavar="REGEX",
                    help="only report members whose name matches")
    ap.add_argument("--archcheck", action="store_true",
                    help="decompress matched members and identify Mach-O arch")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    size = os.path.getsize(args.image)
    length = args.length if args.length is not None else size - args.start
    members = scan(args.image, args.start, length, progress=not args.quiet)

    print(f"\n=== zip members carved from {os.path.basename(args.image)} ===")
    print(f"range +{args.start} .. +{args.start + length} "
          f"({length / 2**30:.2f} GiB)\n")
    print(f"members recovered : {len(members)}")

    by_method = Counter(m["method"] for m in members)
    print(f"by compression    : "
          f"{', '.join(f'{k}={v}' for k, v in by_method.most_common())}")
    total_u = sum(m["uncompressed_size"] for m in members)
    print(f"declared uncompressed total : {total_u / 2**30:.2f} GiB")

    sel = members
    if args.grep:
        rx = re.compile(args.grep, re.I)
        sel = [m for m in members if rx.search(m["name"])]
        print(f"\nmatching {args.grep!r}: {len(sel)}")

    arch_tally = Counter()
    shown = 0
    for m in sel:
        if shown >= args.limit:
            break
        line = (f"  {m['name'][:88]:<88} {m['method']:<8}"
                f"{m['uncompressed_size']:>12}")
        if args.archcheck:
            head = read_member_head(args.image, m)
            archs = macho_arch(head)
            m["archs"] = archs
            if archs:
                for a in archs:
                    arch_tally[a] += 1
                line += "  " + "+".join(archs)
            elif head is None:
                line += "  (undecodable)"
        print(line)
        shown += 1
    if len(sel) > shown:
        print(f"  ... and {len(sel) - shown} more")

    if args.archcheck and arch_tally:
        print("\narchitectures among decoded Mach-O members:")
        for a, n in arch_tally.most_common():
            print(f"    {a:<10}{n:>8}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"image": os.path.abspath(args.image),
                       "start": args.start, "length": length,
                       "member_count": len(members),
                       "by_method": dict(by_method),
                       "members": members}, fh, indent=2)
        print(f"\nwrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
