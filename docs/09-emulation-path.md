# The emulation path, and why VMAPPLE is the right target

> **Status: [verified]** from `pexpert/pexpert/arm64/VMAPPLE.h` in
> `xnu-12377.121.6`, plus **[literature]** for the QEMU and prior-art claims.
> Nothing here was run.

Every other document in this repository examines *porting* — getting an x86
build of something that only exists for ARM. This one examines the alternative:
leave the system as ARM code and translate it at runtime.

That approach deserves a serious hearing, because it is the only one in this
whole area with a working prototype. Zhuowei Zhang booted the arm64e kernel of a
macOS 11 beta to `launchd` under QEMU on non-Apple hardware. No port ever got
close to that.

The question is what you would be emulating.

## Two very different targets

**A real Apple silicon Mac.** This is what the prior art attempted, and the
blockers it hit were all Apple-specific silicon: Apple's modified pointer
authentication algorithm (disabled outright rather than implemented), APRR
memory-permission remapping for JIT, and AIC, Apple's custom interrupt
controller. Plus an undocumented GPU that Asahi spent years reverse engineering
merely to write a *driver* for — emulating it is strictly harder than driving it.

**The Apple Virtual Platform.** Apple defines a second, entirely separate
hardware target for macOS VMs, and it is described in XNU's own published
source. It is a far more tractable thing.

## What VMAPPLE actually requires

`pexpert/pexpert/arm64/VMAPPLE.h`, read directly:

```c
#define HAS_GIC_V3                1
#define PL011_UART
#define HAS_PARAVIRTUALIZED_PAC   1
#define HAS_PARAVIRTUALIZED_CTRR  1
#define NO_MONITOR                1
#define NO_ECORE                  1
#define HAS_ARM_FEAT_SME          1
#define HAS_ARM_FEAT_SME2         1
#define HAS_ARM_FEAT_SSBS2        1
#define HAS_ARM_FEAT_PAN3         1
#define __ARM_16K_PG__            1
```

Read that list against the blockers above:

| Real Mac blocker | On VMAPPLE |
|---|---|
| AIC, Apple's custom interrupt controller | **GICv3** — a standard ARM controller. The header even cites the spec, Arm IHI 0069G, and includes the register definitions. |
| Apple's custom UART | **PL011** — ARM PrimeCell, public spec, emulated in QEMU for over a decade. |
| Apple's modified PAC algorithm | **`HAS_PARAVIRTUALIZED_PAC`** — pointer authentication is provided through a hypervisor interface rather than secret silicon behaviour. |
| CTRR / KTRR text protection | **`HAS_PARAVIRTUALIZED_CTRR`**, and `NO_MONITOR` — no secure monitor firmware layer at all. |
| Heterogeneous P/E cores | **`NO_ECORE`** — homogeneous CPU. |
| Undocumented Apple GPU | virtio devices, which are open standards. |

The remaining CPU requirements — SME, SME2, SSBS2, PAN3, 16K pages — are all
publicly specified ARM architecture extensions, not Apple inventions.

**The Apple Virtual Platform is mostly standard ARM hardware, and the
Apple-specific parts are paravirtualised — that is, they have a defined
interface by construction, because a hypervisor has to implement them.** That is
a categorically better emulation target than an M-series die.

## One thing genuinely in this approach's favour

ARM has a weak memory model; x86 has a strong one. Emulating a weak-ordered
guest on a strongly-ordered host is the **easy** direction — the host already
provides more ordering than the guest requires, so no extra fences are needed.

This is worth stating because the reverse direction is famously hard: Apple had
to add a total-store-ordering hardware mode to the M-series specifically to make
x86-on-ARM emulation fast. Nobody needs to add anything to run ARM on x86.

## What still blocks it

Being precise, since the target looks better than expected:

1. **AVPBooter.** QEMU's `vmapple` machine model implements the Virtualization
   .framework device model, but needs `AVPBooter.vmapple2.bin` — Apple's signed
   VM firmware — plus a trimmed `aux.img` and a `disk.img`, all extractable only
   from a running Apple silicon Mac. Replacing it means reimplementing Apple's
   boot chain including Image4 verification.
2. **QEMU's `vmapple` is `hvf`-only.** The documented configuration uses
   hardware virtualisation, which means an Apple silicon host. There is no TCG
   path today. QEMU emulates ARM64 guests under TCG on x86 hosts perfectly well
   in general, so this is ordinary engineering rather than a wall — but it is
   unwritten, and guest support is documented as macOS 12.x only.
3. **Code signing.** The prior art could not disable signature enforcement, and
   the trustcache failed to load at the expected address. macOS 27 is stricter
   than macOS 11 was, with the sealed system volume on top.
4. **Performance, and this is the one that decides it.** QEMU TCG runs roughly
   an order of magnitude slower than native for CPU-bound code. The guest would
   talk to a virtio GPU with no path to host acceleration, so the entire
   graphics stack is software-rendered on top of an emulated device on top of a
   translated CPU. That is not "slow". A desktop compositor under those
   conditions does not produce a usable session.

## On the two specific proposals

**"Embed the translator in the bootloader."** Architecturally this cannot be a
bootloader. A loader sets up state, hands off, and exits; runtime translation
needs a *resident* component that stays underneath the guest for the machine's
whole life. That component is a hypervisor or a full-system emulator. The idea is
sound — it is simply that the thing being described is QEMU. Which is good news,
because QEMU exists and already has a `vmapple` machine.

**"Pre-translate it ahead of time instead."** Ahead-of-time translation cannot
be complete, for reasons that are properties of the binaries rather than of
effort: arm64e pointers are PAC-signed so branch targets are not statically
recoverable; Objective-C and Swift resolve calls through `objc_msgSend` at
runtime; JavaScriptCore and the Metal shader compiler generate code during
execution. Every real AOT translator, Rosetta 2 included, falls back to JIT for
exactly this, so AOT is always a hybrid and never a replacement. And Apple
re-signs and re-issues every binary each point release, so the translation is
perishable.

## The honest ranking

Emulation gets further, faster, toward "the kernel boots" than any porting
approach — the prior art proves that, and VMAPPLE makes the target much cleaner
than the prior art had to deal with.

It gets nowhere on "a usable graphical system", and it does so for a different
reason than porting does. Porting fails because Metal's implementation does not
exist for x86. Emulation fails because the whole stack runs at emulated speed
with no acceleration path. Both roads end, but they end at different places, and
neither ends at a working desktop.

Where emulation *is* clearly worth it: as a research and preservation
instrument. A TCG-capable `vmapple` machine would let people study, debug and
archive Apple silicon macOS without owning Apple hardware. That is a real,
bounded, publishable contribution, and it does not require the result to be fast.

## Sources

- `pexpert/pexpert/arm64/VMAPPLE.h`, XNU `xnu-12377.121.6` — read directly
- [VMApple machine emulation — QEMU documentation](https://www.qemu.org/docs/master/system/arm/vmapple.html)
- [Booting a macOS Apple Silicon kernel in QEMU — Zhuowei Zhang](https://worthdoingbadly.com/xnuqemu3/)
