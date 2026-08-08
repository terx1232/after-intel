#!/usr/bin/env python3
"""
fdt_read.py -- read a flattened device tree in the standard dtb format.

Not Apple's format - this is the one everybody else uses, and QEMU emits it for
its own machines with `-machine dumpdtb=`. That makes it the shortest route to
the real MMIO addresses of a QEMU machine: rather than guessing where the GIC
and the UART live, ask the machine and read the answer.

The addresses recovered this way go straight into the Apple-format tree that
`devicetree.py` builds, replacing placeholders with values the hardware
actually responds at.

Format: a header with magic 0xd00dfeed, then a token stream of BEGIN_NODE,
PROP, END_NODE, END, with property names indexed into a string block.

Usage:
    python fdt_read.py virt.dtb
    python fdt_read.py virt.dtb --grep 'intc|pl011|uart|memory'
"""

from __future__ import annotations

import argparse
import re
import struct
import sys

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9


def parse(blob: bytes) -> list:
    (magic, totalsize, off_struct, off_strings, off_rsvmap, version,
     last_comp, boot_cpu, size_strings, size_struct) = struct.unpack_from(
        ">10I", blob, 0)
    if magic != FDT_MAGIC:
        raise ValueError(f"not a dtb (magic {magic:#x})")

    strings = blob[off_strings:off_strings + size_strings]
    pos = off_struct
    depth = 0
    nodes = []
    path = []

    while pos < off_struct + size_struct:
        (tok,) = struct.unpack_from(">I", blob, pos)
        pos += 4
        if tok == FDT_BEGIN_NODE:
            end = blob.index(b"\x00", pos)
            name = blob[pos:end].decode("utf-8", "replace")
            pos = (end + 4) & ~3
            path.append(name)
            nodes.append({"path": "/".join(path), "depth": depth, "props": {}})
            depth += 1
        elif tok == FDT_END_NODE:
            depth -= 1
            path.pop()
        elif tok == FDT_PROP:
            plen, noff = struct.unpack_from(">II", blob, pos)
            pos += 8
            nend = strings.index(b"\x00", noff)
            pname = strings[noff:nend].decode("ascii", "replace")
            pval = blob[pos:pos + plen]
            pos = (pos + plen + 3) & ~3
            if nodes:
                nodes[-1]["props"][pname] = pval
        elif tok == FDT_NOP:
            continue
        elif tok == FDT_END:
            break
        else:
            raise ValueError(f"bad token {tok:#x} at {pos - 4:#x}")
    return nodes


def show_prop(name: str, val: bytes) -> str:
    if name in ("compatible", "device_type", "model", "status", "stdout-path",
                "bootargs", "method", "clock-names"):
        return " ".join(s.decode("ascii", "replace")
                        for s in val.split(b"\x00") if s)
    if name == "reg" and len(val) % 8 == 0 and len(val) >= 16:
        cells = struct.unpack(f">{len(val) // 4}I", val)
        pairs = []
        for i in range(0, len(cells) - 3, 4):
            addr = (cells[i] << 32) | cells[i + 1]
            size = (cells[i + 2] << 32) | cells[i + 3]
            pairs.append(f"{addr:#x} (+{size:#x})")
        return ", ".join(pairs)
    if len(val) == 4:
        return f"{struct.unpack('>I', val)[0]:#x}"
    if len(val) <= 32:
        return val.hex(" ")
    return f"<{len(val)} bytes>"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dtb")
    ap.add_argument("--grep", default="")
    ap.add_argument("--props", default="reg|compatible|device_type|interrupts")
    args = ap.parse_args(argv)

    nodes = parse(open(args.dtb, "rb").read())
    rx = re.compile(args.grep, re.I) if args.grep else None
    prx = re.compile(args.props, re.I)

    print(f"\n=== {args.dtb}: {len(nodes)} nodes ===\n")
    for n in nodes:
        if rx and not rx.search(n["path"]):
            continue
        print(f"{'  ' * n['depth']}{n['path'].split('/')[-1] or '/'}")
        for k, v in n["props"].items():
            if prx.search(k):
                print(f"{'  ' * n['depth']}    {k:<14}{show_prop(k, v)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
