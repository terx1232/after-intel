#!/usr/bin/env python3
"""
bootargs.py -- build the arm64 `boot_args` block XNU expects at entry.

Step four of IbootCore. When a loader jumps to the kernel it passes one thing:
a pointer to this structure in x0. XNU defines it in
`pexpert/pexpert/arm64/boot.h`, and it is short - thirteen fields, no EFI
anything, a flattened device tree pointer and a command line.

Natural alignment applies, so the fields do not sit where a naive sum of sizes
would put them. This module lays them out explicitly and can print the map, so
the offsets can be checked against the header rather than trusted.

Usage:
    python bootargs.py --layout
    python bootargs.py --build --dt devicetree.bin --out bootargs.bin
"""

from __future__ import annotations

import argparse
import struct
import sys

BOOT_LINE_LENGTH = 1024

kBootArgsRevision2 = 2      # added boot_args.bootFlags
kBootArgsVersion2 = 2
kBootFlagsDarkBoot = 1 << 0

# name, offset, struct format, description
LAYOUT = [
    ("Revision",        0,    "<H",   "boot_args structure revision"),
    ("Version",         2,    "<H",   "boot_args structure version"),
    ("virtBase",        8,    "<Q",   "virtual base of memory"),
    ("physBase",        16,   "<Q",   "physical base of memory"),
    ("memSize",         24,   "<Q",   "size of memory"),
    ("topOfKernelData", 32,   "<Q",   "highest physical address used by kernel"),
    ("Video.baseAddr",  40,   "<Q",   "framebuffer base"),
    ("Video.display",   48,   "<Q",   "display code"),
    ("Video.rowBytes",  56,   "<Q",   "bytes per pixel row"),
    ("Video.width",     64,   "<Q",   "width"),
    ("Video.height",    72,   "<Q",   "height"),
    ("Video.depth",     80,   "<Q",   "depth and flags"),
    ("machineType",     88,   "<I",   "machine type"),
    ("deviceTreeP",     96,   "<Q",   "pointer to flattened device tree"),
    ("deviceTreeLength", 104, "<I",   "length of flattened device tree"),
    ("CommandLine",     108,  None,   f"boot command line, {BOOT_LINE_LENGTH} bytes"),
    ("bootFlags",       1136, "<Q",   "loader-specified flags"),
    ("memSizeActual",   1144, "<Q",   "actual size of memory"),
]

SIZEOF_BOOT_ARGS = 1152


def build(*, virt_base: int, phys_base: int, mem_size: int,
          top_of_kernel_data: int, device_tree_p: int, device_tree_length: int,
          cmdline: str = "", machine_type: int = 0, boot_flags: int = 0,
          mem_size_actual: int | None = None,
          video=(0, 0, 0, 0, 0, 0)) -> bytes:
    """Return a fully populated boot_args block."""
    buf = bytearray(SIZEOF_BOOT_ARGS)

    def put(off, fmt, value):
        struct.pack_into(fmt, buf, off, value)

    put(0, "<H", kBootArgsRevision2)
    put(2, "<H", kBootArgsVersion2)
    put(8, "<Q", virt_base)
    put(16, "<Q", phys_base)
    put(24, "<Q", mem_size)
    put(32, "<Q", top_of_kernel_data)
    for i, v in enumerate(video):
        put(40 + i * 8, "<Q", v)
    put(88, "<I", machine_type)
    put(96, "<Q", device_tree_p)
    put(104, "<I", device_tree_length)

    cb = cmdline.encode("utf-8")
    if len(cb) >= BOOT_LINE_LENGTH:
        raise ValueError(f"command line too long: {len(cb)} bytes")
    buf[108:108 + len(cb)] = cb

    put(1136, "<Q", boot_flags)
    put(1144, "<Q", mem_size_actual if mem_size_actual is not None else mem_size)
    return bytes(buf)


def parse(buf: bytes) -> dict:
    out = {}
    for name, off, fmt, _desc in LAYOUT:
        if fmt is None:
            raw = buf[off:off + BOOT_LINE_LENGTH]
            out[name] = raw.split(b"\x00")[0].decode("utf-8", "replace")
        else:
            (out[name],) = struct.unpack_from(fmt, buf, off)
    return out


def show_layout(out=sys.stdout) -> None:
    print("\n=== arm64 boot_args layout ===\n", file=out)
    print(f"{'field':<20}{'offset':>8}{'size':>7}  description", file=out)
    print("-" * 74, file=out)
    for name, off, fmt, desc in LAYOUT:
        size = BOOT_LINE_LENGTH if fmt is None else struct.calcsize(fmt)
        print(f"{name:<20}{off:>8}{size:>7}  {desc}", file=out)
    print("-" * 74, file=out)
    print(f"{'sizeof(boot_args)':<20}{'':>8}{SIZEOF_BOOT_ARGS:>7}", file=out)
    print("\nCompare with the x86 struct, which XNU asserts is exactly 4096",
          file=out)
    print("bytes and which carries twelve EFI-dependent fields. The arm64",
          file=out)
    print("contract is a quarter the size and mentions no firmware at all.",
          file=out)


def human_size(s: str) -> int:
    s = s.strip().upper()
    mult = 1
    if s.endswith("G"):
        mult, s = 1 << 30, s[:-1]
    elif s.endswith("M"):
        mult, s = 1 << 20, s[:-1]
    elif s.endswith("K"):
        mult, s = 1 << 10, s[:-1]
    return int(s, 0) * mult


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layout", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--dt", help="flattened device tree file")
    ap.add_argument("--dt-addr", default="0x900000000")
    ap.add_argument("--virt-base", default="0xfffffe0007004000")
    ap.add_argument("--phys-base", default="0x800000000")
    ap.add_argument("--mem-size", default="4G")
    ap.add_argument("--kernel-size", default="0x4d20000")
    ap.add_argument("--cmdline", default="-v")
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    if args.layout:
        show_layout()
        return 0

    if args.build:
        dt_len = 0
        if args.dt:
            dt_len = len(open(args.dt, "rb").read())
        phys = int(args.phys_base, 0)
        blob = build(
            virt_base=int(args.virt_base, 0),
            phys_base=phys,
            mem_size=human_size(args.mem_size),
            top_of_kernel_data=phys + int(args.kernel_size, 0),
            device_tree_p=int(args.dt_addr, 0),
            device_tree_length=dt_len,
            cmdline=args.cmdline,
        )
        got = parse(blob)
        print("\n=== built boot_args ===\n")
        for k, v in got.items():
            print(f"  {k:<20}"
                  f"{v if isinstance(v, str) else format(v, '#x')}")
        print(f"\n  size: {len(blob)} bytes")
        if args.out:
            open(args.out, "wb").write(blob)
            print(f"  wrote {args.out}")
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
