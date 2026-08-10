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

# Any non-zero value works; it only has to match between /defaults/serial-device
# and the UART node's AAPL,phandle, which is how the kernel connects the two.
UART_PHANDLE = 1

# IONVRAM refuses a zero-sized store. 8 KiB is the smallest size Apple's own
# platforms use and is plenty for a store nothing has written to yet.
# Read from Apple's own manifest for this platform, apticket.vma2macosap.im4m,
# by im4m_props.py. Values are Apple's, not invented.
DEFAULT_MANIFEST_PROPS = {
    "BORD": 32,
    "CEPO": 1,
    "CHIP": 65024,
    "CPRO": True,
    "CSEC": True,
    "EKEY": True,
    "EPRO": True,
    "ESEC": True,
    "SDOM": 1,
    "augs": 1,
    "vugs": 1,
    "apmv": "27.0",
    "love": "26.1.388.5.7,0",
    "prtp": "VirtualMac2,1",
    "sdkp": "macosx",
    "tagt": "VMA2MACOSAP",
    "tatp": "vma2macos",
    "tstp": 1784268391,
}

NVRAM_BYTES = 0x2000

# Phandles. Any distinct non-zero values work; they only have to agree between
# the referring property and the referenced node's AAPL,phandle.
TRUSTCACHE_KEY = "TrustCache"

GIC_PHANDLE = 2
PCIE_PHANDLE = 3

# PCIe host bridge geometry, read out of QEMU's own generated device tree with
#     qemu-system-aarch64 -M virt,gic-version=3,highmem-ecam=off,dumpdtb=x.dtb
# and decoded by fdt_read.py. Measured, not looked up.
PCIE_ECAM_BASE = 0x3F00_0000
PCIE_ECAM_SIZE = 0x0100_0000          # 16 buses at 1 MiB each
PCIE_INTX_SPI_BASE = 3                # INTA..INTD are SPI 3, 4, 5, 6

# (flags, pci address, cpu address, size). The flag byte's low two bits are the
# space: 1 = I/O, 2 = 32-bit memory, 3 = 64-bit memory. The 64-bit aperture at
# 0x8000000000 is deliberately left out: it does not fit inside arm-io's window,
# and virtio devices are happy with 32-bit BARs.
PCIE_RANGES = (
    (0x0100_0000, 0x0000_0000, 0x3EFF_0000, 0x0001_0000),
    (0x0200_0000, 0x1000_0000, 0x1000_0000, 0x2EFF_0000),
)

# Apple's manifest for this platform, shipped in the installer and committed to
# data/. Loaded lazily so the tree can still be built without it.
def _default_manifest_blob():
    import os
    for p in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                           "data", "apticket.vma2macosap.im4m"),
              r"D:\macos\ibootcore-build\apticket.vma2macosap.im4m"):
        if os.path.exists(p):
            return open(p, "rb").read()
    return None


def _default_nvram(size: int) -> bytes:
    """A valid, empty CHRP store. Built by nvram_image.py, which reads the
    layout and checksum out of IONVRAMCHRPHandler.cpp."""
    import nvram_image
    return nvram_image.build(size)


def _pad4(n: int) -> int:
    return (-n) % 4


