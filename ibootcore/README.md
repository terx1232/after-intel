# IbootCore

A loader for arm64e XNU that is not iBoot and not AVPBooter.

## What this is for

Apple's Virtual Machine platform is the only configuration in which macOS 27
can plausibly be made to start on non-Apple hardware, by emulating an ARM guest
rather than porting anything. That is argued from measurements in
[../docs/09-emulation-path.md](../docs/09-emulation-path.md) and
[../docs/10-inside-macos27.md](../docs/10-inside-macos27.md); the short version
is that `VMAPPLE` is built from standard ARM primitives, and Apple ships a
kernel for it, `kernelcache.release.vma2`, in the retail installer.

The blocker on that route is `AVPBooter.vmapple2.bin` - Apple's signed VM
firmware, extractable only from a Mac. IbootCore is an attempt to establish how
much of what AVPBooter does can be reconstructed from published sources instead.

**Goal: the kernel starts executing.** Not a desktop, not an installer, not a
usable system. Instructions retiring inside the kernel image, and a crash with a
diagnosable cause, would be the milestone.

## What works now

Six pieces, all derived from Apple's own published material rather than guessed.

### `loadmap.py` - where the kernel wants to live

Reads the Mach-O load commands of a kernel collection and prints its memory map
plus the `boot_args` values that follow from it.

For `kernelcache.release.vma2` (output in `../data/vma2-loadmap.json`):

```
entry point (pc): 0xfffffe0009e3c480
virtBase        : 0xfffffe0007004000
virtual span    : 80,871,424 bytes (77.1 MiB)
UUID            : e17fc1e4-1a81-ec3f-52f2-55be515b96ea
segments        : __TEXT __PRELINK_TEXT __DATA_CONST __TEXT_EXEC
                  __PRELINK_INFO __DATA __LINKEDIT
```

One property matters more than the rest: the virtual span is **exactly** the
file size, and `__LINKEDIT`'s file offset plus its size lands on the end of the
file. The collection maps one to one, so `vmaddr = virtBase + fileoff` and a
loader can place the whole 77 MiB image as a single contiguous blob rather than
walking segments.

### `devicetree_req.py` - what the tree must contain

`boot_args.deviceTreeP` points at a device tree, and the kernel's platform
drivers will not attach without nodes they recognise. Rather than guessing,
this reads the requirement out of the kernel: an `MH_FILESET` carries every
bundled kext's Info.plist in `__PRELINK_INFO` as an XML property list, and the
IOKit matching dictionaries name the nodes each driver looks for.

From vma2: 235 kexts, 1 114 personalities, 242 distinct `IONameMatch` names,
120 distinct provider classes. The platform-relevant subset:

| Node | Driver class | What it is |
|---|---|---|
| `AppleVirtualPlatformARM` | `AppleVirtualPlatformARMPE` | the platform expert - the root |
| `arm-io,vmapple1` | `AppleVirtualPlatformIO` | the I/O bus |
| `pcie,vmapple1` | `AppleVirtualPlatformPCIE` | PCIe host |
| `ARM,gicv3` | `AppleARMGICv3` | interrupt controller, ARM IHI 0069 |
| `ARM,psci` | `ApplePSCI` | power state coordination, ARM DEN 0022 |
| `ARM,pl031` | `ApplePL031RTC` | PrimeCell RTC |
| `ARM,pl061` | `AppleVirtualPlatformButtons` | PrimeCell GPIO |
| `cpu` | `AppleARMCPU` | processor nodes |
| `uart0` .. `uart8` | `AppleSerialShim` | console |
| `avp,rtc`, `avp,sealed-registers`, `port-virtual-1` | various | Apple-specific |

Most of that list is standard ARM with public specifications. Only four node
names are Apple inventions.

### `kext_strings.py` - what properties a driver reads

Node names get a structurally valid tree; each node also has to carry the
properties its driver looks up, and those are in no plist. They are in the
driver: IOKit property lookups take a C string, so every property name appears
as a literal in the kext's `__TEXT,__cstring`. This extracts them.

