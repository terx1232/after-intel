#!/usr/bin/env python3
"""
xar_explore.py -- read the table of contents of a xar archive, and optionally
extract members from it.

Apple ships macOS full installers as `InstallAssistant.pkg`, which is a xar
archive. This reads the TOC without unpacking 16 GB of payload, so you can see
the structure first and decide what is worth extracting.

The xar format is documented and simple: a 28-byte big-endian header, a
zlib-compressed XML table of contents, then a heap of member data at offsets
given in the TOC.

No dependencies beyond the standard library. Runs anywhere.

Usage:
    python xar_explore.py <archive.pkg> [--json out.json]
    python xar_explore.py <archive.pkg> --extract <name> --out <dir>
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import zlib
import xml.etree.ElementTree as ET

XAR_MAGIC = b"xar!"


def read_header(fh) -> dict:
    fh.seek(0)
    raw = fh.read(28)
    if raw[:4] != XAR_MAGIC:
        raise ValueError(f"not a xar archive (magic {raw[:4]!r})")
    magic, hsize, version, toc_c, toc_u, cksum = struct.unpack(">4sHHQQI", raw)
    return {
        "header_size": hsize,
        "version": version,
        "toc_compressed": toc_c,
        "toc_uncompressed": toc_u,
        "checksum_alg": cksum,
        "heap_offset": hsize + toc_c,
    }


def read_toc(fh, hdr: dict) -> ET.Element:
    fh.seek(hdr["header_size"])
    blob = fh.read(hdr["toc_compressed"])
    xml = zlib.decompress(blob)
    return ET.fromstring(xml)


def walk_files(node: ET.Element, prefix: str = "") -> list:
    """Flatten the nested <file> tree into a list of member descriptors."""
    out = []
    for f in node.findall("file"):
        name_el = f.find("name")
        name = name_el.text if name_el is not None else "?"
        path = f"{prefix}/{name}" if prefix else name
        ftype = f.findtext("type", default="?")
        entry = {"path": path, "type": ftype}
        data = f.find("data")
        if data is not None:
            enc = data.find("encoding")
            entry.update({
                "offset": int(data.findtext("offset", "0")),
                "length": int(data.findtext("length", "0")),
                "size": int(data.findtext("size", "0")),
                "encoding": enc.get("style") if enc is not None else None,
            })
        out.append(entry)
        out.extend(walk_files(f, path))
    return out


def extract(fh, hdr: dict, entry: dict, dest: str) -> str:
    fh.seek(hdr["heap_offset"] + entry["offset"])
    blob = fh.read(entry["length"])
    enc = (entry.get("encoding") or "")
    if "gzip" in enc or "zlib" in enc:
        blob = zlib.decompress(blob)
    elif "bzip2" in enc:
        import bz2
        blob = bz2.decompress(blob)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "wb") as out:
        out.write(blob)
    return dest


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return str(n)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archive")
    ap.add_argument("--json", metavar="FILE")
    ap.add_argument("--extract", metavar="PATH",
                    help="extract the member whose path matches this exactly")
    ap.add_argument("--out", metavar="DIR", default=".")
    args = ap.parse_args(argv)

    with open(args.archive, "rb") as fh:
        hdr = read_header(fh)
        toc = read_toc(fh, hdr)
        files = walk_files(toc.find("toc") if toc.find("toc") is not None else toc)

        print(f"\n=== {os.path.basename(args.archive)} ===")
        print(f"xar version {hdr['version']}, TOC {hdr['toc_compressed']} -> "
              f"{hdr['toc_uncompressed']} bytes, heap at {hdr['heap_offset']}\n")
        print(f"{'member':<48}{'type':<10}{'stored':>12}{'unpacked':>12}  encoding")
        print("-" * 100)
        for e in files:
            if "length" not in e:
                print(f"{e['path']:<48}{e['type']:<10}")
                continue
            enc = (e.get("encoding") or "").replace("application/", "")
            print(f"{e['path']:<48}{e['type']:<10}{human(e['length']):>12}"
                  f"{human(e['size']):>12}  {enc}")

        if args.extract:
            match = [e for e in files if e["path"] == args.extract and "length" in e]
            if not match:
                print(f"\nno member named {args.extract!r}", file=sys.stderr)
                return 1
            dest = os.path.join(args.out, os.path.basename(args.extract))
            print(f"\nextracting {args.extract} -> {dest} ...")
            extract(fh, hdr, match[0], dest)
            print(f"wrote {human(os.path.getsize(dest))}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh2:
            json.dump({"archive": os.path.abspath(args.archive),
                       "header": hdr, "members": files}, fh2, indent=2)
        print(f"\nwrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
