#!/usr/bin/env python3
"""
metal_surface.py -- measure the size of the Metal API surface.

Discussions of reimplementing Metal are conducted entirely in adjectives
("huge", "impossible"). Nobody appears to have published a number. This tool
produces one.

It parses Apple's own metal-cpp headers (https://github.com/apple/metal-cpp),
which map every Metal Objective-C class, protocol, constant and enum directly
into the MTL namespace. That makes them a faithful, machine-readable census of
the public API -- and unlike the Objective-C headers, they are a self-contained
repository you can clone on any OS.

What is counted:
  * classes        -- a defined C++ class, i.e. one real API object type
  * methods        -- member function declarations inside those classes
  * enums/options  -- _MTL_ENUM and _MTL_OPTIONS blocks and their members
  * constants      -- _MTL_CONST declarations

What this does NOT measure: semantics. A method is one line to declare and
anywhere from one to several thousand lines to implement correctly. The count
is a lower bound on the work and an exact measure of the surface.

Usage:
    python metal_surface.py <path-to-metal-cpp> [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

# `class Device : public NS::Referencing<Device>` -- a real definition.
# Bare `class Device;` forward declarations are deliberately excluded.
# Leading whitespace is allowed: MetalFX declares its classes indented inside a
# `namespace MTLFX` block, and anchoring at column 0 silently missed all of them.
CLASS_DEF = re.compile(r"^\s*class\s+(\w+)\s*:\s*public\s+(.+?)\s*$")

# A member function declaration: optional return type, a name, an argument
# list, terminated by `;`. Excludes macro lines and inline definitions.
METHOD = re.compile(r"^\s{4,}[\w:<>*&\s]+?(\w+)\s*\([^;{]*\)\s*(?:const\s*)?;\s*$")

# metal-cpp splits some protocols into a `FooBase` helper plus the real `Foo`.
# The Base classes are an artefact of the C++ binding, not Metal API objects.
BINDING_ARTEFACT = re.compile(r"Base$")

ENUM_OPEN = re.compile(r"^_MTL_(ENUM|OPTIONS)\s*\(\s*([\w:]+)\s*,\s*(\w+)\s*\)")
CONST_DECL = re.compile(r"^_MTL_CONST\s*\(")


def parse_header(path: str) -> dict:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()

    classes: dict[str, int] = {}
    enums: dict[str, int] = {}
    consts = 0

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        m = CLASS_DEF.match(line)
        if m:
            name = m.group(1)
            # Body: find the opening brace, then brace-match to the close.
            j = i + 1
            while j < n and "{" not in lines[j]:
                if lines[j].strip() and not lines[j].strip().startswith("//"):
                    break  # not actually a class body
                j += 1
            if j >= n or "{" not in lines[j]:
                i += 1
                continue
            depth = 0
            methods = 0
            k = j
            while k < n:
                depth += lines[k].count("{") - lines[k].count("}")
                if k > j or depth > 0:
                    if depth == 1 and METHOD.match(lines[k]):
                        methods += 1
                if depth <= 0 and k > j:
                    break
                k += 1
            # A class may be split across headers; take the largest body seen.
            classes[name] = max(classes.get(name, 0), methods)
            i = k + 1
            continue

        m = ENUM_OPEN.match(line)
        if m:
            ename = m.group(3)
            j = i
            depth = 0
            members = 0
            while j < n:
                depth += lines[j].count("{") - lines[j].count("}")
                if depth == 1 and "=" in lines[j] and not lines[j].lstrip().startswith("_MTL"):
                    members += 1
                if depth <= 0 and j > i:
                    break
                j += 1
            enums[ename] = max(enums.get(ename, 0), members)
            i = j + 1
            continue

        if CONST_DECL.match(line):
            consts += 1

        i += 1

    return {"classes": classes, "enums": enums, "consts": consts}


def audit(root: str) -> dict:
    frameworks: dict[str, dict] = {}
    for entry in sorted(os.listdir(root)):
        fw_dir = os.path.join(root, entry)
        if not os.path.isdir(fw_dir) or entry.startswith("."):
            continue
        headers = sorted(
            os.path.join(dp, f)
            for dp, _dn, fns in os.walk(fw_dir)
            for f in fns
            if f.endswith(".hpp")
        )
        if not headers:
            continue
        classes: dict[str, int] = {}
        enums: dict[str, int] = {}
        consts = 0
        artefacts = 0
        for h in headers:
            r = parse_header(h)
            for cn, mc in r["classes"].items():
                if BINDING_ARTEFACT.search(cn):
                    artefacts += 1
                    continue
                classes[cn] = max(classes.get(cn, 0), mc)
            for en, ec in r["enums"].items():
                enums[en] = max(enums.get(en, 0), ec)
            consts += r["consts"]
        frameworks[entry] = {
            "headers": len(headers),
            "binding_artefacts_excluded": artefacts,
            "classes": len(classes),
            "methods": sum(classes.values()),
            "enums": len(enums),
            "enum_members": sum(enums.values()),
            "constants": consts,
            "largest_classes": Counter(classes).most_common(15),
            "categories": categorise(classes),
            "all_classes": dict(Counter(classes).most_common()),
        }
    return {"root": os.path.abspath(root), "frameworks": frameworks}


# Not all API surface is equal work. A `*Descriptor` is a bag of properties --
# its methods are getters and setters over a struct, which is mechanical. An
# encoder or a device method is where the actual driver behaviour lives.
# Splitting the count this way is the difference between a scary number and a
# useful one.
CATEGORIES = [
    ("descriptors", lambda n: n.endswith("Descriptor")),
    ("encoders", lambda n: n.endswith("Encoder")),
    ("state_objects", lambda n: n.endswith("State")),
    ("device_and_queue", lambda n: n in ("Device", "CommandQueue", "CommandBuffer")),
]


def categorise(classes: dict[str, int]) -> dict:
    out = {}
    claimed: set[str] = set()
    for label, pred in CATEGORIES:
        sel = {n: m for n, m in classes.items() if pred(n) and n not in claimed}
        claimed |= set(sel)
        out[label] = {"classes": len(sel), "methods": sum(sel.values())}
    rest = {n: m for n, m in classes.items() if n not in claimed}
    out["other"] = {"classes": len(rest), "methods": sum(rest.values())}
    return out


def report(a: dict, out=sys.stdout) -> None:
    print(f"\n=== Metal API surface: {a['root']} ===\n", file=out)
    hdr = f"{'framework':<14}{'hdrs':>6}{'classes':>9}{'methods':>9}{'enums':>7}{'enum val':>10}{'consts':>8}"
    print(hdr, file=out)
    print("-" * len(hdr), file=out)
    tot = Counter()
    for fw, d in a["frameworks"].items():
        print(f"{fw:<14}{d['headers']:>6}{d['classes']:>9}{d['methods']:>9}"
              f"{d['enums']:>7}{d['enum_members']:>10}{d['constants']:>8}", file=out)
        for k in ("headers", "classes", "methods", "enums", "enum_members", "constants"):
            tot[k] += d[k]
    print("-" * len(hdr), file=out)
    print(f"{'TOTAL':<14}{tot['headers']:>6}{tot['classes']:>9}{tot['methods']:>9}"
          f"{tot['enums']:>7}{tot['enum_members']:>10}{tot['constants']:>8}", file=out)

    metal = a["frameworks"].get("Metal")
    if metal:
        print("\nMetal surface by kind of work:", file=out)
        total_m = metal["methods"] or 1
        for label, d in metal["categories"].items():
            pct = 100.0 * d["methods"] / total_m
            print(f"    {label:<18}{d['classes']:>4} classes{d['methods']:>6} methods"
                  f"  ({pct:4.1f}%)", file=out)

        print("\nlargest classes in Metal (by method count):", file=out)
        for name, mc in metal["largest_classes"]:
            print(f"    {name:<38}{mc:>5} methods", file=out)

    print("\nNOTE: this measures surface, not semantics. A declared method is a", file=out)
    print("      lower bound on the work -- implementing one correctly ranges", file=out)
    print("      from trivial to thousands of lines.", file=out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="path to a metal-cpp checkout")
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
