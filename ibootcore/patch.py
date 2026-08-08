#!/usr/bin/env python3
"""
patch.py -- apply instruction patches to a kernel collection by virtual address.

Bring-up technique, not a fix. When a kernel stops on something the machine
cannot provide, the way forward is to stub that thing out and see where it
stops next. Each patch buys one more stretch of execution and one more piece of
information about what the kernel actually needs.

Patches are recorded in a list so the set applied to any given image is always
visible, and every patch prints the instruction it replaced so a wrong address
shows up immediately rather than silently corrupting the image.

Usage:
    python patch.py <kernel> --out <patched> --list
    python patch.py <kernel> --out <patched> --apply skip-pv-pac
    python patch.py <kernel> --out <patched> --at 0xfffffe0009e40350 --word 0xd2800000
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys

NOP = 0xD503201F
MOVZ_X0_0 = 0xD2800000        # movz x0, #0

# Named patch sets. Each entry: (virtual address, replacement word, why).
PATCHES = {
    "skip-pv-pac": [
        (0xFFFFFE0009E40350, MOVZ_X0_0,
         "hvc #0 for SMCCC 0xC1000000 (CPU Service Calls). QEMU's virt machine "
         "returns NOT_SUPPORTED, and the kernel then spins on cbnz x0. "
         "Replacing the call with x0 = 0 makes the check fall through, which "
         "pretends the paravirtualised service succeeded."),
    ],
}


def vaddr_to_off(kernel: str, va: int) -> int:
    """A kernel collection maps 1:1, so the offset is va - virtBase."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import loadmap
    m = loadmap.parse(kernel)
    if m["vm_span"] != m["file_size"]:
        raise ValueError("collection does not map 1:1; per-segment lookup needed")
    off = va - m["vm_low"]
    if not (0 <= off < m["file_size"]):
        raise ValueError(f"{va:#x} is outside the image")
    return off


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("--out")
    ap.add_argument("--apply", action="append", default=[],
                    help="name of a patch set to apply")
    ap.add_argument("--at", help="virtual address for an ad-hoc patch")
    ap.add_argument("--word", help="replacement instruction word")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)

    if args.list:
        print("\navailable patch sets:\n")
        for name, entries in PATCHES.items():
            print(f"  {name}")
            for va, word, why in entries:
                print(f"      {va:#018x} <- {word:#010x}")
                print(f"          {why}")
        return 0

    if not args.out:
        ap.error("--out is required when applying patches")

    data = bytearray(open(args.kernel, "rb").read())
    todo = []
    for name in args.apply:
        if name not in PATCHES:
            print(f"unknown patch set {name!r}", file=sys.stderr)
            return 2
        todo += PATCHES[name]
    if args.at:
        if not args.word:
            ap.error("--at needs --word")
        todo.append((int(args.at, 0), int(args.word, 0), "ad-hoc"))

    if not todo:
        ap.error("nothing to apply; use --apply or --at/--word")

    print(f"\n=== patching {os.path.basename(args.kernel)} ===\n")
    applied = []
    for va, word, why in todo:
        off = vaddr_to_off(args.kernel, va)
        (old,) = struct.unpack_from("<I", data, off)
        struct.pack_into("<I", data, off, word)
        print(f"  {va:#018x}  (offset {off:#x})")
        print(f"      {old:#010x} -> {word:#010x}")
        print(f"      {why}")
        applied.append({"vaddr": va, "offset": off, "old": old, "new": word,
                        "why": why})

    open(args.out, "wb").write(bytes(data))
    print(f"\nwrote {args.out} ({len(data):,} bytes, {len(applied)} patch(es))")

    manifest = os.path.splitext(args.out)[0] + "-patches.json"
    json.dump({"kernel": os.path.basename(args.kernel), "patches": applied},
              open(manifest, "w", encoding="utf-8"), indent=2)
    print(f"wrote {manifest}")
    print("\nThese are stubs for bring-up, not fixes. Each one hides a service "
          "the machine\ndoes not provide, so anything reached past it is "
          "running on a pretence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
