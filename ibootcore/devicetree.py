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
import os
import struct
import sys

PROP_NAME_LEN = 32

# GICv3 gives every core two 64 KiB redistributor frames, GICR_CTRL and
# GICR_SGI, laid out contiguously from the redistributor base.
GICR_STRIDE = 0x20000

# How many bytes of entropy the kernel demands in /chosen/random-seed. The
# kernel states the figure itself when it disagrees.
RANDOM_SEED_BYTES = 256


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
                         ncpus: int = 1,
                         timebase_hz: int = 62_500_000,
                         cpu_hz: int = 2_400_000_000,
                         bus_hz: int = 100_000_000,
                         soc_base: int = 0x0800_0000,
                         soc_size: int = 0x3800_0000,
                         random_seed: bytes | None = None) -> Node:
    root = Node("device-tree")
    root.set_str("compatible", "AppleVirtualPlatformARM")
    root.set_str("model", "VirtualMac2,1")
    root.set_u32("#address-cells", 2)
    root.set_u32("#size-cells", 2)

    chosen = root.add(Node("chosen"))
    chosen.set_u64("dram-base", ram_base)
    chosen.set_u64("dram-size", ram_size)
    # Leave debugging off. Setting this to 1 made the kernel enable debug
    # exceptions and then panic out of machine_routines_common.c with
    # "debug exceptions enabled in kernel mode" -- a complaint about state we
    # had asked for ourselves.
    chosen.set_u32("debug-enabled", 0)
    # pexpert/gen/pe_gen.c reads /chosen/random-seed and panics with
    # "no random seed" if the property is absent or empty. It copies the bytes
    # out, counts the nulls, and zeroes the tree copy behind itself; an
    # all-zero seed is not a panic but yields a zero-length seed, so the bytes
    # have to be real. Entropy is taken at build time here. A loader shipping a
    # constant in this field would be handing every boot the same kernel RNG
    # seed, which is a real weakness, not a placeholder like the addresses
    # elsewhere in this tree.
    # 256 bytes, not 64: the kernel checks the length and says so plainly --
    # "Expected 256 seed bytes from bootloader, but got 64."
    chosen.props["random-seed"] = random_seed or os.urandom(RANDOM_SEED_BYTES)
    # chip-id / unique-chip-id are read by AppleVirtualPlatform.
    chosen.set_u32("chip-id", 0)
    chosen.set_u64("unique-chip-id", 0)

    # arm_vm_init.c does
    #
    #     err = SecureDTLookupEntry(NULL, "chosen/memory-map", &memory_map);
    #     assert(err == kSuccess);
    #     err = SecureDTGetProperty(memory_map, "TrustCache", &trustCacheRange, ...);
    #     if (err == kSuccess) { ... phystokv(trustCacheRange->paddr) ... }
    #
    # and that assert is compiled out of a release kernel. With no such node the
    # lookup fails, memory_map keeps whatever was on the stack, and the property
    # read walks it -- which is how this port ended up calling phystokv(0) and
    # panicking with "illegal PA: 0x0".
    #
    # The node exists so the lookup succeeds and the property lookups then fail
    # honestly. It is deliberately empty: there is no trust cache and no AuxKC
    # here, and claiming either would be worse than admitting neither. The
    # AuxKC path is guarded against a zero paddr; the TrustCache path is not.
    # Real firmware does not leave this node empty. It fills it with
    # DTMemoryMapRange entries -- {uint64 paddr; uint64 length;} -- naming the
    # regions it placed, and the kernel reads them back to find the device tree
    # and boot args in physical memory. An empty node satisfies the lookup that
    # arm_vm_init does, which is why adding it stopped the TrustCache panic,
    # but it supplies none of the ranges that the code after that lookup goes
    # on to read.
    #
    # The values are filled in by the loader once it knows where it placed
    # things; sixteen zero bytes reserve the space so that adding them cannot
    # change the serialised size between passes.
    memmap = chosen.add(Node("memory-map"))
    memmap.props["DeviceTree"] = b"\x00" * 16
    memmap.props["BootArgs"] = b"\x00" * 16

    # pe_serial.c:831 does
    #
    #     if (SecureDTFindNodeWithStringProperty("name", "defaults",
    #                                            &defaults_node) != kSuccess) {
    #         panic("Unable to find the 'defaults' devicetree node.");
    #     }
    #
    # and that is an unconditional panic, not a fallback. The node has to exist
    # for the kernel to reach serial init at all.
    #
    # It then looks for a "serial-device" phandle inside it. Leaving that out is
    # deliberate: absent, the kernel treats no serial device as specified and
    # picks its own, which is what we want while the tree describes PL011 rather
    # than an Apple UART.
    root.add(Node("defaults"))

    memory = root.add(Node("memory"))
    memory.set_str("device_type", "memory")
    memory.set_reg(ram_base, ram_size)

    # pexpert/arm/pe_identify_machine.c walks "/cpus", skips any node whose
    # "state" property does not compare equal to the string "running", and
    # reads the clock rates from the ones that remain. Two things about that
    # loop are unforgiving, and this tree got both wrong at first:
    #
    #   * "state" is compared with strncmp against "running". Writing it as a
    #     u32 makes every CPU fail the test, so no node is ever examined.
    #   * Nothing after the loop supplies a fallback. timebase_frequency_hz
    #     stays whatever the defaults left, and wfe_timeout_configure then does
    #         bit_index = flsll(ticks_per_event) - 1
    #     which on a zero frequency yields 0xFFFFFFFF, decrements once more,
    #     and panics in _enable_timebase_event_stream with
    #     "invalid bit index (4294967294)" -- before serial init, so nothing is
    #     printed and the kernel spins forever. That was this port's stage-4
    #     hang, and it was our own device tree causing it.
    #
    # pe_identify_machine also divides by dec_clock_rate_hz, which is a copy of
    # the timebase frequency, so a zero there is a divide by zero as well.
    #
    # 62500000 is QEMU's generic timer rate: GTIMER_SCALE is 16 ns, so
    # 1e9 / 16 = 62.5 MHz. It has to agree with CNTFRQ_EL0 or the kernel's
    # sense of time is wrong.
    cpus = root.add(Node("cpus"))
    cpus.set_u32("#address-cells", 1)
    cpus.set_u32("#size-cells", 0)
    for i in range(ncpus):
        c = cpus.add(Node(f"cpu{i}"))
        c.set_str("compatible", "cpu")
        c.set_str("device_type", "cpu")
        c.set_u32("reg", i)
        c.set_u32("cpu-id", i)
        c.set_str("state", "running" if i == 0 else "waiting")
        c.set_u32("timebase-frequency", timebase_hz)
        c.set_u32("clock-frequency", cpu_hz)
        c.set_u32("bus-frequency", bus_hz)
        c.set_u32("memory-frequency", bus_hz)
        c.set_u32("peripheral-frequency", timebase_hz)
        c.set_u32("fixed-frequency", timebase_hz)
        # `find_gicr_pe_base` walks /cpus looking for each core's redistributor,
        # and `reg-private` is Apple's name for a CPU's private register region.
        # Read out of the kernel's own string table (0xfffffe0007137142) rather
        # than guessed - the previous guess put invented properties on the gic
        # node and the kernel ignored them.
        #
        # GICv3 gives each core two 64 KiB frames, GICR_CTRL and GICR_SGI, laid
        # out contiguously from the redistributor base.
        c.props["reg-private"] = struct.pack("<QQ",
                                             gic_redist + i * GICR_STRIDE,
                                             GICR_STRIDE)

    # This node gates the whole platform expert. pe_arm_get_soc_base_phys()
    # does, without checking either result:
    #
    #     SecureDTFindEntry("name", "arm-io", &entryP)
    #     SecureDTGetProperty(entryP, "device_type", &tmpStr, &prop_size)
    #     strlcpy(gPESoCDeviceTypeBuffer, tmpStr, ...)
    #     SecureDTGetProperty(entryP, "ranges", &ranges_prop, &prop_size)
    #     gPESoCBasePhys = *(ranges_prop + 1)
    #
    # and pe_identify_machine returns immediately if that comes back zero --
    # before it assigns any of its defaults, so gPEClockFrequencyInfo stays
    # zeroed BSS. Everything downstream that needs a clock then reads zero.
    #
    # Two consequences for this tree:
    #
    #   * "ranges" is <child, parent, size> in 64-bit cells and the SoC base is
    #     the *second* cell. The first version here was <0, 0, 4 GiB>, so the
    #     base read back as zero and the kernel panicked in
    #     _enable_timebase_event_stream long before serial init.
    #   * "device_type" must exist. Its lookup is unchecked, so a missing
    #     property leaves tmpStr holding uninitialised stack and strlcpy
    #     copies from wherever that points.
    #
    # Child nodes below keep absolute addresses in "reg" rather than offsets
    # from this base. On Apple hardware the offset convention matters because
    # pe_serial.c computes soc_base_phys + block_offset for the Apple UART and
    # for dockchannel; this tree declares neither of those, so nothing here
    # consumes the offset form.
    arm_io = root.add(Node("arm-io"))
    arm_io.set_str("compatible", "arm-io,vmapple1")
    arm_io.set_str("device_type", "arm-io")
    arm_io.set_u32("#address-cells", 2)
    arm_io.set_u32("#size-cells", 2)
    arm_io.props["ranges"] = struct.pack("<QQQ", 0, soc_base, soc_size)

    # The node must be named `gic`, not `interrupt-controller`. The kernel looks
    # it up by path and says so in its own error string, which sits immediately
    # before the message in the binary:
    #
    #     0xfffffe00070dae04  '/arm-io/gic'
    #     0xfffffe00070dae10  '%s: cannot find GIC node in DT @%s:%d'
    #
    # Read out of the shipped kernel rather than guessed, which matters here:
    # finding #31 records that AppleARMGIC yields zero property names from its
    # cstring sections, so this node cannot be reconstructed from the driver.
    gic = arm_io.add(Node("gic"))
    gic.set_str("compatible", "ARM,gicv3")
    gic.set_u32("#interrupt-cells", 3)
    gic.set_u32("interrupt-controller", 1)
    # `reg` here is **relative to arm-io's ranges base**, not absolute.
    # `pe_arm_map_interrupt_controller` maps `soc_phys + offset`, and its own
    # log string says so: "pe_arm_map_interrupt_controller: soc_phys: 0x%l...".
    # With absolute addresses the kernel mapped 0x08000000 + 0x080a0000, and
    # reading the result returned 0xffffffffffffffff - QEMU's answer for an
    # unassigned address - while the register at physical 0x080a0000 held a
    # perfectly good GICR_TYPER of 0x0000000001000011 with Aff0 of 0. The scan
    # then matched Aff0 0xff against MPIDR's 0 and panicked with "cannot find
    # GICR base for core %u".
    #
    # This is the correction to the note on arm-io above, which claimed nothing
    # consumed the offset form. The GIC does.
    gic.props["reg"] = struct.pack("<QQQQ",
                                   gic_dist - soc_base, 0x10000,
                                   gic_redist - soc_base, 0xF60000)
    # The kernel checks this exactly: "incorrect reg property size in GIC DT
    # node; expecting 32 bytes but got %u bytes". Four 64-bit values, which is
    # what the two pairs above give.
    #
    # The per-core redistributor base does NOT live here. `find_gicr_pe_base`
    # panics with "cannot find GICR base for core %u", and the strings that
    # follow it in the binary are `/cpus`, `state`, `running` - so it walks the
    # cpu nodes. An earlier attempt invented `gicr-base`, `gicr-stride` and
    # friends on this node; they changed nothing, because the kernel never looks
    # for them. See the cpu nodes for where it actually looks.

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


