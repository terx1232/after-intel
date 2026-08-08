#!/usr/bin/env python3
"""
devicetree.py -- build and serialise Apple flattened device trees.

Step three of IbootCore. `boot_args.deviceTreeP` points at a flattened device
tree in Apple's own format, which is not FDT/dtb and is much simpler. XNU
defines it in `pexpert/pexpert/device_tree.h`:

    typedef struct DeviceTreeNodeProperty {
        char     name[32];      // NUL-terminated property name
        uint32_t length;        // length in bytes of the value that follows
        // uint8_t value[];     // padded to a 4-byte multiple
    };

    typedef struct OpaqueDTEntry {
        uint32_t nProperties;   // number of properties that follow
        uint32_t nChildren;     // number of child nodes after those
        // DeviceTreeNodeProperty props[nProperties];
        // DeviceTreeNode         children[nChildren];
    };

That is the whole format: a preorder walk, no string table, no header, no
magic. This module emits it and parses it back, and self-tests by round-trip,
which is how the serialiser can be shown correct without a Mac to boot on.

The node names in `minimal_vmapple_tree()` are not invented. They were read out
of the shipped macOS 27 `vma2` kernel collection by `devicetree_req.py`, which
extracts every bundled kext's IOKit matching dictionary from `__PRELINK_INFO`.
The property *values*, by contrast, are placeholders - see the README.

Usage:
    python devicetree.py --selftest
    python devicetree.py --emit vmapple --out devicetree.bin
    python devicetree.py --parse devicetree.bin
"""

from __future__ import annotations

import argparse
import struct
import sys

PROP_NAME_LEN = 32


def _pad4(n: int) -> int:
    return (-n) % 4


class Node:
    """A device tree node: an ordered property map plus ordered children."""

    def __init__(self, name: str | None = None, **props):
        self.props: dict[str, bytes] = {}
        self.children: list[Node] = []
        if name is not None:
            self.set_str("name", name)
        for k, v in props.items():
            self.set(k, v)

    def set(self, key: str, value) -> "Node":
        if isinstance(value, bytes):
            self.props[key] = value
        elif isinstance(value, str):
            self.set_str(key, value)
        elif isinstance(value, int):
            self.set_u32(key, value)
        else:
            raise TypeError(f"unsupported property type {type(value)}")
        return self

    def set_str(self, key: str, value: str) -> "Node":
        self.props[key] = value.encode("utf-8") + b"\x00"
        return self

    def set_u32(self, key: str, value: int) -> "Node":
        self.props[key] = struct.pack("<I", value & 0xFFFFFFFF)
        return self

    def set_u64(self, key: str, value: int) -> "Node":
        self.props[key] = struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF)
        return self

    def set_reg(self, base: int, size: int) -> "Node":
        """The conventional <address, size> pair, 64-bit each."""
        self.props["reg"] = struct.pack("<QQ", base, size)
        return self

    def add(self, child: "Node") -> "Node":
        self.children.append(child)
        return child

    @property
    def name(self) -> str:
        raw = self.props.get("name", b"")
        return raw.split(b"\x00")[0].decode("utf-8", "replace")

    def serialise(self) -> bytes:
        out = bytearray()
        out += struct.pack("<II", len(self.props), len(self.children))
        for key, value in self.props.items():
            nb = key.encode("utf-8")
            if len(nb) >= PROP_NAME_LEN:
                raise ValueError(f"property name too long: {key!r}")
            out += nb.ljust(PROP_NAME_LEN, b"\x00")
            out += struct.pack("<I", len(value))
            out += value
            out += b"\x00" * _pad4(len(value))
        for c in self.children:
            out += c.serialise()
        return bytes(out)

    def __repr__(self) -> str:
        return (f"<Node {self.name!r} props={len(self.props)} "
                f"children={len(self.children)}>")

    def walk(self, depth: int = 0):
        yield depth, self
        for c in self.children:
            yield from c.walk(depth + 1)


def parse(buf: bytes, off: int = 0):
    """Parse one node at buf[off:]. Returns (Node, next_offset)."""
    nprops, nchildren = struct.unpack_from("<II", buf, off)
    off += 8
    node = Node()
    for _ in range(nprops):
        raw_name = buf[off:off + PROP_NAME_LEN]
        off += PROP_NAME_LEN
        (length,) = struct.unpack_from("<I", buf, off)
        off += 4
        value = buf[off:off + length]
        off += length + _pad4(length)
        key = raw_name.split(b"\x00")[0].decode("utf-8", "replace")
        node.props[key] = value
    for _ in range(nchildren):
        child, off = parse(buf, off)
        node.children.append(child)
    return node, off


# --------------------------------------------------------------------------
# A minimal tree for the Apple Virtual Machine platform.
#
# Node names come from `data/vma2-devicetree-req.json`, i.e. from the IOKit
# matching dictionaries inside the shipped vma2 kernel collection. Property
# names marked below come from `data/vma2-avp-strings.json`, extracted from the
# AppleVirtualPlatform driver's own cstring section. Addresses and sizes are
# placeholders: they are what a loader must fill in for a given emulated
# machine, and are NOT claimed to match any real configuration.
# --------------------------------------------------------------------------

