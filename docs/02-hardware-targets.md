# Which hardware is actually easy to write drivers for

The premise of this document is a practical one: if you were going to target a
single machine configuration, which components can a small team realistically
support, and which cannot be supported at any effort level?

The answer is more lopsided than the usual framing suggests, and it moves the
wall to a different place than most discussions put it.

## Tier 1 - trivial, and already done

Fully public specifications, small state machines, decades of stability.

| Component | Spec | Status in the ecosystem |
|---|---|---|
| PS/2 keyboard / trackpad | 1987 IBM spec, ~2 I/O ports | VoodooPS2Controller, from scratch |
| 16550 UART serial | Public since 1987 | Trivial, a few hundred lines |
| RTC / CMOS, HPET, APIC | ACPI + Intel SDM | Documented, no surprises |
| SMBus / I2C controllers | Public Intel datasheets | Documented |

## Tier 2 - easy, and the community has already proven it

Open industry specifications. These are the ones people cite when they say
"nobody writes real drivers any more" - and the claim is false.

| Component | Spec source | Evidence it was done from scratch |
|---|---|---|
| AHCI (SATA) | Open Intel spec | Reference implementations everywhere |
| NVMe | Open at nvmexpress.org | Fully public standard |
| xHCI (USB 3) | Open Intel spec | Fully public standard |
| Realtek RTL8111/8168 Ethernet | Semi-public datasheets | Mieze, `RTL8111_driver_for_OS_X` |
| Intel onboard Ethernet | Public datasheets | Mieze, `IntelMausiEthernet` |
| SDHCI card readers | Open SD Association spec | Documented |

Mieze's two Ethernet drivers are the important data point. They are not patches
on Apple code. They are real drivers with no-copy transmit and receive,
multisegment packets, and TCP/UDP/IPv4 and IPv6 checksum offload - the kind of
thing a vendor ships. Written by one person against public datasheets.

There is a caveat worth recording, because it is the recurring failure mode:
`RealtekRTL8111` binds to macOS's *private* networking interface, so when Apple
updates `IONetworking.kext` the linker can fail to notice and the result is a
kernel panic. Real drivers are achievable; staying compatible with a closed,
moving host OS is the part that grinds people down.

## Tier 3 - hard, but genuinely documented

This is where the received wisdom is wrong, and it is worth being precise.

**AMD GPUs are extensively documented in public.** AMD publishes ISA reference
guides going back to R600 and continuing through RDNA 3.5; machine-readable XML
specifications of every instruction, encoding, operand and data format; an
IsaDecoder API for parsing them; and the entire `amdgpu` kernel driver plus the
LLVM AMDGPU backend as open source that functions as living documentation.

So "you cannot write a GPU driver because the hardware is undocumented" is true
for Apple silicon GPUs and largely true for NVIDIA, and **false for AMD**. This
is exactly why FreeBSD and Linux have working AMD acceleration.

Intel iGPUs sit in a similar place: Intel publishes Programmer's Reference
Manuals for its graphics hardware.

If a target configuration were being chosen today on driver-difficulty grounds
alone, it would be: an AMD GPU, Intel or Realtek Ethernet, NVMe storage, xHCI
USB, PS/2 or USB input, HDA audio. Every one of those has a public spec and a
readable open-source reference implementation.

## Tier 4 - the actual wall

And here is the finding that matters, because it is *not* where people put it.

### Metal

A kernel-mode GPU driver gets you memory management, command submission and a
display. It gets you no applications, because macOS applications do not talk to
the GPU - they talk to **Metal**, and Metal is a closed userspace API with a
closed shader compiler.

The state of play:

- **ravynOS**, after five years of development, lists its graphics system as
  *"EFI Framebuffer (Future: DRM/KMS, OpenGL, Metal)"*. It is still on an
  unaccelerated firmware framebuffer. Their own notes describe needing to port
  the Quartz WindowServer implementation onto a GOP framebuffer first, and
  "eventually to Metal/Vulkan/DRM-KMS or something accelerated."
- **Metal → Vulkan translation does not exist.** MoltenVK is mature, Valve-owned
  and Apache-licensed - and runs the *opposite* direction, Vulkan on top of
  Metal. The reverse ("MetalVK") exists only as a proposal in a Darling
  discussion thread.
- The shader format is partially understood. Metal shaders are AIR, which is
  LLVM bitcode produced by a modified clang. Zhuowei Zhang's `MetalShaderTools`
  and related work have compiled Metal bitcode to x86 and ARM assembly, and the
  IR format has been publicly documented in part.

### Everything else in tier 4

Wi-Fi and Bluetooth (signed firmware blobs plus regulatory constraints), camera
and image signal processors, Thunderbolt. All undocumented, all firmware-bound.
These are genuinely closed in a way AMD graphics is not.

## The conclusion this leads to

Choosing "hardware that is easy to write drivers for" does not route around the
problem. It routes around roughly ninety-five percent of it, and leaves the
remaining five percent untouched - because storage, networking, USB, input and
audio controllers were never the hard part, and the hard part was never a
driver at all.

The single highest-leverage unclaimed piece of work in this entire area is a
**Metal implementation on top of Vulkan**. It is proposed and unbuilt. If it
existed:

- ravynOS gets accelerated graphics and a path to running real macOS software
- Darling gets GUI applications on Linux
- every downstream Darwin project stops being blocked on the same component

And it has a property nothing else here has: **it lives entirely in userspace.**
No kernel panics, no serial-console bisection, no code signing, no boot chain.
You can write it, run it, and see it fail with a stack trace like normal
software. That is the one place in this problem space where a fast iteration
loop is available at all.

## Sources

- [AMD machine-readable GPU ISA documentation](https://gpuopen.com/machine-readable-isa/)
- [AMD GPU architecture programming documentation](https://gpuopen.com/amd-gpu-architecture-programming-documentation/)
- [ravynOS technical details](https://ravynos.com/more/) and [roadmap](https://wiki.ravynos.com/roadmap)
- [MetalVK proposal - darling discussion #1646](https://github.com/darlinghq/darling/discussions/1646)
- [MoltenVK](https://github.com/KhronosGroup/MoltenVK)
- [MetalShaderTools - zhuowei](https://github.com/zhuowei/MetalShaderTools)
- [RTL8111_driver_for_OS_X - Mieze](https://github.com/Mieze/RTL8111_driver_for_OS_X)
- [IntelMausiEthernet - Mieze](https://github.com/Mieze/IntelMausiEthernet)
