#!/usr/bin/env python3
"""
image_arch_scan.py -- scan a raw disk image or byte range for Mach-O headers
and tally the CPU architectures present.

Reading APFS from scratch is a project of its own. This sidesteps it: Mach-O
headers are self-identifying and structurally checkable, so a linear scan over
the raw bytes finds every uncompressed binary in an image without understanding
the filesystem at all.

The point is to answer one question about a macOS installer directly, from the
bytes Apple shipped, rather than from a press release: does it contain any x86
code?

False positives are the obvious risk with magic-number scanning, so every hit is
validated against the rest of the header -- cputype must be a known value,
filetype must be in range, and the load-command count and size must be sane.
Unvalidated hits are counted separately and reported, so the noise floor is
visible rather than hidden.

Usage:
    python image_arch_scan.py <file> [--start N] [--length N] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from collections import Counter

MH_MAGIC_64 = 0xFEEDFACF
MH_MAGIC_32 = 0xFEEDFACE
FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF

CPU_ARCH_ABI64 = 0x01000000
CPU_TYPE_X86 = 7
CPU_TYPE_X86_64 = CPU_TYPE_X86 | CPU_ARCH_ABI64
CPU_TYPE_ARM = 12
CPU_TYPE_ARM64 = CPU_TYPE_ARM | CPU_ARCH_ABI64
CPU_TYPE_POWERPC = 18

CPU_NAMES = {
    CPU_TYPE_X86: "i386",
    CPU_TYPE_X86_64: "x86_64",
    CPU_TYPE_ARM: "arm",
    CPU_TYPE_ARM64: "arm64",
    CPU_TYPE_POWERPC: "ppc",
}
CPU_SUBTYPE_ARM64E = 2
MAX_FILETYPE = 12

# Little-endian on-disk byte patterns for the thin magics, and the big-endian
# ones for fat headers (fat headers are always stored big-endian).
NEEDLES = {
    b"\xcf\xfa\xed\xfe": "thin64",
    b"\xce\xfa\xed\xfe": "thin32",
    b"\xca\xfe\xba\xbe": "fat",
    b"\xca\xfe\xba\xbf": "fat64",
}

CHUNK = 8 << 20   # 8 MiB read window
OVERLAP = 4096    # enough to hold any header we inspect across a boundary


def arch_name(cputype: int, cpusubtype: int) -> str:
    base = CPU_NAMES.get(cputype)
    if base is None:
        return None
    if cputype == CPU_TYPE_ARM64 and (cpusubtype & 0x00FFFFFF) == CPU_SUBTYPE_ARM64E:
        return "arm64e"
    return base


def check_thin(buf: bytes, off: int, wide: bool):
    """Validate a thin Mach-O header at buf[off:]. Returns arch name or None."""
    need = 32 if wide else 28
    if off + need > len(buf):
        return None
    cputype, cpusubtype, filetype, ncmds, sizeofcmds = struct.unpack_from(
        "<iiIII", buf, off + 4)
    if cputype not in CPU_NAMES:
        return None
    if not (1 <= filetype <= MAX_FILETYPE):
        return None
    if not (1 <= ncmds <= 4096):
        return None
    if not (8 <= sizeofcmds <= (1 << 22)):
        return None
    return arch_name(cputype, cpusubtype)


def check_fat(buf: bytes, off: int, wide: bool):
    """Validate a fat header. Returns list of arch names or None."""
    if off + 8 > len(buf):
        return None
    (nfat,) = struct.unpack_from(">I", buf, off + 4)
    if not (1 <= nfat <= 32):
        return None
    esz = 32 if wide else 20
    if off + 8 + nfat * esz > len(buf):
        return None
    archs = []
    for i in range(nfat):
        cputype, cpusubtype = struct.unpack_from(">ii", buf, off + 8 + i * esz)
        a = arch_name(cputype, cpusubtype)
        if a is None:
            return None
        archs.append(a)
    return archs


def scan(path: str, start: int, length: int, progress=True) -> dict:
    end = start + length
    per_arch = Counter()
    machos = 0
    fats = 0
    rejected = Counter()
    first_hits = []

    with open(path, "rb") as fh:
        pos = start
        carry = b""
        carry_pos = start
        read_total = 0
        while pos < end:
            fh.seek(pos)
            want = min(CHUNK, end - pos)
            block = fh.read(want)
            if not block:
                break
            buf = carry + block
            base = carry_pos
            read_total += len(block)

            for needle, kind in NEEDLES.items():
                i = buf.find(needle)
                while i != -1:
                    abs_off = base + i
                    if kind == "thin64":
                        got = check_thin(buf, i, True)
                    elif kind == "thin32":
                        got = check_thin(buf, i, False)
                    elif kind == "fat":
                        got = check_fat(buf, i, False)
                    else:
                        got = check_fat(buf, i, True)

                    if got is None:
                        rejected[kind] += 1
                    else:
                        if isinstance(got, list):
                            fats += 1
                            machos += 1
                            for a in got:
                                per_arch[a] += 1
                        else:
                            machos += 1
                            per_arch[got] += 1
                        if len(first_hits) < 40:
                            first_hits.append({"offset": abs_off, "kind": kind,
                                               "arch": got})
                    i = buf.find(needle, i + 1)

            carry = buf[-OVERLAP:]
            carry_pos = base + len(buf) - len(carry)
            pos += len(block)
            if progress:
                pct = 100.0 * (pos - start) / length
                print(f"\r  scanned {read_total / 2**30:6.2f} GiB "
                      f"({pct:5.1f}%)  validated Mach-O: {machos}",
                      end="", file=sys.stderr, flush=True)
    if progress:
        print(file=sys.stderr)

    return {
        "path": os.path.abspath(path),
        "start": start,
        "length": length,
        "validated_macho_headers": machos,
        "fat_headers": fats,
        "per_arch": dict(per_arch.most_common()),
        "rejected_magic_hits": dict(rejected),
        "sample_hits": first_hits,
    }


def report(r: dict, out=sys.stdout) -> None:
    print(f"\n=== Mach-O architecture scan ===", file=out)
    print(f"file   : {r['path']}", file=out)
    print(f"range  : +{r['start']} .. +{r['start'] + r['length']} "
          f"({r['length'] / 2**30:.2f} GiB)\n", file=out)
    print(f"validated Mach-O headers : {r['validated_macho_headers']}", file=out)
    print(f"  of which universal     : {r['fat_headers']}", file=out)

    if r["per_arch"]:
        print("\narchitecture slices found:", file=out)
        for a, n in r["per_arch"].items():
            print(f"    {a:<10}{n:>9}", file=out)
    else:
        print("\n  no validated Mach-O headers found in this range", file=out)

    print("\nmagic hits rejected by header validation (noise floor):", file=out)
    for k, n in r["rejected_magic_hits"].items():
        print(f"    {k:<10}{n:>9}", file=out)

    x86 = r["per_arch"].get("x86_64", 0) + r["per_arch"].get("i386", 0)
    arm = sum(v for k, v in r["per_arch"].items() if k.startswith("arm"))
    print("\nVERDICT:", file=out)
    print(f"    x86 slices   : {x86}", file=out)
    print(f"    arm slices   : {arm}", file=out)
    if r["validated_macho_headers"] == 0:
        print("    -> nothing readable. The payload is compressed or", file=out)
        print("       encrypted; a linear scan cannot see inside it.", file=out)
    elif x86 == 0:
        print("    -> ARM-ONLY among readable binaries.", file=out)
    elif arm == 0:
        print("    -> x86-only among readable binaries.", file=out)
    else:
        print("    -> both present among readable binaries.", file=out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--length", type=int, default=None)
    ap.add_argument("--json", metavar="FILE")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    size = os.path.getsize(args.path)
    length = args.length if args.length is not None else size - args.start
    r = scan(args.path, args.start, length, progress=not args.quiet)
    report(r)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(r, fh, indent=2)
        print(f"\nwrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