def check_timebase(tree: Node) -> bool:
    """Run XNU's own event-stream arithmetic over this tree.

    Reproduces pe_identify_machine's node filter and wfe_timeout_configure's
    bit_index computation, so a tree that would panic the kernel fails here
    instead of hanging silently in an emulator. The panic this guards against
    prints nothing, because it happens before serial init.
    """
    print("\n  checking the tree against XNU's timebase arithmetic ...")

    # pe_identify_machine bails before touching gPEClockFrequencyInfo unless
    # pe_arm_get_soc_base_phys() is non-zero, so check that first: without it
    # none of the clock arithmetic below is ever reached at runtime.
    arm_io = next((n for _, n in tree.walk() if n.name == "arm-io"), None)
    if arm_io is None:
        print('    FAIL: no "arm-io" node; pe_arm_get_soc_base_phys returns 0')
        return False
    if "device_type" not in arm_io.props:
        print('    FAIL: arm-io has no "device_type"; its lookup is unchecked '
              "and strlcpy would copy from an uninitialised pointer")
        return False
    ranges = arm_io.props.get("ranges", b"")
    if len(ranges) < 24:
        print("    FAIL: arm-io ranges must be three 64-bit cells")
        return False
    soc_base = struct.unpack_from("<Q", ranges, 8)[0]   # *(ranges_prop + 1)
    if soc_base == 0:
        print("    FAIL: arm-io ranges gives SoC base 0, so "
              "pe_identify_machine returns early and every clock stays zero")
        return False
    print(f"    SoC base from arm-io ranges: {soc_base:#x}")

    chosen = next((n for _, n in tree.walk() if n.name == "chosen"), None)
    seed = chosen.props.get("random-seed", b"") if chosen else b""
    if len(seed) != RANDOM_SEED_BYTES:
        print(f"    FAIL: random-seed is {len(seed)} bytes, kernel wants "
              f"{RANDOM_SEED_BYTES}")
        return False
    if not any(seed):
        print("    FAIL: random-seed is all zeros, which counts as no seed")
        return False
    print(f"    random-seed: {len(seed)} bytes")

    cpus = next((n for _, n in tree.walk() if n.name == "cpus"), None)
    if cpus is None:
        print("    FAIL: no /cpus node")
        return False

    running = [c for c in cpus.children
               if c.props.get("state", b"").split(b"\x00")[0] == b"running"]
    if not running:
        print('    FAIL: no cpu has state == "running"; pe_identify_machine '
              "skips every node and the clock rates stay at their defaults")
        return False
    print(f"    cpus with state \"running\": {len(running)}")

    cpu = running[0]
    raw = cpu.props.get("timebase-frequency")
    if raw is None:
        print("    FAIL: the running cpu has no timebase-frequency")
        return False
    ticks_per_sec = int.from_bytes(raw, "little")
    if ticks_per_sec == 0:
        print("    FAIL: timebase-frequency is zero; XNU divides by it")
        return False

    events_per_sec = 1_000_000                     # USEC_PER_SEC
    ticks_per_event = ticks_per_sec // events_per_sec
    if ticks_per_event == 0:
        print(f"    FAIL: {ticks_per_sec} Hz gives 0 ticks per event")
        return False

    bit_index = ticks_per_event.bit_length() - 1   # flsll(x) - 1
    if ticks_per_event & ((1 << bit_index) - 1):
        bit_index += 1
    if bit_index != 0:
        bit_index -= 1

    print(f"    timebase {ticks_per_sec:,} Hz -> {ticks_per_event} ticks per "
          f"event -> EVENTI bit index {bit_index}")
    if bit_index >= 64:
        print(f"    FAIL: _enable_timebase_event_stream would panic with "
              f"invalid bit index ({bit_index})")
        return False
    print("    PASS: within range, no early panic")
    return True


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

    if not check_timebase(tree):
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