Results vary sharply by driver, which is recorded rather than smoothed over:

| Driver | strings | property-like |
|---|---:|---:|
| `AppleARMPlatform` | 2 535 | 258 |
| `AppleVirtualPlatform` | 558 | 35 |
| `AppleARMGIC` | 82 | **0** |

From `AppleVirtualPlatform`: `chip-id`, `unique-chip-id`, `avp-features`,
`ranges`, `interrupt-base`, `device-interrupt-parent`, `msi-frame-index`,
`syscfg`, `monotonicclock`. From `AppleARMPlatform`: `cpu-id`,
`clock-frequencies`, `clock-gates`, `cluster-type`, `boot-manifest-hash`,
`device-clocks-max`, and 250 more.

The GIC returning zero is not a bug in the tool - that driver does not reference
property names through string constants, so this technique simply does not reach
it. Some other approach is needed there.

### `devicetree.py` - emitting the tree

Apple's flattened device tree is not FDT/dtb and is far simpler. XNU defines it
in `pexpert/pexpert/device_tree.h`: a node is `nProperties` and `nChildren` as
32-bit words followed by that many properties then that many child nodes; a
property is a 32-byte NUL-padded name, a 32-bit length, and a value padded to a
4-byte multiple. No header, no magic, no string table.

This module builds, serialises and parses that format, and `--selftest` proves
the serialiser by round-trip:

```
$ python devicetree.py --selftest
  serialised: 1840 bytes
  parsed back: consumed 1840 of 1840 bytes
  nodes: 10, properties: 39
  PASS: round-trip is byte-identical
```

### `bootargs.py` - the handoff block

Thirteen fields, 1 152 bytes with natural alignment, and no firmware
dependency anywhere in it. `--layout` prints the offsets so they can be checked
against `pexpert/pexpert/arm64/boot.h` rather than trusted. For contrast, the
x86 equivalent is asserted by XNU to be exactly 4 096 bytes and carries twelve
EFI-dependent fields.

### `build_image.py` - assembling it

Places kernel, device tree and `boot_args` at fixed physical addresses and
writes one flat file an emulator can load, then prints the CPU state required
at handoff: `PC` = the kernel entry point, `x0` = the physical address of
`boot_args`. Optionally populates the `Video` fields for a boot-console
framebuffer.

It ships no Apple code. It reads a kernel you already have and writes an image
locally.

## What does not work, and why

Being explicit, because a repository of working parts can read as a working
whole.

- **The node property values are placeholders.** Names are recovered; `reg`
  ranges, interrupt specifiers and clock frequencies are not. The tree
  `devicetree.py` emits is structurally valid and semantically invented. This
  is the largest single gap.
- **Nothing here executes anything.** There is no CPU. QEMU's `vmapple` machine
  is `hvf`-only, so a TCG path has to be written before any of this can be
  handed to a processor. QEMU is not installed in the environment this was
  developed in, so none of it has been tried even against a generic machine.
- **VirtualBox cannot run any of this.** It is a virtualiser, not an emulator:
  guest code executes natively on the host CPU via VT-x, with no translation
  layer, so it cannot execute an ARM instruction on x86 at all.
- **AVPBooter does more than build these structures.** How much more - page
  table setup, CPU state, Image4 chain handling, the `aux.img` contract - is
  **unknown** and has not been established. Assuming these pieces are sufficient
  would be unfounded.
- **Code signing and the trustcache** stopped the only prior attempt at this, on
  a much older and less strict macOS.
- **Nobody has run any of this.** Every claim above is about format correctness,
  verified by round-trip and against Apple's headers. None of it is a claim that
  a kernel accepts the result.

## Provenance

Everything here derives from material Apple publishes: the XNU source at
`xnu-12377.121.6` for the structures, and the shipped
`InstallAssistant_27.0_26A5388g.pkg` for the kernel collection that states its
own requirements. No Apple code or binaries are redistributed.