# Defaults are QEMU's `virt` machine as it actually reports itself, read out of
# `-machine dumpdtb` with fdt_read.py rather than guessed:
#
#   RAM            0x40000000 (+0x100000000)
#   GICv3 dist     0x08000000 (+0x10000)
#   GICv3 redist   0x080a0000 (+0xf60000)
#   PL011 UART     0x09000000 (+0x1000)
#
# For reference, the real vmapple machine in QEMU upstream places them at
# 0x10000000 / 0x10010000 / 0x20010000 with RAM at 0x70000000. Those are the
# values to use once a vmapple machine is available; this build has none.

def minimal_vmapple_tree(*, ram_base: int = 0x4000_0000,
                         ram_size: int = 4 << 30,
                         gic_dist: int = 0x0800_0000,
                         gic_redist: int = 0x080A_0000,
                         uart_base: int = 0x0900_0000,
                         ncpus: int = 1) -> Node:
    root = Node("device-tree")
    root.set_str("compatible", "AppleVirtualPlatformARM")
    root.set_str("model", "VirtualMac2,1")
    root.set_u32("#address-cells", 2)
    root.set_u32("#size-cells", 2)

    chosen = root.add(Node("chosen"))
    chosen.set_u64("dram-base", ram_base)
    chosen.set_u64("dram-size", ram_size)
    chosen.set_u32("debug-enabled", 1)
    # chip-id / unique-chip-id are read by AppleVirtualPlatform.
    chosen.set_u32("chip-id", 0)
    chosen.set_u64("unique-chip-id", 0)

    memory = root.add(Node("memory"))
    memory.set_str("device_type", "memory")
    memory.set_reg(ram_base, ram_size)

    cpus = root.add(Node("cpus"))
    cpus.set_u32("#address-cells", 1)
    cpus.set_u32("#size-cells", 0)
    for i in range(ncpus):
        c = cpus.add(Node(f"cpu{i}"))
        c.set_str("compatible", "cpu")
        c.set_str("device_type", "cpu")
        c.set_u32("reg", i)
        c.set_u32("cpu-id", i)
        c.set_u32("state", 0 if i == 0 else 1)

    arm_io = root.add(Node("arm-io"))
    arm_io.set_str("compatible", "arm-io,vmapple1")
    arm_io.set_u32("#address-cells", 2)
    arm_io.set_u32("#size-cells", 2)
    arm_io.props["ranges"] = struct.pack("<QQQ", 0, 0, 1 << 32)

    gic = arm_io.add(Node("interrupt-controller"))
    gic.set_str("compatible", "ARM,gicv3")
    gic.set_u32("#interrupt-cells", 3)
    gic.set_u32("interrupt-controller", 1)
    gic.props["reg"] = struct.pack("<QQQQ", gic_dist, 0x10000,
                                   gic_redist, 0xF60000)

    psci = arm_io.add(Node("psci"))
    psci.set_str("compatible", "ARM,psci")
    psci.set_str("method", "hvc")

    uart = arm_io.add(Node("uart0"))
    uart.set_str("compatible", "ARM,pl011")
    uart.set_str("device_type", "serial")
    uart.set_reg(uart_base, 0x1000)

    rtc = arm_io.add(Node("rtc"))
    rtc.set_str("compatible", "ARM,pl031")

    return root


def selftest() -> int:
    """Emit, parse back, and compare. Proves the serialiser round-trips."""
    print("building minimal vmapple tree ...")
    tree = minimal_vmapple_tree()
    blob = tree.serialise()
    print(f"  serialised: {len(blob)} bytes")

    parsed, consumed = parse(blob)
    print(f"  parsed back: consumed {consumed} of {len(blob)} bytes")

    ok = True
    if consumed != len(blob):
        print("  FAIL: trailing bytes after parse")
        ok = False

    orig = list(tree.walk())
    back = list(parsed.walk())
    if len(orig) != len(back):
        print(f"  FAIL: node count {len(orig)} != {len(back)}")
        ok = False
    else:
        for (d1, a), (d2, b) in zip(orig, back):
            if d1 != d2 or a.props != b.props:
                print(f"  FAIL: mismatch at {a.name!r}")
                ok = False
                break

    if parsed.serialise() != blob:
        print("  FAIL: re-serialisation differs")
        ok = False

    nprops, nchildren = struct.unpack_from("<II", blob, 0)
    if nprops != len(tree.props) or nchildren != len(tree.children):
        print("  FAIL: root header wrong")
        ok = False

    print(f"  nodes: {len(orig)}, "
          f"properties: {sum(len(n.props) for _, n in orig)}")
    print("\n  " + ("PASS: round-trip is byte-identical" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--emit", choices=["vmapple"])
    ap.add_argument("--out")
    ap.add_argument("--parse")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if args.emit:
        tree = minimal_vmapple_tree()
        blob = tree.serialise()
        for depth, n in tree.walk():
            props = ", ".join(sorted(n.props))
            print(f"{'  ' * depth}{n.name or '(unnamed)':<24} [{props}]")
        print(f"\nserialised: {len(blob)} bytes")
        if args.out:
            open(args.out, "wb").write(blob)
            print(f"wrote {args.out}")
        return 0

    if args.parse:
        blob = open(args.parse, "rb").read()
        tree, consumed = parse(blob)
        for depth, n in tree.walk():
            print(f"{'  ' * depth}{n.name or '(unnamed)':<24} "
                  f"{len(n.props)} props, {len(n.children)} children")
        print(f"\nconsumed {consumed} of {len(blob)} bytes")
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
