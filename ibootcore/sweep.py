#!/usr/bin/env python3
"""
sweep.py -- find which functions of a kext actually execute, by trapping them.

AppleVirtIOPCITransport attaches to the disk and then publishes nothing, and the
one function known to belong to it - the publish helper at 0xfffffe0008a2b09c -
never runs. Finding where it turns back needs its `start`, and there are no
symbols.

There is a way to enumerate a kext's functions without them. `__DATA_CONST`
carries a sorted table of (function address, metadata) pairs; walking it while
the value stays inside the kext's text yields every entry point. This puts
`brk #0` at all of them, boots, and reports the first that fires - a break panics
with a register dump and clobbers nothing.

Most of what fires is the kext loader walking constructors and initialisers, so
those get excluded and the sweep runs again. Two filters do the bulk of it:
functions containing a call to OSMetaClass's constructor are dropped statically,
and everything the loader reaches is dropped as it is found. The exclusion list
persists between runs so each invocation costs one boot.

Usage:
    python sweep.py --patch out.kernel            # emit the next round
    python sweep.py --exclude 0xfffffe0008a43320  # record a hit and move on
    python sweep.py --list
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loadmap
import xrefs

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "data", "sweep-state.json")

KERNEL = r"D:\macos\ibootcore-build\vma2-msi.kernel"
TABLE_ANCHOR = 0xFFFFFE000AFFFD48        # a known entry in the kext's table
TEXT_LO, TEXT_HI = 0xFFFFFE0008A102E0, 0xFFFFFE0008A442FB
METACLASS_CTOR = 0xFFFFFE0008A4372C      # the kext's thunk to OSMetaClass


def function_table(data: bytes, base: int) -> list:
    """Every function entry point in the kext, from the __DATA_CONST table."""
    out = set()
    for step in (-16, 16):
        va = TABLE_ANCHOR
        while True:
            va += step
            off = va - base
            if not (0 <= off < len(data) - 8):
                break
            (w,) = struct.unpack_from("<Q", data, off)
            if not (TEXT_LO <= w < TEXT_HI):
                break
            out.add(w)
    return sorted(out)


def constructors(data: bytes, base: int, fl: list) -> set:
    """Functions that call the OSMetaClass constructor - run at load, not use."""
    bad = set()
    for pc in range(TEXT_LO, TEXT_HI, 4):
        (w,) = struct.unpack_from("<I", data, pc - base)
        t = xrefs.branch_target(w, pc)
        if t and t[0] == METACLASS_CTOR:
            i = bisect.bisect_right(fl, pc) - 1
            if i >= 0:
                bad.add(fl[i])
    return bad


def load_state() -> dict:
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"excluded": [], "hits": []}


def save_state(s: dict) -> None:
    json.dump(s, open(STATE, "w"), indent=1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patch", metavar="OUT")
    ap.add_argument("--exclude", metavar="ADDR",
                    help="record an address that fired and exclude it from now on")
    ap.add_argument("--caller", metavar="ADDR", default="",
                    help="the lr it fired with, kept for the record")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--kernel", default=KERNEL)
    args = ap.parse_args(argv)

    state = load_state()

    if args.exclude:
        a = int(args.exclude, 0)
        if a not in state["excluded"]:
            state["excluded"].append(a)
            state["hits"].append({"pc": hex(a), "lr": args.caller})
            save_state(state)
        print(f"  excluded {a:#x}; {len(state['excluded'])} total")
        return 0

    if args.list:
        print(f"\n  {len(state['excluded'])} excluded")
        for h in state["hits"]:
            print(f"    {h['pc']}   lr {h['lr']}")
        return 0

    if not args.patch:
        ap.error("give --patch, --exclude or --list")

    base = loadmap.parse(args.kernel)["vm_low"]
    data = bytearray(open(args.kernel, "rb").read())
    fl = function_table(data, base)
    ctors = constructors(data, base, fl)
    excluded = set(state["excluded"]) | ctors
    sel = [f for f in fl if f not in excluded]

    shutil.copyfile(args.kernel, args.patch)
    out = bytearray(open(args.patch, "rb").read())
    for f in sel:
        struct.pack_into("<I", out, f - base, 0xD4200000)
    open(args.patch, "wb").write(bytes(out))

    print(f"\n  functions in table   {len(fl)}")
    print(f"  metaclass ctors      {len(ctors)}")
    print(f"  excluded by hits     {len(state['excluded'])}")
    print(f"  trapped this round   {len(sel)}")
    print(f"  wrote {args.patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
