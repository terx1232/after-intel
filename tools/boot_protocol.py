#!/usr/bin/env python3
"""
boot_protocol.py -- extract and compare XNU's boot_args handoff protocol
across architectures.

"Write a new bootloader" is the usual first suggestion for getting macOS onto
non-Apple hardware. This tool answers the prior question: what does a bootloader
actually have to hand the kernel, and how much of that is architecture-specific?

The answer is fully public. Apple ships the boot protocol in the XNU source as
`pexpert/pexpert/<arch>/boot.h`, and it is a plain C struct. This parses those
headers and reports the field inventory and computed size per architecture.

Usage:
    python boot_protocol.py <path-to-xnu-source> [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

ARCH_HEADERS = {
    "i386/x86_64": "pexpert/pexpert/i386/boot.h",
    "arm64": "pexpert/pexpert/arm64/boot.h",
    "arm": "pexpert/pexpert/arm/boot.h",
}

# Sizes for the scalar types that appear in these headers. `unsigned long` is
# 8 bytes in the LP64 model XNU builds under.
TYPE_SIZES = {
    "uint8_t": 1, "int8_t": 1, "char": 1, "unsigned char": 1,
    "uint16_t": 2, "int16_t": 2,
    "uint32_t": 4, "int32_t": 4, "int": 4, "unsigned int": 4,
    "uint64_t": 8, "int64_t": 8, "unsigned long": 8, "long": 8,
    "void *": 8,
}

FIELD = re.compile(
    r"^\s*(?P<type>(?:unsigned\s+|struct\s+)?[A-Za-z_][\w]*)\s*"
    r"(?P<ptr>\*?)\s*(?P<name>[A-Za-z_]\w*)\s*"
    r"(?P<array>\[[^\]]*\])?\s*;"
)

# Fields whose presence means the kernel expects a UEFI firmware handoff.
EFI_MARKERS = ("efi", "MemoryMap", "pciConfigSpace")
# Fields tied to the sealed system volume / boot security chain.
SECURITY_MARKERS = ("arv", "ARV", "apfsData", "csr", "keyStore", "KC_hdrs")


def struct_body(text: str, name: str) -> str | None:
    """Extract the body of `typedef struct <name> { ... }` or `struct <name> {...}`."""
    for pat in (rf"typedef\s+struct\s+{name}\s*\{{", rf"struct\s+{name}\s*\{{"):
        m = re.search(pat, text)
        if not m:
            continue
        i = m.end() - 1
        depth = 0
        for j in range(i, len(text)):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    return text[i + 1:j]
    return None


def parse_fields(body: str, consts: dict) -> list:
    fields = []
    for line in body.splitlines():
        line = line.split("/*")[0].split("//")[0]
        m = FIELD.match(line)
        if not m:
            continue
        ftype = " ".join(m.group("type").split())
        if ftype in ("struct", "typedef", "return", "extern"):
            continue
        name = m.group("name")
        ptr = bool(m.group("ptr"))
        count = 1
        arr = m.group("array")
        if arr:
            expr = arr[1:-1].strip()
            if expr.isdigit():
                count = int(expr)
            elif expr in consts:
                count = consts[expr]
            elif expr == "":
                count = 0  # flexible array member
            else:
                count = None  # unresolved
        base = 8 if ptr else TYPE_SIZES.get(ftype)
        size = None if base is None or count is None else base * count
        fields.append({
            "name": name, "type": ftype + ("*" if ptr else ""),
            "count": count, "bytes": size,
        })
    return fields


def classify(name: str) -> str:
    if any(k in name for k in EFI_MARKERS):
        return "efi"
    if any(k in name for k in SECURITY_MARKERS):
        return "boot-security"
    return "core"


def audit(root: str) -> dict:
    out = {"root": os.path.abspath(root), "arches": {}}
    for arch, rel in ARCH_HEADERS.items():
        path = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(path):
            out["arches"][arch] = {"present": False}
            continue
        text = open(path, "r", encoding="utf-8", errors="replace").read()

        consts = {m.group(1): int(m.group(2))
                  for m in re.finditer(r"#define\s+(\w+)\s+(\d+)", text)}

        body = struct_body(text, "boot_args")
        fields = parse_fields(body, consts) if body else []

        # Nested struct sizes we can resolve locally (Boot_Video etc).
        local = {}
        for sname in re.findall(r"struct\s+(\w+)\s*\{", text):
            sbody = struct_body(text, sname)
            if sbody:
                sf = parse_fields(sbody, consts)
                if all(f["bytes"] is not None for f in sf):
                    local[sname] = sum(f["bytes"] for f in sf)
        for f in fields:
            if f["bytes"] is None and f["type"] in local:
                f["bytes"] = local[f["type"]] * (f["count"] or 1)

        buckets = {"core": 0, "efi": 0, "boot-security": 0}
        for f in fields:
            f["role"] = classify(f["name"])
            buckets[f["role"]] += 1

        asserted = None
        am = re.search(r"sizeof\(boot_args\)\s*==\s*(\d+)", text)
        if am:
            asserted = int(am.group(1))

        known = [f["bytes"] for f in fields if f["bytes"] is not None]
        out["arches"][arch] = {
            "present": True,
            "header": rel,
            "header_bytes": len(text),
            "field_count": len(fields),
            "fields_by_role": buckets,
            "computed_bytes": sum(known),
            "unresolved_fields": len(fields) - len(known),
            "asserted_size": asserted,
            "nested_structs": local,
            "fields": fields,
        }
    return out


def report(a: dict, out=sys.stdout) -> None:
    print(f"\n=== XNU boot_args handoff protocol: {a['root']} ===\n", file=out)
    hdr = f"{'arch':<14}{'hdr B':>8}{'fields':>8}{'core':>7}{'efi':>6}{'sec':>6}{'bytes':>9}{'asserted':>10}"
    print(hdr, file=out)
    print("-" * len(hdr), file=out)
    for arch, d in a["arches"].items():
        if not d.get("present"):
            print(f"{arch:<14}  (header not present)", file=out)
            continue
        b = d["fields_by_role"]
        print(f"{arch:<14}{d['header_bytes']:>8}{d['field_count']:>8}{b['core']:>7}"
              f"{b['efi']:>6}{b['boot-security']:>6}{d['computed_bytes']:>9}"
              f"{str(d['asserted_size'] or '-'):>10}", file=out)

    for arch, d in a["arches"].items():
        if not d.get("present") or not d["fields_by_role"]["efi"]:
            continue
        print(f"\nEFI-dependent fields in {arch} boot_args:", file=out)
        for f in d["fields"]:
            if f["role"] == "efi":
                print(f"    {f['name']:<38}{f['type']}", file=out)

    for arch, d in a["arches"].items():
        if not d.get("present") or not d["fields_by_role"]["boot-security"]:
            continue
        print(f"\nBoot-security fields in {arch} boot_args:", file=out)
        for f in d["fields"]:
            if f["role"] == "boot-security":
                print(f"    {f['name']:<38}{f['type']}", file=out)

    print("\nA bootloader must produce every field above. The EFI column is the", file=out)
    print("reason the x86 loader is a UEFI application and the ARM one is not.", file=out)


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
