#!/usr/bin/env python3
"""
macho_audit.py -- inventory the CPU architectures present in a tree of Mach-O binaries.

The point of this tool is to replace opinion with measurement. Given any macOS
system tree, installer payload, kext bundle or framework, it reports exactly
which architecture slices Apple actually shipped -- per file and in aggregate.

Runs on any OS with a stock Python 3.8+. No macOS, no lipo, no dependencies:
it parses the Mach-O and fat headers directly.

Usage:
    python macho_audit.py <path> [<path> ...] [--json out.json] [--quiet]

Exit status is 0 on success, 1 if no Mach-O files were found at all.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from collections import Counter
from dataclasses import dataclass, field

# --- Mach-O constants (from <mach-o/loader.h> and <mach/machine.h>) ----------

MH_MAGIC = 0xFEEDFACE  # 32-bit, host-endian
MH_CIGAM = 0xCEFAEDFE  # 32-bit, byte-swapped
MH_MAGIC_64 = 0xFEEDFACF  # 64-bit, host-endian
MH_CIGAM_64 = 0xCFFAEDFE  # 64-bit, byte-swapped
FAT_MAGIC = 0xCAFEBABE  # universal binary, 32-bit entries
FAT_CIGAM = 0xBEBAFECA
FAT_MAGIC_64 = 0xCAFEBABF  # universal binary, 64-bit entries
FAT_CIGAM_64 = 0xBFBAFECA

CPU_ARCH_ABI64 = 0x01000000
CPU_ARCH_ABI64_32 = 0x02000000

CPU_TYPE_X86 = 7
CPU_TYPE_X86_64 = CPU_TYPE_X86 | CPU_ARCH_ABI64
CPU_TYPE_ARM = 12
CPU_TYPE_ARM64 = CPU_TYPE_ARM | CPU_ARCH_ABI64
CPU_TYPE_ARM64_32 = CPU_TYPE_ARM | CPU_ARCH_ABI64_32
CPU_TYPE_POWERPC = 18
CPU_TYPE_POWERPC64 = CPU_TYPE_POWERPC | CPU_ARCH_ABI64

# arm64 subtypes. The distinction matters more than the architecture itself:
# arm64e binaries carry pointer-authentication (PAC) signatures baked into the
# code, which is the single largest obstacle to any static ARM->x86 translation.
CPU_SUBTYPE_MASK = 0x00FFFFFF
CPU_SUBTYPE_ARM64_ALL = 0
CPU_SUBTYPE_ARM64_V8 = 1
CPU_SUBTYPE_ARM64E = 2

# Mach-O file types we care about telling apart.
MH_FILETYPE = {
    0x1: "object",
    0x2: "executable",
    0x6: "dylib",
    0x7: "dylinker",
    0x8: "bundle",
    0xB: "kext",  # MH_KEXT_BUNDLE
    0xC: "fileset",  # MH_FILESET -- the dyld shared cache / boot kernel collection
}


def arch_name(cputype: int, cpusubtype: int) -> str:
    """Human-readable arch name, matching what `lipo -archs` would print."""
    sub = cpusubtype & CPU_SUBTYPE_MASK
    if cputype == CPU_TYPE_X86_64:
        return "x86_64"
    if cputype == CPU_TYPE_X86:
        return "i386"
    if cputype == CPU_TYPE_ARM64:
        if sub == CPU_SUBTYPE_ARM64E:
            return "arm64e"
        if sub == CPU_SUBTYPE_ARM64_V8:
            return "arm64v8"
        return "arm64"
    if cputype == CPU_TYPE_ARM64_32:
        return "arm64_32"
    if cputype == CPU_TYPE_ARM:
        return "arm"
    if cputype == CPU_TYPE_POWERPC64:
        return "ppc64"
    if cputype == CPU_TYPE_POWERPC:
        return "ppc"
    return f"unknown({cputype:#x}/{sub})"


@dataclass
class Result:
    """Aggregate counters for one audited root."""

    root: str
    files_seen: int = 0
    macho_files: int = 0
    per_arch: Counter = field(default_factory=Counter)
    per_filetype: Counter = field(default_factory=Counter)
    fat_files: int = 0
    thin_files: int = 0
    # Every distinct arch combination found, e.g. ("arm64e", "x86_64"): 1234
    combos: Counter = field(default_factory=Counter)
    entries: list = field(default_factory=list)

    def to_dict(self, include_entries: bool) -> dict:
        d = {
            "root": self.root,
            "files_seen": self.files_seen,
            "macho_files": self.macho_files,
            "fat_files": self.fat_files,
            "thin_files": self.thin_files,
            "per_arch": dict(self.per_arch.most_common()),
            "per_filetype": dict(self.per_filetype.most_common()),
            "combos": {"+".join(k): v for k, v in self.combos.most_common()},
        }
        if include_entries:
            d["entries"] = self.entries
        return d


def _read_header(fh) -> bytes:
    """First 4 KiB is plenty for a fat header with a sane number of arches."""
    return fh.read(4096)


def _thin_arch(head: bytes, offset: int = 0):
    """Decode a thin Mach-O header at `offset`. Returns (arch, filetype) or None."""
    if len(head) < offset + 16:
        return None
    (magic,) = struct.unpack_from(">I", head, offset)
    # We probed with big-endian. Seeing MH_MAGIC means the file really is
    # stored big-endian; seeing the swapped MH_CIGAM means it is little-endian
    # (which every x86_64 and arm64 Mach-O on disk is).
    if magic in (MH_MAGIC, MH_MAGIC_64):
        endian = ">"
    elif magic in (MH_CIGAM, MH_CIGAM_64):
        endian = "<"
    else:
        return None
    cputype, cpusubtype, filetype = struct.unpack_from(endian + "iiI", head, offset + 4)
    return arch_name(cputype, cpusubtype), MH_FILETYPE.get(filetype, f"type{filetype}")


def inspect(path: str):
    """Return (list_of_archs, filetype, is_fat) or None if not a Mach-O."""
    try:
        with open(path, "rb") as fh:
            head = _read_header(fh)
    except (OSError, PermissionError):
        return None
    if len(head) < 8:
        return None

    (magic,) = struct.unpack_from(">I", head, 0)

    # --- universal ("fat") binary -------------------------------------------
    if magic in (FAT_MAGIC, FAT_MAGIC_64, FAT_CIGAM, FAT_CIGAM_64):
        wide = magic in (FAT_MAGIC_64, FAT_CIGAM_64)
        # Fat headers are always big-endian on disk.
        (nfat,) = struct.unpack_from(">I", head, 4)
        if nfat > 64:  # sanity: no real binary has this many slices
            return None
        archs, filetype = [], None
        entry_size = 32 if wide else 20
        for i in range(nfat):
            off = 8 + i * entry_size
            if len(head) < off + entry_size:
                break
            cputype, cpusubtype = struct.unpack_from(">ii", head, off)
            archs.append(arch_name(cputype, cpusubtype))
            # Read the slice's own header to learn the file type.
            if filetype is None:
                if wide:
                    (slice_off,) = struct.unpack_from(">Q", head, off + 8)
                else:
                    (slice_off,) = struct.unpack_from(">I", head, off + 8)
                try:
                    with open(path, "rb") as fh:
                        fh.seek(slice_off)
                        sub = fh.read(16)
                    got = _thin_arch(sub)
                    if got:
                        filetype = got[1]
                except OSError:
                    pass
        if not archs:
            return None
        return archs, filetype or "unknown", True

    # --- thin binary ---------------------------------------------------------
    got = _thin_arch(head)
    if got:
        return [got[0]], got[1], False
    return None


def walk(root: str, keep_entries: bool = False) -> Result:
    res = Result(root=root)
    if os.path.isfile(root):
        candidates = [root]
    else:
        candidates = []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            # dSYM bundles are debug symbols, not shipped code -- they would
            # double-count every binary and distort the ratios.
            dirnames[:] = [d for d in dirnames if not d.endswith(".dSYM")]
            for fn in filenames:
                candidates.append(os.path.join(dirpath, fn))

    for path in candidates:
        if os.path.islink(path):
            continue
        res.files_seen += 1
        got = inspect(path)
        if not got:
            continue
        archs, filetype, is_fat = got
        res.macho_files += 1
        res.fat_files += int(is_fat)
        res.thin_files += int(not is_fat)
        res.per_filetype[filetype] += 1
        for a in archs:
            res.per_arch[a] += 1
        res.combos[tuple(sorted(set(archs)))] += 1
        if keep_entries:
            res.entries.append(
                {
                    "path": os.path.relpath(path, root) if os.path.isdir(root) else path,
                    "archs": archs,
                    "filetype": filetype,
                    "fat": is_fat,
                }
            )
    return res


def report(res: Result, out=sys.stdout) -> None:
    print(f"\n=== {res.root} ===", file=out)
    print(f"files scanned : {res.files_seen}", file=out)
    print(f"Mach-O found  : {res.macho_files}"
          f"  (universal {res.fat_files} / thin {res.thin_files})", file=out)
    if not res.macho_files:
        print("  no Mach-O binaries here", file=out)
        return

    print("\n  architecture slices:", file=out)
    for arch, n in res.per_arch.most_common():
        pct = 100.0 * n / res.macho_files
        print(f"    {arch:<10} {n:>7}  ({pct:5.1f}% of binaries)", file=out)

    print("\n  architecture combinations shipped:", file=out)
    for combo, n in res.combos.most_common():
        print(f"    {'+'.join(combo):<24} {n:>7}", file=out)

    print("\n  Mach-O file types:", file=out)
    for ft, n in res.per_filetype.most_common():
        print(f"    {ft:<12} {n:>7}", file=out)

    # The headline number: can this tree run on an Intel CPU at all?
    x86 = res.per_arch.get("x86_64", 0) + res.per_arch.get("i386", 0)
    arm = sum(v for k, v in res.per_arch.items() if k.startswith("arm64"))
    print("\n  VERDICT:", file=out)
    print(f"    x86 slices : {x86:>7}", file=out)
    print(f"    arm64 slices: {arm:>6}", file=out)
    if x86 == 0 and arm > 0:
        print("    -> ARM-ONLY. Nothing here can execute on an x86 CPU.", file=out)
    elif x86 > 0 and arm == 0:
        print("    -> x86-only tree.", file=out)
    elif x86 and arm:
        print("    -> universal; an x86 machine can run this.", file=out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="files or directories to audit")
    ap.add_argument("--json", metavar="FILE", help="write full results as JSON")
    ap.add_argument("--entries", action="store_true",
                    help="include a per-file listing in the JSON output")
    ap.add_argument("--quiet", action="store_true", help="suppress the text report")
    args = ap.parse_args(argv)

    results = [walk(p, keep_entries=args.entries) for p in args.paths]

    if not args.quiet:
        for r in results:
            report(r)

    if args.json:
        payload = {
            "tool": "macho_audit.py",
            "roots": [r.to_dict(args.entries) for r in results],
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        if not args.quiet:
            print(f"\nwrote {args.json}", file=sys.stderr)

    return 0 if any(r.macho_files for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
