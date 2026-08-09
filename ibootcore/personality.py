#!/usr/bin/env python3
"""
personality.py -- print whole IOKit matching dictionaries from a collection.

devicetree_req.py answers "which node names does the collection look for", which
is the right question when building a tree from nothing. It is the wrong
question once the tree matches a platform driver and the next link in the chain
has to be found, because that link is named by IOProviderClass and IOClass, not
by a device tree node at all: AppleVirtIOTransport is a provider for twenty
personalities and appears nowhere in any device tree.

This prints the personalities themselves, filtered by any key, so a chain can be
walked in either direction:

    python personality.py <kernel> --class VirtIO       what VirtIO drivers exist
    python personality.py <kernel> --provider IOPCIDevice   what binds to PCI
    python personality.py <kernel> --bundle AppleVirtualPlatform

Usage:
    python personality.py <kernel> [--class RE] [--provider RE] [--bundle RE]
                                   [--name RE] [--full]
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devicetree_req

INTERESTING = ("IOClass", "IOProviderClass", "IONameMatch", "IOMatchCategory",
               "IOProbeScore", "IOPropertyMatch", "IOResourceMatch",
               "IOPCIMatch", "IOPCIPrimaryMatch", "IOPCIClassMatch",
               "AppleVirtIODeviceType", "VirtIODeviceID", "IOUserClass")


def personalities(info: dict):
    """Yield (bundle_id, personality_name, dict) for the whole collection."""
    for kext in info.get("_PrelinkInfoDictionary", []):
        bundle = kext.get("CFBundleIdentifier", "?")
        for pname, p in (kext.get("IOKitPersonalities") or {}).items():
            if isinstance(p, dict):
                yield bundle, pname, p


def show(bundle, pname, p, full):
    print(f"\n  {pname}   [{bundle}]")
    keys = sorted(p) if full else [k for k in INTERESTING if k in p]
    for k in keys:
        v = p[k]
        if isinstance(v, (list, tuple)):
            v = ", ".join(str(x) for x in v)
        elif isinstance(v, dict):
            v = "{" + ", ".join(f"{a}={b!r}" for a, b in list(v.items())[:6]) + "}"
        print(f"      {k:<22} {v}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("--class", dest="cls", help="regex on IOClass")
    ap.add_argument("--provider", help="regex on IOProviderClass")
    ap.add_argument("--bundle", help="regex on CFBundleIdentifier")
    ap.add_argument("--name", help="regex on IONameMatch")
    ap.add_argument("--full", action="store_true", help="every key, not just the "
                                                        "matching-relevant ones")
    args = ap.parse_args(argv)

    info = devicetree_req.prelink_info(args.kernel)
    tests = []
    if args.cls:
        tests.append(lambda p: re.search(args.cls, str(p.get("IOClass", "")), re.I))
    if args.provider:
        tests.append(lambda p: re.search(args.provider,
                                         str(p.get("IOProviderClass", "")), re.I))
    if args.name:
        tests.append(lambda p: re.search(args.name, str(p.get("IONameMatch", "")), re.I))

    n = 0
    for bundle, pname, p in personalities(info):
        if args.bundle and not re.search(args.bundle, bundle, re.I):
            continue
        if tests and not all(t(p) for t in tests):
            continue
        show(bundle, pname, p, args.full)
        n += 1
    print(f"\n  {n} personality(ies)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
