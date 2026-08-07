#!/usr/bin/env python3
"""
im4p_extract.py -- unwrap an Apple Image4 payload (IM4P) and identify what is
inside it.

Apple ships kernelcaches as IM4P containers: a small ASN.1 DER structure
carrying a four-character type tag, a description string, and an octet string
holding the payload. The payload is normally LZFSE-compressed.

This parses the DER directly (no asn1 library needed), decompresses the payload
when possible, and reports the Mach-O header of whatever comes out -- which is
how you establish a kernel's architecture from the shipped bits rather than
from its filename.

LZFSE decompression needs `pyliblzfse`, which is optional: without it the tool
still reports the container structure and the payload's compression format.

Usage:
    python im4p_extract.py <file.im4p> [--out <path>] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys

CPU = {7: "i386", 0x01000007: "x86_64", 12: "arm", 0x0100000C: "arm64", 18: "ppc"}
FILETYPES = {2: "executable", 6: "dylib", 0xB: "kext", 0xC: "fileset"}

# Mach-O load commands worth reporting for a kernel collection.
LC_SEGMENT_64 = 0x19
LC_FILESET_ENTRY = 0x80000035


def der_read(buf: bytes, i: int):
    """Read one DER TLV at buf[i:]. Returns (tag, value_bytes, next_index)."""
    tag = buf[i]
    i += 1
    n = buf[i]
    i += 1
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(buf[i:i + k], "big")
        i += k
    return tag, buf[i:i + n], i + n


def parse_im4p(data: bytes) -> dict:
    """Parse the IM4P SEQUENCE. Returns metadata plus the payload bytes."""
    tag, body, _ = der_read(data, 0)
    if tag != 0x30:
        raise ValueError(f"not a DER SEQUENCE (tag {tag:#x})")

    out = {"strings": [], "payload": None}
    i = 0
    while i < len(body):
        t, v, i = der_read(body, i)
        if t == 0x16:            # IA5String
            out["strings"].append(v.decode("ascii", "replace"))
        elif t == 0x04:          # OCTET STRING -- the payload
            if out["payload"] is None:
                out["payload"] = v
        elif t == 0x02:          # INTEGER (version / size hints)
            out.setdefault("integers", []).append(int.from_bytes(v, "big"))
    if len(out["strings"]) >= 1:
        out["magic"] = out["strings"][0]
    if len(out["strings"]) >= 2:
        out["type"] = out["strings"][1]
    if len(out["strings"]) >= 3:
        out["description"] = out["strings"][2]
    return out


def payload_format(p: bytes) -> str:
    if p[:4] in (b"bvx2", b"bvx1", b"bvxn", b"bvx-"):
        return f"lzfse ({p[:4].decode()})"
    if p[:8] == b"complzss":
        return "complzss"
    if p[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
        return "bare Mach-O"
    if p[:4] == b"\x1f\x8b\x08\x00":
        return "gzip"
    return "unknown"


def decompress(p: bytes):
    """Return (bytes, note). Falls back gracefully if lzfse is unavailable."""
    fmt = payload_format(p)
    if fmt.startswith("bare"):
        return p, "payload was uncompressed"
    if fmt.startswith("lzfse"):
        try:
            import liblzfse
        except ImportError:
            return None, ("payload is LZFSE; install pyliblzfse "
                          "(or add it to sys.path) to decompress")
        return liblzfse.decompress(p), "decompressed with liblzfse"
    return None, f"no decompressor for {fmt}"


def describe_macho(b: bytes) -> dict:
    if len(b) < 32 or b[:4] not in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
        return {"is_macho": False, "first_bytes": b[:16].hex(" ")}
    magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags = \
        struct.unpack_from("<IiiIIII", b, 0)
    arch = CPU.get(cputype, f"unknown({cputype:#x})")
    if cputype == 0x0100000C and (cpusubtype & 0xFFFFFF) == 2:
        arch = "arm64e"
    d = {
        "is_macho": True,
        "arch": arch,
        "cputype": cputype,
        "cpusubtype": cpusubtype,
        "filetype": filetype,
        "filetype_name": FILETYPES.get(filetype, str(filetype)),
        "ncmds": ncmds,
        "sizeofcmds": sizeofcmds,
        "flags": flags,
    }
    # Walk the load commands: count segments and fileset entries.
    off = 32
    segs, entries, names = 0, 0, []
    for _ in range(min(ncmds, 4096)):
        if off + 8 > len(b):
            break
        cmd, cmdsize = struct.unpack_from("<II", b, off)
        if cmdsize == 0:
            break
        if cmd == LC_SEGMENT_64:
            segs += 1
        elif cmd == LC_FILESET_ENTRY:
            # struct fileset_entry_command:
            #   cmd(4) cmdsize(4) vmaddr(8) fileoff(8) entry_id(4) reserved(4)
            # entry_id is an lc_str, i.e. a byte offset from the start of the
            # command -- it sits at +24, not at +28 where `reserved` lives.
            entries += 1
            if off + 32 <= len(b):
                (name_off,) = struct.unpack_from("<I", b, off + 24)
                s = b[off + name_off:off + cmdsize].split(b"\x00")[0]
                names.append(s.decode("utf-8", "replace"))
        off += cmdsize
    d["segments"] = segs
    d["fileset_entries"] = entries
    if names:
        d["fileset_entry_names"] = names
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--out", help="write the decompressed payload here")
    ap.add_argument("--json")
    ap.add_argument("--libpath", help="extra sys.path entry for pyliblzfse")
    args = ap.parse_args(argv)

    if args.libpath:
        sys.path.insert(0, args.libpath)

    raw = open(args.path, "rb").read()
    info = parse_im4p(raw)
    p = info["payload"] or b""

    print(f"\n=== {os.path.basename(args.path)} ===")
    print(f"container   : {info.get('magic')}")
    print(f"type tag    : {info.get('type')}")
    print(f"description : {info.get('description')}")
    if info.get("integers"):
        print(f"integers    : {info['integers']}")
    print(f"payload     : {len(p)} bytes, {payload_format(p)}")

    data, note = decompress(p)
    print(f"              {note}")

    result = {
        "file": os.path.abspath(args.path),
        "container": info.get("magic"),
        "type": info.get("type"),
        "description": info.get("description"),
        "payload_bytes": len(p),
        "payload_format": payload_format(p),
        "decompress_note": note,
    }

    if data:
        print(f"decompressed: {len(data)} bytes "
              f"({len(data) / len(p):.2f}x)")
        m = describe_macho(data)
        result["decompressed_bytes"] = len(data)
        result["macho"] = m
        if m["is_macho"]:
            print(f"\nMach-O header:")
            print(f"  architecture     : {m['arch']}")
            print(f"  cputype/subtype  : {m['cputype']:#x} / {m['cpusubtype']:#x}")
            print(f"  file type        : {m['filetype_name']} ({m['filetype']})")
            print(f"  load commands    : {m['ncmds']} ({m['sizeofcmds']} bytes)")
            print(f"  segments         : {m['segments']}")
            print(f"  fileset entries  : {m['fileset_entries']}")
            for n in m.get("fileset_entry_names", [])[:20]:
                print(f"      {n}")
            extra = len(m.get("fileset_entry_names", [])) - 20
            if extra > 0:
                print(f"      ... and {extra} more (full list in --json)")
        else:
            print(f"\n  not a Mach-O; first bytes {m['first_bytes']}")
        if args.out:
            open(args.out, "wb").write(data)
            print(f"\nwrote {args.out}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
        print(f"wrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
