#!/usr/bin/env python3
"""
xnu_arch_check.py -- measure how much x86 support survives in an XNU source tree.

Apple publishes XNU source for each macOS release at
https://github.com/apple-oss-distributions/xnu. macOS 26 Tahoe is the last
release that supports Intel hardware; macOS 27 is Apple-silicon-only.

The open question this tool exists to answer: when Apple publishes the macOS 27
source drop, is the x86 platform code still in the tree, or was it deleted?

That matters because it is the difference between two very different worlds:

  * Code still present -> the kernel can in principle still be built for x86.
    That does not give you a bootable macOS (userland and every driver remain
    closed and ARM-only), but it keeps a Darwin-on-x86 base alive.
  * Code deleted -> even the open part of the stack is ARM-only from here on,
    and every downstream project (PureDarwin, ravynOS) inherits that problem.

Run it against the Tahoe tag first to get a baseline, then against the macOS 27
tag when it appears, and diff the two numbers.

Usage:
    python xnu_arch_check.py <path-to-xnu-source> [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Directories that only exist to support one architecture. Their presence and
# size is the most direct proxy for "is this architecture still a build target".
# Verified against xnu-12377.121.6 (macOS 26.5): these paths all exist in a
# Tahoe checkout, so a "missing" result in a later tree is a real deletion and
# not a wrong guess on our part. Note the ARM side has no pexpert/arm64 or
# kdp/ml/arm64 -- 64-bit ARM shares the .../arm directories.
ARCH_DIRS = {
    "x86": [
        "osfmk/i386",
        "osfmk/x86_64",
        "bsd/dev/i386",
        "pexpert/i386",
        "osfmk/kdp/ml/i386",
        "osfmk/kdp/ml/x86_64",
    ],
    "arm": [
        "osfmk/arm",
        "osfmk/arm64",
        "bsd/dev/arm",
        "bsd/dev/arm64",
        "pexpert/arm",
        "osfmk/kdp/ml/arm",
    ],
}

# The cleanest single signal: the build system keeps one MASTER config per
# supported target. If MASTER.x86_64 disappears, Intel is no longer a target.
BUILD_FILES = ["makedefs/MakeInc.def", "config/MASTER.x86_64", "config/MASTER.arm64"]

SOURCE_EXT = {".c", ".cpp", ".h", ".hpp", ".s", ".S", ".defs", ".mig", ".py"}


def count_tree(root: str, rel: str) -> dict:
    """Count files and source lines under root/rel."""
    path = os.path.join(root, rel.replace("/", os.sep))
    if not os.path.isdir(path):
        return {"exists": False, "files": 0, "lines": 0}
    files = lines = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for fn in filenames:
            if os.path.splitext(fn)[1] not in SOURCE_EXT:
                continue
            files += 1
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, "rb") as fh:
                    lines += fh.read().count(b"\n")
            except OSError:
                pass
    return {"exists": True, "files": files, "lines": lines}


def audit(root: str) -> dict:
    result = {"root": os.path.abspath(root), "arch": {}, "build_files": {}}
    for arch, dirs in ARCH_DIRS.items():
        per_dir = {d: count_tree(root, d) for d in dirs}
        result["arch"][arch] = {
            "dirs": per_dir,
            "dirs_present": sum(1 for v in per_dir.values() if v["exists"]),
            "dirs_total": len(per_dir),
            "files": sum(v["files"] for v in per_dir.values()),
            "lines": sum(v["lines"] for v in per_dir.values()),
        }
    for bf in BUILD_FILES:
        p = os.path.join(root, bf.replace("/", os.sep))
        result["build_files"][bf] = os.path.isfile(p)

    # Enumerate every kernel build target the tree still declares.
    cfg = os.path.join(root, "config")
    result["master_configs"] = sorted(
        f for f in os.listdir(cfg) if f.startswith("MASTER")
    ) if os.path.isdir(cfg) else []
    return result


def report(a: dict, out=sys.stdout) -> None:
    print(f"\n=== XNU architecture audit: {a['root']} ===\n", file=out)
    for arch in ("x86", "arm"):
        info = a["arch"][arch]
        print(f"{arch.upper()} platform code", file=out)
        print(f"  directories present : {info['dirs_present']}/{info['dirs_total']}",
              file=out)
        print(f"  source files        : {info['files']}", file=out)
        print(f"  source lines        : {info['lines']}", file=out)
        for d, v in info["dirs"].items():
            mark = "ok " if v["exists"] else "GONE"
            print(f"    [{mark}] {d:<24} {v['lines']:>8} lines", file=out)
        print(file=out)

    print("build configuration files:", file=out)
    for bf, present in a["build_files"].items():
        print(f"  [{'ok ' if present else 'GONE'}] {bf}", file=out)

    print("\nkernel build targets declared in config/:", file=out)
    for mc in a.get("master_configs", []):
        print(f"  {mc}", file=out)

    x86 = a["arch"]["x86"]["lines"]
    arm = a["arch"]["arm"]["lines"]
    print("\nVERDICT:", file=out)
    if x86 == 0:
        print("  x86 platform code has been REMOVED from this XNU tree.", file=out)
        print("  The open-source kernel can no longer target Intel.", file=out)
    else:
        ratio = 100.0 * x86 / (x86 + arm) if (x86 + arm) else 0
        print(f"  x86 platform code still present: {x86} lines "
              f"({ratio:.1f}% of platform code).", file=out)
        print("  The kernel can still in principle be built for Intel.", file=out)
        print("  NOTE: this says nothing about userland or drivers, which are", file=out)
        print("        closed source and shipped ARM-only from macOS 27 on.", file=out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="path to an XNU source checkout")
    ap.add_argument("--json", metavar="FILE", help="write results as JSON")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.root):
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2

    a = audit(args.root)
    report(a)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(a, fh, indent=2)
        print(f"\nwrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
