#!/usr/bin/env python3
"""
symbols.py -- resolve kernel collection symbols by name or address.

Every address in this project has so far been found the hard way: a string, a
reference to it, a scan backwards for the function prologue. That was necessary
because the collection has no LC_SYMTAB of its own - but it does have 216
LC_FILESET_ENTRY commands, one per kext plus the kernel, and each of those is a
nested Mach-O that carries its own symbol table.

So the names were there all along, one indirection away. This reads them.

    python symbols.py <kernel> --name thread_block
    python symbols.py <kernel> --addr 0xfffffe0009ecce8c
    python symbols.py <kernel> --grep apfs_vfsop
    python symbols.py <kernel> --list-images
"""

from __future__ import annotations

import argparse
import bisect
import struct
import sys

LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x02
LC_FILESET_ENTRY = 0x80000035

N_TYPE = 0x0E
N_SECT = 0x0E


def cstr(data: bytes, off: int) -> str:
    end = data.find(b"\x00", off)
    return data[off:end].decode("utf-8", "replace")


def images(data: bytes):
    """(name, vmaddr, fileoff) for each nested Mach-O in the collection."""
    ncmds, = struct.unpack_from("<I", data, 16)
    off = 32
    out = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmd == LC_FILESET_ENTRY:
            vmaddr, fileoff = struct.unpack_from("<QQ", data, off + 8)
            name_off, = struct.unpack_from("<I", data, off + 24)
            out.append((cstr(data, off + name_off), vmaddr, fileoff))
        off += cmdsize
    return out


def symtab_of(data: bytes, header_off: int):
    """(symoff, nsyms, stroff) of a Mach-O at header_off, or None."""
    ncmds, = struct.unpack_from("<I", data, header_off + 16)
    off = header_off + 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmd == LC_SYMTAB:
            symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", data, off + 8)
            return symoff, nsyms, stroff
        off += cmdsize
    return None


def collect(path: str):
    """name -> address, and a sorted (address, name) list."""
    data = open(path, "rb").read()
    by_name = {}
    pairs = []
    for name, vmaddr, fileoff in images(data):
        st = symtab_of(data, fileoff)
        if not st:
            continue
        symoff, nsyms, stroff = st
        for i in range(nsyms):
            e = symoff + i * 16
            if e + 16 > len(data):
                break
            strx, ntype, nsect, ndesc = struct.unpack_from("<IBBH", data, e)
            value, = struct.unpack_from("<Q", data, e + 8)
            if not value or (ntype & N_TYPE) != N_SECT:
                continue
            sym = cstr(data, stroff + strx)
            if not sym:
                continue
            by_name.setdefault(sym.lstrip("_"), value)
            pairs.append((value, sym.lstrip("_")))
    pairs.sort()
    return data, by_name, pairs


def nearest(pairs, addr: int):
    i = bisect.bisect_right(pairs, (addr, "\xff")) - 1
    if i < 0:
        return None
    value, name = pairs[i]
    return name, value, addr - value


def short(va: int) -> str:
    KV = 0xFFFFFE0000000000
    return f"0x{va - KV:x}" if va >= KV else f"{va:#x}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("--name", action="append", default=[])
    ap.add_argument("--addr", action="append", default=[])
    ap.add_argument("--grep")
    ap.add_argument("--list-images", action="store_true")
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args(argv)

    data, by_name, pairs = collect(args.kernel)
    print(f"\n  {len(pairs):,} symbols from "
          f"{len(images(data))} images\n")

    if args.list_images:
        for name, vmaddr, fileoff in images(data)[:args.limit]:
            print(f"    {short(vmaddr):>12}  {name}")
        return 0

    for n in args.name:
        key = n.lstrip("_")
        if key in by_name:
            print(f"    {key} = {by_name[key]:#x}  ({short(by_name[key])})")
        else:
            print(f"    {key}: not found")

    for a in args.addr:
        addr = int(a, 0)
        hit = nearest(pairs, addr)
        if hit:
            name, value, delta = hit
            print(f"    {short(addr)} = {name} + {delta:#x}  "
                  f"(starts {short(value)})")
        else:
            print(f"    {short(addr)}: below the first symbol")

    if args.grep:
        hits = [(v, n) for v, n in pairs if args.grep in n]
        print(f"    {len(hits)} symbol(s) matching {args.grep!r}")
        for v, n in hits[:args.limit]:
            print(f"      {short(v):>12}  {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
