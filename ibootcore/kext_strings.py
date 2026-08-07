#!/usr/bin/env python3
"""
kext_strings.py -- recover the device tree properties a driver actually reads,
from the driver's own code.

Step five of IbootCore. `devicetree_req.py` recovers node *names* from IOKit
matching dictionaries, which is enough to build a structurally valid tree but
not a semantically useful one: each node also has to carry the properties its
driver looks up, and those are not in any plist.

They are, however, in the driver. IOKit property lookups take a C string name,
so every property a kext reads appears as a literal in its `__TEXT,__cstring`
section. Extracting those gives a candidate list far better than guesswork.

A kernel collection makes this straightforward. Each `LC_FILESET_ENTRY` gives a
kext's file offset inside the collection, and the collection maps one to one
(`vmaddr = virtBase + fileoff`), so each kext's own Mach-O can be read in place.

Usage:
    python kext_strings.py <kernel> --kext AppleVirtualPlatform
    python kext_strings.py <kernel> --kext AppleARMGIC --json out.json
    python kext_strings.py <kernel> --list
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
from collections import Counter

LC_SEGMENT_64 = 0x19
LC_FILESET_ENTRY = 0x80000035

# Device tree property names are lowercase, may contain hyphens, digits,
# commas and underscores, and are short. This is deliberately loose; the
# filtering happens by cross-referencing, not by the regex.
PROP_RE = re.compile(rb"^[a-z][a-z0-9_,\-\.#]{2,30}$")

# Strings that look like properties but are something else.
NOISE_PREFIXES = (b"com.apple", b"http", b"/usr", b"/system", b"/var")


def read_header(b: bytes, off: int):
    magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags = \
        struct.unpack_from("<IiiIIII", b, off)
    return magic, filetype, ncmds


def segments_at(b: bytes, base: int):
    """Yield (segname, sectname, fileoff, size) for every section."""
    _magic, _ft, ncmds = read_header(b, base)
    off = base + 32
    for _ in range(ncmds):
        if off + 8 > len(b):
            return
        cmd, cmdsize = struct.unpack_from("<II", b, off)
        if cmdsize == 0:
            return
        if cmd == LC_SEGMENT_64:
            segname = b[off + 8:off + 24].split(b"\x00")[0].decode("ascii", "replace")
            nsects = struct.unpack_from("<I", b, off + 64)[0]
            soff = off + 72
            for _s in range(nsects):
                sectname = b[soff:soff + 16].split(b"\x00")[0].decode("ascii", "replace")
                addr, size = struct.unpack_from("<QQ", b, soff + 32)
                (fileoff,) = struct.unpack_from("<I", b, soff + 48)
                yield segname, sectname, fileoff, size, addr
                soff += 80
        off += cmdsize


def fileset_entries(b: bytes):
    _magic, _ft, ncmds = read_header(b, 0)
    off = 32
    out = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", b, off)
        if cmdsize == 0:
            break
        if cmd == LC_FILESET_ENTRY:
            vmaddr, fileoff, idoff = struct.unpack_from("<QQI", b, off + 8)
            name = b[off + idoff:off + cmdsize].split(b"\x00")[0]
            out.append({"id": name.decode("utf-8", "replace"),
                        "vmaddr": vmaddr, "fileoff": fileoff})
        off += cmdsize
    return out


def cstrings(b: bytes, base: int) -> list:
    """Every NUL-terminated string in this kext's cstring sections."""
    out = []
    for segname, sectname, fileoff, size, _addr in segments_at(b, base):
        if sectname not in ("__cstring", "__const", "__oslstring"):
            continue
        if not (0 < size < (1 << 26)) or fileoff + size > len(b):
            continue
        blob = b[fileoff:fileoff + size]
        for s in blob.split(b"\x00"):
            if 3 <= len(s) <= 40:
                out.append(s)
    return out


def looks_like_property(s: bytes) -> bool:
    if any(s.startswith(p) for p in NOISE_PREFIXES):
        return False
    return bool(PROP_RE.match(s))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("--kext", help="substring of the bundle id to inspect")
    ap.add_argument("--list", action="store_true", help="list fileset entries")
    ap.add_argument("--json")
    ap.add_argument("--limit", type=int, default=70)
    args = ap.parse_args(argv)

    b = open(args.kernel, "rb").read()
    entries = fileset_entries(b)

    if args.list or not args.kext:
        print(f"\n{len(entries)} fileset entries in "
              f"{os.path.basename(args.kernel)}\n")
        for e in entries[:args.limit]:
            print(f"  {e['fileoff']:>10}  {e['id']}")
        if len(entries) > args.limit:
            print(f"  ... and {len(entries) - args.limit} more")
        return 0

    sel = [e for e in entries if args.kext.lower() in e["id"].lower()]
    if not sel:
        print(f"no fileset entry matching {args.kext!r}", file=sys.stderr)
        return 1

    result = {}
    for e in sel:
        strings = cstrings(b, e["fileoff"])
        props = sorted({s.decode("ascii", "replace")
                        for s in strings if looks_like_property(s)})
        result[e["id"]] = props
        print(f"\n=== {e['id']} ===")
        print(f"  kext at file offset {e['fileoff']:,}, "
              f"vmaddr {e['vmaddr']:#x}")
        print(f"  {len(strings)} strings, {len(props)} look like "
              f"device tree property or node names\n")
        for p in props[:args.limit]:
            print(f"    {p}")
        if len(props) > args.limit:
            print(f"    ... and {len(props) - args.limit} more")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
        print(f"\nwrote {args.json}", file=sys.stderr)

    print("\nThese are candidates, not a specification. A string in a driver's")
    print("cstring section may be a property it reads, a property it sets, a")
    print("node name, or unrelated. Cross-reference before trusting one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
