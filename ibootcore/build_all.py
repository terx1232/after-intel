#!/usr/bin/env python3
"""
build_all.py -- run the whole IbootCore chain end to end, from a shipped
InstallAssistant package to a flat memory image.

Steps:
  1. read the package table of contents (xar)
  2. locate SharedSupport.dmg inside it and carve the zip members
  3. extract the requested kernelcache
  4. unwrap the Image4 container and decompress the LZFSE payload
  5. derive the load map and the device tree requirements
  6. build the device tree and boot_args
  7. assemble the flat memory image

Everything is written to an output directory of your choosing. Nothing is
placed in the repository: the artefacts contain Apple's kernel and are not
redistributable.

Usage:
    python build_all.py <InstallAssistant.pkg> --out DIR [--kernel vma2]
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(HERE), "tools")
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)

import xar_explore
import zip_carve
import im4p_extract
import loadmap
import devicetree
import bootargs


def step(n: int, text: str) -> None:
    print(f"\n[{n}] {text}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pkg")
    ap.add_argument("--out", required=True)
    ap.add_argument("--kernel", default="vma2",
                    help="which kernelcache to build for (default: vma2)")
    ap.add_argument("--phys-base", default="0x800000000")
    ap.add_argument("--mem-size", default="4G")
    ap.add_argument("--fb", default="1024x768")
    ap.add_argument("--cmdline", default="-v debug=0x8 serial=3")
    ap.add_argument("--libpath", help="sys.path entry providing liblzfse")
    args = ap.parse_args(argv)

    if args.libpath:
        sys.path.insert(0, args.libpath)

    os.makedirs(args.out, exist_ok=True)
    out = lambda *p: os.path.join(args.out, *p)

    # ---- 1. package table of contents -----------------------------------
    step(1, "reading package table of contents")
    with open(args.pkg, "rb") as fh:
        hdr = xar_explore.read_header(fh)
        toc = xar_explore.read_toc(fh, hdr)
        members = xar_explore.walk_files(
            toc.find("toc") if toc.find("toc") is not None else toc)
    ss = next((m for m in members if m["path"] == "SharedSupport.dmg"), None)
    if ss is None:
        print("    no SharedSupport.dmg in this package", file=sys.stderr)
        return 2
    dmg_off = hdr["heap_offset"] + ss["offset"]
    print(f"    SharedSupport.dmg at +{dmg_off}, {ss['length'] / 2**30:.2f} GiB")

    # ---- 2. carve zip members -------------------------------------------
    step(2, "carving zip members from the image (this takes a few minutes)")
    cache = out("members.json")
    if os.path.exists(cache):
        zmembers = json.load(open(cache, encoding="utf-8"))["members"]
        print(f"    reusing cached listing: {len(zmembers)} members")
    else:
        zmembers = zip_carve.scan(args.pkg, dmg_off, ss["length"], progress=True)
        json.dump({"members": zmembers}, open(cache, "w", encoding="utf-8"))
        print(f"    {len(zmembers)} members, cached to {cache}")

    # ---- 3. extract the kernelcache -------------------------------------
    step(3, f"extracting kernelcache.release.{args.kernel}")
    want = f"kernelcache.release.{args.kernel}"
    km = next((m for m in zmembers if m["name"].endswith(want)), None)
    if km is None:
        avail = sorted(m["name"].rsplit("/", 1)[-1] for m in zmembers
                       if "kernelcache" in m["name"])
        print(f"    {want} not found. available: {', '.join(avail)}",
              file=sys.stderr)
        return 2
    with open(args.pkg, "rb") as fh:
        fh.seek(km["data_offset"])
        raw = fh.read(km["compressed_size"] or (1 << 26))
    blob = (zlib.decompressobj(-zlib.MAX_WBITS).decompress(raw)
            if km["method_id"] == 8 else raw[:km["uncompressed_size"]])
    im4p_path = out(want)
    open(im4p_path, "wb").write(blob)
    print(f"    {len(blob):,} bytes -> {im4p_path}")

    # ---- 4. unwrap Image4 and decompress --------------------------------
    step(4, "unwrapping Image4 and decompressing LZFSE")
    info = im4p_extract.parse_im4p(blob)
    kern, note = im4p_extract.decompress(info["payload"])
    if not kern:
        print(f"    {note}", file=sys.stderr)
        print("    install pyliblzfse, or pass --libpath", file=sys.stderr)
        return 2
    kern_path = out(f"{args.kernel}.kernel")
    open(kern_path, "wb").write(kern)
    print(f"    {len(info['payload']):,} -> {len(kern):,} bytes "
          f"({len(kern) / len(info['payload']):.2f}x) -> {kern_path}")

    # ---- 5. load map and device tree requirements ------------------------
    step(5, "deriving load map and device tree requirements")
    m = loadmap.parse(kern_path)
    json.dump(m, open(out("loadmap.json"), "w", encoding="utf-8"), indent=2)
    print(f"    entry {m['entry']:#018x}, virtBase {m['vm_low']:#018x}, "
          f"{len(m['fileset_entries'])} kexts")
    try:
        import devicetree_req
        req = devicetree_req.collect(devicetree_req.prelink_info(kern_path))
        json.dump(req, open(out("devicetree-req.json"), "w", encoding="utf-8"),
                  indent=2)
        print(f"    {len(req['name_match'])} node names, "
              f"{req['personality_count']} personalities -> devicetree-req.json")
    except Exception as e:
        print(f"    device tree requirements unavailable: {e}")

    # ---- 6 & 7. device tree, boot_args, image ----------------------------
    step(6, "building device tree, boot_args and the memory image")
    image_path = out(f"{args.kernel}-image.bin")
    rc = subprocess.call([sys.executable, os.path.join(HERE, "build_image.py"),
                          kern_path, "--out", image_path,
                          "--phys-base", args.phys_base,
                          "--mem-size", args.mem_size,
                          "--fb", args.fb,
                          "--cmdline", args.cmdline])
    if rc != 0:
        return rc

    # also drop the pieces separately, they are useful on their own
    tree = devicetree.minimal_vmapple_tree(
        ram_base=int(args.phys_base, 0),
        ram_size=bootargs.human_size(args.mem_size))
    open(out("devicetree.bin"), "wb").write(tree.serialise())

    print(f"\n=== build complete: {os.path.abspath(args.out)} ===")
    for f in sorted(os.listdir(args.out)):
        p = out(f)
        print(f"  {os.path.getsize(p):>13,}  {f}")

    print("\nNothing here is redistributable: the kernel and the image contain")
    print("Apple code. Keep them local.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