class Node:
    """A device tree node: an ordered property map plus ordered children."""

    def __init__(self, name: str | None = None, **props):
        self.props: dict[str, bytes] = {}
        self.children: list[Node] = []
        # Property names whose length field had the top bit set, i.e. values
        # Apple's iBoot fills in. Kept so a parsed tree can say which of its own
        # numbers are real and which are waiting to be written.
        self.placeholders: set[str] = set()
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
        # The top bit of the length is a flag, not length. Apple's own trees set
        # it on properties iBoot is expected to overwrite before handing the
        # tree to the kernel -- addresses, sizes, seeds and the like. Reading it
        # as part of the length turns a 4-byte property into a 2 GiB one, which
        # is exactly how Apple's DeviceTree.vma2macosap failed to parse here.
        placeholder = bool(length & 0x80000000)
        length &= 0x7FFFFFFF
        value = buf[off:off + length]
        off += length + _pad4(length)
        key = raw_name.split(b"\x00")[0].decode("utf-8", "replace")
        node.props[key] = value
        if placeholder:
            node.placeholders.add(key)
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
                         random_seed: bytes | None = None,
                         nvram_data: bytes | None = None,
                         manifest_props: dict | None = None,
                         manifest_blob: bytes | None = None,
                         gic_msi_frame: int = 0x0802_0000,
                         want_trustcache: bool = False,) -> Node:
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
    # The routine that demanded `/product` walks a fixed list, and its panics
    # name each entry: "failed to get chosen node", "...options node",
    # "...defaults node", "...product node", "...manifest properties". The paths
    # sit in the string table right beside those messages: /chosen, /defaults,
    # /product, /chosen/manifest-properties, /chosen/asmb.
    #
    # Added empty. What belongs inside them is sealed-system-volume material -
    # the ARV root hash and manifest a real loader supplies, per finding #15 -
    # and inventing values there would be worse than leaving them out. The nodes
    # exist so the lookups succeed; their contents are a separate problem.
    # The manifest properties are Image4 secure-boot fields. Leaving the node
    # empty produced "panic: non-sensical crypto hash method: " with the value
    # missing after the colon, which named the property directly.
    #
    # The names and the accepted values are read out of the kernel's own string
    # table around 0xfffffe0007234f1a: `crypto-hash-method` takes `sha1` or
    # `sha2-384`, and the neighbouring strings are the rest of the set. Note
    # `uses-avp-root-ca` - AVP is Apple Virtual Platform, so this path is meant
    # for exactly the machine we are pretending to be.
    #
    # These describe a development configuration: production status off, security
    # mode off, mix-and-match allowed. That is deliberate and it is a real
    # loosening of secure boot, not a placeholder - a loader shipping these
    # values would be declaring an unlocked machine.
    # The property names are four-character codes, not the long display labels
    # that sit near the panic string. Two attempts to synthesise this node from
    # those labels failed, because they are what the kernel *prints*, not what
    # it looks up.
    #
    # The real values come from Apple's own manifest for this exact platform,
    # shipped inside the installer at
    #   AssetData/boot/Firmware/Manifests/restore/
    #   macOS Customer Software Update/apticket.vma2macosap.im4m
    # and read by im4m_props.py. `prtp` there is "VirtualMac2,1", matching the
    # model this tree already claims, which is how the file was confirmed to be
    # the right one.
    #
    # Note CPRO and CSEC are **true**. The earlier synthesis set them to zero,
    # declaring an unlocked development machine; Apple's manifest says the
    # opposite, so that loosening was not only unnecessary, it was wrong.
    # The raw blob was tried here too - as /chosen/manifest-properties, as
    # /chosen/manifest, and as `manifest` and `IM4M` inside the node - and
    # changed nothing. It is not passed any more; it only added 20 KiB three
    # times over. See the crypto-hash-method note below for what the panic
    # actually wanted, which was none of this.
    manifest = chosen.add(Node("manifest-properties"))
    for key, value in (manifest_props or DEFAULT_MANIFEST_PROPS).items():
        if isinstance(value, bool):
            manifest.set_u32(key, 1 if value else 0)
        elif isinstance(value, int):
            manifest.set_u32(key, value)
        elif isinstance(value, str):
            manifest.set_str(key, value)
        else:
            manifest.props[key] = value

    chosen.add(Node("asmb"))
    # IONVRAM panics with "NVRAM size is 0 bytes, possibly due to bad config
    # with iBoot + xnu mismatch" when this is empty, so the buffer has to be
    # real rather than the node merely present. Zeros are a valid empty store:
    # the handler formats it on first use.
    # A buffer of zeros is not enough: the CHRP handler validates a header and
    # fails with "IONVRAMCHRPHandler creation failed @IONVRAM.cpp:1691". The
    # image below carries a real Apple header, a checksum computed the way
    # `chrp_checksum` computes it, an Adler-32 over the body, and two empty
    # partitions. See nvram_image.py, which reads the layout out of
    # IONVRAMCHRPHandler.cpp rather than guessing it.
    root.add(Node("options"))

    # The NVRAM store hangs off **/chosen**, not /options. IONVRAM.cpp does
    #
    #     entry = IORegistryEntry::fromPath("/chosen", gIODTPlane);
    #     prop  = entry->copyProperty(bankSizeKey);
    #     prop  = entry->copyProperty(proxyDataKey);
    #
    # and putting them on /options produced "IONVRAMCHRPHandler creation failed"
    # with a perfectly valid image, because the handler was being handed
    # nothing at all. The image was never the problem.
    chosen.props["nvram-proxy-data"] = nvram_data or _default_nvram(NVRAM_BYTES)
    chosen.set_u32("nvram-total-size", NVRAM_BYTES)
    chosen.set_u32("nvram-bank-size", NVRAM_BYTES)
    chosen.set_u32("nvram-bank-count", 1)
    chosen.set_u32("nvram-current-bank", 0)

    # Secure boot policy. `crypto-hash-method` is the property behind
    #
    #     panic: non-sensical crypto hash method:
    #
    # and it took three wrong attempts to find, all of them spent on the Image4
    # manifest because the panic appeared right after manifest properties were
    # added. It has nothing to do with the manifest. The proof is in the kernel's
    # own string table, where the name occurs exactly twice, and the second copy
    # sits in AppleMobileApNonce::start's literal pool immediately after the node
    # it reads from:
    #
    #     fffffe000732f934  /chosen
    #     fffffe000732f93c  crypto-hash-method
    #     fffffe000732f94f  sha2-384
    #     fffffe000732f958  sha1
    #     fffffe000732f95d  allow-ap-nonce-retrieval
    #
    # A plain string property on /chosen, and the only two accepted values are
    # right there next to it. The consumer memcmps 4 bytes against "sha1" or 8
    # against "sha2-384" and panics on anything else - including, as here, on
    # absent, because the 64-byte output buffer is prefilled with 0xaa and an
    # unfound property leaves it that way.
    #
    # sha2-384 is the modern choice and the first one the code tests for.
    chosen.set_str("crypto-hash-method", "sha2-384")

    # Read by the same routine, immediately after, and by AppleImage4. Each is
    # fetched as a single byte and skipped if absent, so unlike the above these
    # cannot panic - they are set because leaving them out means accepting
    # whatever default a driver picks for hardware this is not.
    #
    # `uses-avp-root-ca` is the interesting one: AVP is Apple Virtual Platform,
    # which is exactly what this tree describes, so the answer is yes.
    chosen.props["uses-avp-root-ca"] = b"\x01"
    chosen.props["allow-ap-nonce-retrieval"] = b"\x01"
    chosen.props["entangle-nonce"] = b"\x00"
    chosen.props["use-ddi-secure-boot"] = b"\x00"
    chosen.props["allow-ecid-mismatch"] = b"\x01"

    memmap = chosen.add(Node("memory-map"))
    # Apple's own tree carries this, and its absence is the difference between
    # a tree the kernel walks and one it does not.
    memmap.set_str("kernel-only", "true")
    memmap.props["DeviceTree"] = b"\x00" * 16
    memmap.props["BootArgs"] = b"\x00" * 16
    # Reserved at full size so filling it in later cannot move anything. XNU
    # reads this entry by name when the command line says rd=md0, and says so
    # when it is absent: "Unable to retrieve range for root memory device".
    memmap.props["RAMDisk"] = b"\x00" * 16
    # AMFI refuses every platform binary on the root volume unless their code
    # directory hashes are in a trust cache the kernel was handed. It looks for
    # one here and names the entry itself:
    #     "unable to find chosen/memory-map in the device tree"
    #     "TrustCache"
    #     "unexpected size for TrustCache property: %u != %zu"
    #     "no external trust caches found (segment length is zero)"
    if want_trustcache:
        memmap.props[TRUSTCACHE_KEY] = b"\x00" * 16

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
    # It then looks for a "serial-device" phandle inside it, and that is not
    # optional either. `serial_init` does
    #
    #     if (!get_serial_device_phandle(&phandle)) {
    #         // XNU has not been configured to use a serial device
    #         return 0;
    #     }
    #
    # so an empty `defaults` node means the kernel selects no serial device at
    # all and returns before any driver runs. This node was first added empty on
    # the reasoning that the kernel would then "pick its own"; it does not, it
    # gives up. That is why the port stayed silent through this whole bring-up.
    #
    # The phandle names the UART node, which must carry a matching
    # `AAPL,phandle`. `SecureDTFindNodeWithPhandle` looks it up by that value.
    defaults = root.add(Node("defaults"))
    defaults.set_u32("serial-device", UART_PHANDLE)
    # The rest of Apple's /defaults for this platform, read out of
    # DeviceTree.vma2macosap. vmm-present is the one that matters most: it tells
    # the kernel it is a guest, which changes what it expects of the hardware.
    defaults.set_u32("vmm-present", 1)
    defaults.set_u32("pmap-max-asids", 0x4000)
    defaults.set_u32("kern.vm_compressor", 4)
    defaults.set_u32("has-xart", 1)
    defaults.set_u32("force-sep-nonce", 1)
    defaults.set_u32("sleep-disabled", 1)
    defaults.set_u32("avp-encryption-version", 0)
    defaults.props["no-effaceable-storage"] = b""
    defaults.props["ean-storage-present"] = b""

    # "panic: failed to get product node" - read out of the guest at the point
    # of failure, not guessed. `pe_init.c:478` reads `unique-model` and
    # `sub-product-type` out of this node, and somewhere on the path taken here
    # its absence is fatal rather than skipped.
    product = root.add(Node("product"))
    product.set_str("product-name", "VirtualMac2,1")
    product.set_str("unique-model", "VirtualMac2,1")
    product.set_str("sub-product-type", "VirtualMac2,1")
    product.set_str("product-description", "Apple Virtual Machine")
    product.set_str("product-id", "VirtualMac2,1")

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

        # The interrupts live here, on the CPU, not on the controller - which is
        # the answer to "Failed to register GIC to PassthruInterruptController."
        # AppleARMGIC finishes by registering a handler through
        # IOService::registerInterrupt, and that resolves through the
        # IOInterruptControllers property IODTMapInterrupts derives from a node's
        # `interrupts` and `interrupt-parent`. Putting them on the gic node makes
        # IODeviceTreeSupport dereference a null parent; Apple puts them here.
        #
        # Three specifiers of (number, flags), matching #interrupt-cells = 2 on
        # the controller. The values are Apple's own, read out of cpu0 in
        # DeviceTree.vma2macosap: 1, 0x17 and 1 - the maintenance, PMU and
        # timer PPIs this core answers.
        c.set_u32("interrupt-parent", GIC_PHANDLE)
        c.props["interrupts"] = struct.pack("<6I", 1, 1, 0x17, 1, 1, 1)
        c.props["function-enable_core"] = b""
        c.set_u32("cpu-version", 0)

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
    arm_io.set_str("device_type", "vmapple2-io")
    # Apple's own value for this platform, alongside the SoC generation string
    # its drivers look for. "arm-io" was a reasonable guess and is what the
    # kernel copies into gPESoCDeviceTypeBuffer; this is what it should read.
    arm_io.set_str("soc-generation", "VMApple2")
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
    # Apple's own tree for this platform, DeviceTree.vma2macosap.im4p, carries
    # two entries here, and the first is the one its personality would prefer.
    # A property holds a NUL-separated list, which is why this is one blob.
    gic.props["compatible"] = b"gic,vmapple1\x00ARM,gicv3\x00"
    # Two, not three. Apple's tree says #interrupt-cells = 2 and
    # #address-cells = 0, so an interrupt specifier here is (number, flags).
    gic.set_u32("#interrupt-cells", 2)
    gic.set_u32("#address-cells", 0)
    # A string, and specifically this string. SecureDTFindEntry takes a property
    # name and a **value** to compare, and pe_arm_map_interrupt_controller's
    # literal pool has the two sitting adjacent:
    #
    #     0xfffffe00070db077  interrupt-controller
    #     0xfffffe00070db08c  master
    #
    # so the search is for a node whose `interrupt-controller` reads "master".
    # A u32 1 was written here for a long time; it satisfied nothing, and the
    # boot survived only because the GICv3 path finds this node by the literal
    # path '/arm-io/gic' instead.
    gic.set_str("interrupt-controller", "master")
    # No `interrupt-controller` **property**. The conventional DT marker is fatal
    # here: IODeviceTreeSupport tests for it while resolving a node's own
    # interrupt parent, and a node carrying both it and `interrupts` takes a
    # branch that leaves the controller pointer null and then dereferences it -
    #
    #     0xa635db4  cbz  x0, ...        ; getProperty("interrupt-controller")
    #     0xa635db8  mov  x19, #0        ; present -> no parent
    #     0xa635df4  ldr  x16, [x19]     ; ... and straight into a null load
    #
    # which shows up as a data abort at pc 0xfffffe000a635df4 before IOKit
    # finishes registering. `device_type` below carries the same meaning for
    # everything that needs to recognise this node, and does not take that path.
    # Referenced by /arm-io/pcie/device-interrupt-parent, which the PCIe driver
    # asserts is present and exactly four bytes long. The PCIe driver turns that
    # phandle into a matching dictionary and calls waitForMatchingService with a
    # timeout of ~0ull, so a phandle naming nothing hangs the boot silently
    # rather than failing.
    gic.set_u32("AAPL,phandle", GIC_PHANDLE)

    # `device_type` is what makes this nub an interrupt controller as far as
    # IOKit is concerned, and the name has to be exactly this.
    #
    # AppleARMGIC reads an `InterruptControllerName` property from its provider,
    # and AppleVirtualPlatformPCIEMSIController reads the same name off the
    # service it is handed - and panics at its line 52 when the value is not an
    # OSSymbol. A device tree property cannot satisfy that: IODeviceTreeSupport
    # turns every property into OSData, so writing the name here directly fails
    # the cast. That was tried; the panic did not move.
    #
    # The name is not supposed to come from the tree at all. AppleARMPE's
    # platformAdjustService sets it, and the code is unambiguous:
    #
    #     if (IODTMatchNubWithKeys(nub, "interrupt-controller"))
    #         nub->setProperty("InterruptControllerName",
    #                          IODTInterruptControllerName(nub));
    #
    # IODTMatchNubWithKeys tests `name`, `compatible`, `device_type` and
    # `model`. This node's name must stay "gic" because the kernel finds it by
    # the literal path '/arm-io/gic', and `compatible` must stay "ARM,gicv3"
    # because that is what AppleARMGICv3's personality matches - so device_type
    # is the one field left, and it is enough. IODTInterruptControllerName then
    # produces the OSSymbol "IOInterruptController%08X" from AAPL,phandle above.
    gic.set_str("device_type", "interrupt-controller")

    # AppleARMGIC::start ends by calling, on its own nub,
    #
    #     registerInterrupt(0, this, handler, NULL)
    #
    # four arguments, which is IOService::registerInterrupt and not the
    # IOInterruptController five-argument form. That routes through
    # IOService::lookupInterrupt -> resolveInterrupt, which reads the
    # IOInterruptControllers and IOInterruptSpecifiers properties IODTMapInterrupts
    # derives from this node's `interrupts`. With no such property there is no
    # source 0 to resolve, the call returns an error, and the driver panics with
    #
    #     "Failed to register GIC to PassthruInterruptController." @AppleARMGIC.cpp:105
    #
    # One cell, because IODTGetICellCounts looks for #interrupt-cells on the
    # parent chain - arm-io and the root both lack it - and falls back to 1. The
    # #interrupt-cells = 3 above describes what *children* of this controller
    # write, not what this node's own `interrupts` means.
    # No `interrupts` property on this node. Apple's tree has none either, and
    # adding one took a data abort inside IODeviceTreeSupport: the interrupt
    # parent of a node that is itself a controller resolves to null and is then
    # dereferenced. The CPU node carries the interrupts instead - see cpu0.
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
    if gic_msi_frame:
        # A third region, and its only consumer is the PCIe MSI controller:
        # /arm-io/pcie carries msi-frame-index = 2, which indexes this node's
        # device memory, and index 2 is this pair. Without it the controller
        # asserts `memory` at AppleVirtualPlatformPCIEMSIController.cpp:57.
        #
        # Apple's own tree has three pairs here for exactly this reason, the
        # third being a 64 KiB window well above the redistributors. On QEMU the
        # equivalent is the GICv3 ITS, which `virt` places at 0x08080000.
        gic.props["reg"] += struct.pack("<QQ",
                                        gic_msi_frame - soc_base, 0x1000)
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

    # Same offset convention as the GIC, and for the same reason.
    # `pl011_uart_setup` does
    #
    #     ml_io_map(pe_arm_get_soc_base_phys() + reg->block_offset,
    #               reg->block_size)
    #
    # so `reg` is relative to arm-io's ranges base. With an absolute address the
    # kernel would map 0x08000000 + 0x09000000 and talk to nothing. It also
    # asserts the property is exactly 16 bytes, one 64-bit offset and one size.
    uart = arm_io.add(Node("uart0"))
    uart.set_str("compatible", "arm,pl011")
    uart.set_str("device_type", "serial")
    uart.set_reg(uart_base - soc_base, 0x1000)
    uart.set_u32("AAPL,phandle", UART_PHANDLE)

    rtc = arm_io.add(Node("rtc"))
    rtc.set_str("compatible", "ARM,pl031")

    # ------------------------------------------------------------------
    # PCIe host bridge - the only route to a root device on this platform.
    #
    # The chain was recovered from the collection's own matching dictionaries
    # by personality.py, and it ends somewhere useful:
    #
    #   AppleVirtualPlatformPCIE     IONameMatch      pcie,vmapple1
    #                                IOProviderClass  AppleARMIODevice
    #   AppleVirtIOPCITransport      IOProviderClass  IOPCIDevice
    #                                IOPCIPrimaryMatch 0x00001af4&0x0000FFFF
    #   AppleVirtIOBlock             IOClass          AppleVirtIOBlockStorageDevice
    #                                IOProviderClass  AppleVirtIOTransport
    #
    # 0x1af4 is the standard virtio vendor ID, which is exactly what QEMU's
    # virtio-blk-pci presents. So Apple's own shipped driver can bind to QEMU's
    # disk with nothing emulated on our side - provided the host bridge comes up.
    #
    # The properties are not guessed. AppleVirtualPlatformPCIE's assertion
    # strings name them, in the order the driver touches them:
    #
    #     fEcamMM != NULL
    #     device-interrupt-parent
    #     deviceInterruptParentPhandle->getLength() == sizeof(UInt32)
    #     msi-frame-index
    #     ranges
    #     vendor-id
    #     device-id
    #
    # Addresses come from QEMU's own generated dtb rather than from reading the
    # source, via `-M virt,dumpdtb=`. Note `highmem-ecam=off`: by default the
    # `virt` machine advertises ECAM at 0x4010000000, which is far outside the
    # 0x08000000 + 0x38000000 window arm-io declares, and a child `reg` cannot
    # reach outside its parent's ranges. With the option, ECAM moves to
    # 0x3f000000 and I/O and 32-bit MMIO land at 0x3eff0000 and 0x10000000 - all
    # three inside the window. Only the 64-bit MMIO aperture stays out, and
    # virtio needs 32-bit BARs only.
    pcie = arm_io.add(Node("pcie"))
    pcie.set_str("compatible", "pcie,vmapple1")
    pcie.set_str("device_type", "pci")
    pcie.set_u32("#address-cells", 3)
    pcie.set_u32("#size-cells", 2)
    pcie.set_reg(PCIE_ECAM_BASE - soc_base, PCIE_ECAM_SIZE)
    pcie.props["bus-range"] = struct.pack("<II", 0, PCIE_ECAM_SIZE // 0x100000 - 1)
    # Apple's own values for the two properties whose meaning is not guessable.
    pcie.props["dev-range"] = struct.pack("<II", 0, 0xFF)

    # Standard PCI ranges: three cells of child address, then parent address and
    # size in this node's parent's cells. The parent is arm-io, so parent
    # addresses are written relative to its base, the same convention `reg` uses
    # one line above. Little-endian cells, because this is an Apple tree and not
    # an FDT - the values were read big-endian out of QEMU's dtb and are
    # re-packed here.
    # Cell order matters and was wrong here. Apple''s tree packs each 64-bit
    # value as a plain little-endian 64-bit field - low word first - so an entry
    # is <u32 flags><u64 pci><u64 cpu><u64 size>, 28 bytes. Packing seven u32s
    # high word first, which is the FDT convention, describes a different
    # machine entirely.
    ranges = b""
    for flags, pci_addr, cpu_addr, size in PCIE_RANGES:
        ranges += struct.pack("<IQQQ", flags, pci_addr, cpu_addr - soc_base, size)
    pcie.props["ranges"] = ranges

    # The bridge's own identity, read by the driver and reported for the root
    # complex nub. Apple's vendor ID with a generic device ID; nothing matches
    # against it, it is descriptive.
    pcie.set_u32("vendor-id", 0x106B)
    pcie.set_u32("device-id", 0x0001)
    pcie.set_u32("device-interrupt-parent", GIC_PHANDLE)
    pcie.set_u32("msi-frame-index", 2)
    pcie.set_u32("interrupt-base", 0x40)
    pcie.set_u32("AAPL,phandle", PCIE_PHANDLE)
    # IOPCIFamily refuses to match any driver whose plist lacks
    # IOPCITunnelCompatible when it considers a nub to be behind a tunnel, and
    # says so: `Driver "%s" needs "%s" key in plist`, a string sitting directly
    # after IOPCITunnelCompatible in its literal pool. That matches what the
    # boot log shows -- the only driver that ever probed a PCI nub here is
    # AppleUIOPCI, and it is the one personality carrying that key.
    #
    # That turned out not to be the gate. The message never appears in the log,
    # and adding IOPCITunnelCompatible and IOPCITunnelled here changed nothing,
    # so both were removed again. Only `built-in` is kept, and only because it
    # is true: this bridge is part of the machine, not plugged into it.
    pcie.props["built-in"] = b""

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























