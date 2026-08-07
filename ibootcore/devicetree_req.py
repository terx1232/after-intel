#!/usr/bin/env python3
"""
devicetree_req.py -- derive the device tree a kernel collection expects, from
the kernel itself.

Step two of IbootCore. `boot_args.deviceTreeP` points at a flattened device
tree, and the kernel will not get far without one that its platform drivers can
match against. Rather than guessing at that tree, this reads the requirements
out of the kernel: an `MH_FILESET` collection carries every bundled kext's
Info.plist in its `__PRELINK_INFO` segment as an XML property list, and IOKit
matching dictionaries state exactly which node names and provider classes each
driver expects.

`IONameMatch` is the load-bearing key. On ARM platforms drivers bind to device
tree nodes by name or compatible string, so the union of every `IONameMatch`
across the collection is a lower bound on the node names the tree must contain.

Usage:
    python devicetree_req.py <kernel> [--json out.json] [--grep REGEX]
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import struct
import sys
from collections import Counter, defaultdict

LC_SEGMENT_64 = 0x19

# Drivers whose presence indicates a platform-level device tree node rather
# than a bus-enumerated device.
PLATFORM_HINTS = ("Platform", "GIC", "AIC", "PMU", "IOP", "Serial", "UART",
                  "Timer", "CPU", "Memory", "Clock", "Power", "WDT")


def prelink_info(path: str) -> dict:
    b = open(path, "rb").read()
    ncmds = struct.unpack_from("<I", b, 16)[0]
    off = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", b, off)
        if cmdsize == 0:
            break
        if cmd == LC_SEGMENT_64:
            name = b[off + 8:off + 24].split(b"\x00")[0]
            if name == b"__PRELINK_INFO":
                fileoff, filesize = struct.unpack_from("<QQ", b, off + 24 + 16)
                blob = b[fileoff:fileoff + filesize]
                end = blob.rfind(b"</plist>")
                if end != -1:
                    blob = blob[:end + 8]
                return plistlib.loads(blob)
        off += cmdsize
    raise ValueError("no __PRELINK_INFO segment found")


def collect(info: dict) -> dict:
    kexts = info.get("_PrelinkInfoDictionary", [])
    name_match = Counter()
    provider = Counter()
    ioclass = Counter()
    by_node = defaultdict(list)
    personalities = 0

    for k in kexts:
        bundle = k.get("CFBundleIdentifier", "?")
        pers = k.get("IOKitPersonalities") or {}
        for pname, p in pers.items():
            if not isinstance(p, dict):
                continue
            personalities += 1
            prov = p.get("IOProviderClass")
            if prov:
                provider[prov] += 1
            cls = p.get("IOClass")
            if cls:
                ioclass[cls] += 1
            nm = p.get("IONameMatch")
            if nm is None:
                continue
            names = nm if isinstance(nm, list) else [nm]
            for n in names:
                if not isinstance(n, str):
                    continue
                name_match[n] += 1
                by_node[n].append({"bundle": bundle, "personality": pname,
                                   "IOClass": cls, "IOProviderClass": prov})

    return {
        "kext_count": len(kexts),
        "personality_count": personalities,
        "name_match": dict(name_match.most_common()),
        "provider_class": dict(provider.most_common()),
        "io_class_count": len(ioclass),
        "by_node": {k: v for k, v in by_node.items()},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("--json")
    ap.add_argument("--grep", help="only show nodes matching this regex")
    ap.add_argument("--limit", type=int, default=45)
    args = ap.parse_args(argv)

    info = prelink_info(args.kernel)
    r = collect(info)

    print(f"\n=== device tree requirements: {os.path.basename(args.kernel)} ===\n")
    print(f"kexts in collection     : {r['kext_count']}")
    print(f"IOKit personalities     : {r['personality_count']}")
    print(f"distinct IONameMatch    : {len(r['name_match'])}")
    print(f"distinct IOProviderClass: {len(r['provider_class'])}")

    print("\nprovider classes the collection binds to:")
    for p, n in list(r["provider_class"].items())[:20]:
        print(f"    {p:<44}{n:>5}")

    nodes = r["name_match"]
    if args.grep:
        rx = re.compile(args.grep, re.I)
        nodes = {k: v for k, v in nodes.items() if rx.search(k)}
        print(f"\ndevice tree node names matching {args.grep!r}: {len(nodes)}")
    else:
        print(f"\ndevice tree node names the kernel's drivers expect "
              f"({len(nodes)} distinct):")

    for name, n in list(nodes.items())[:args.limit]:
        who = r["by_node"].get(name, [])
        first = who[0]["bundle"] if who else ""
        flag = "  <- platform" if any(h.lower() in name.lower()
                                      for h in PLATFORM_HINTS) else ""
        print(f"    {name:<40}{n:>4}  {first[:38]}{flag}")
    if len(nodes) > args.limit:
        print(f"    ... and {len(nodes) - args.limit} more (full list in --json)")

    print("\nThese names are a lower bound on what the flattened device tree")
    print("must contain. They say which nodes drivers look for, not the")
    print("properties each node must carry - that still has to be established.")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(r, fh, indent=2)
        print(f"\nwrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
