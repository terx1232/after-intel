# gg-x86-recon

**Measuring, rather than arguing about, what the Apple silicon transition leaves behind.**

macOS 26 Tahoe is the last release that supports Intel. macOS 27 "Golden Gate"
(announced 8 June 2026, shipping late 2026) is Apple-silicon-only. Every
discussion of what that means for running macOS on non-Apple hardware currently
runs on assertion. This repository replaces assertions with numbers.

It contains two small, dependency-free tools and the measurements they produce.
Both run on Windows, Linux or macOS with a stock Python 3.8+. No Mac required.

---

## What has actually been measured

### 1. The community's entire toolchain is x86-only

Every kext the Hackintosh ecosystem depends on was audited for shipped
architecture slices (`tools/macho_audit.py`, output in
`data/community-kexts.json`):

| Project | Mach-O binaries | x86 slices | arm64 slices |
|---|---|---|---|
| Lilu 1.7.2 | 1 | 2 | 0 |
| WhateverGreen 1.7.0 | 2 | 3 | 0 |
| VirtualSMC 1.3.7 | 10 | 12 | 0 |
| AppleALC 1.9.7 | 3 | 5 | 0 |
| VoodooPS2Controller 2.3.7 | 5 | 5 | 0 |
| BrcmPatchRAM 2.7.2 | 8 | 8 | 0 |
| **total** | **29** | **35** | **0** |

Not one arm64 slice exists anywhere in the stack. This is not an oversight — it
follows from what these kexts *are*, which is the finding underneath the finding
(see [docs/01-patchers-not-drivers.md](docs/01-patchers-not-drivers.md)).

### 2. XNU baseline at the last Intel-supporting release

`tools/xnu_arch_check.py` run against `xnu-12377.121.6` (macOS 26.5, published
17 June 2026), full output in `data/xnu-tahoe-26.5.json`:

```
X86 platform code : 199 files,  83 814 lines   (6/6 directories present)
ARM platform code : 207 files, 126 552 lines   (6/6 directories present)

kernel build targets declared in config/:
  MASTER.x86_64          <- Intel is still a first-class build target
  MASTER.arm64.MacOSX
  MASTER.arm64.iPhoneOS
  MASTER.arm64.BridgeOS
  MASTER.arm64.WatchOS
  MASTER.arm  MASTER.arm64  MASTER
```

### 3. The macOS 27 source has not been published yet

At the time of writing (7 August 2026) the newest tags on
`apple-oss-distributions` are `xnu-12377.121.6` and `macos-265`, both dated
17 June 2026 — Tahoe 26.5. Apple publishes source at release, so the Golden Gate
drop is due around GM in the autumn.

**This means nobody has yet checked whether the x86 platform code survives in
the macOS 27 kernel.** That is the one genuinely open, cheaply answerable
question in this whole area, and this repo exists to answer it on day one.

---

## The open question, and why it is worth answering

When the macOS 27 source appears:

```bash
git clone --depth 1 --branch <macos-27-xnu-tag> \
    https://github.com/apple-oss-distributions/xnu.git xnu-gg
python tools/xnu_arch_check.py xnu-gg --json data/xnu-gg.json
```

Two possible outcomes, and they mean very different things:

- **`MASTER.x86_64` and the ~84 000 lines are still there.** Apple kept the
  Intel code because ripping it out costs engineering time for no benefit. The
  open-source kernel can still in principle be built for x86. That does not give
  anyone a bootable macOS — but it keeps a live x86 Darwin base for downstream
  projects (PureDarwin, ravynOS) instead of a frozen 2026 snapshot.
- **They are gone.** From macOS 27 on, even the open part of the stack is
  ARM-only, and every downstream project inherits a dead-end kernel.

Either way it is a fact, dated and reproducible, rather than a forum opinion.

---

## What this repository does *not* claim

Being explicit, because the surrounding discussion usually is not:

**Nothing here is a path to running macOS 27 on a PC.** The kernel is under 5% of
the system, and it is the only part that is open. AppKit, Foundation,
CoreGraphics, WindowServer, Metal, CoreAudio, and every GPU and audio driver are
closed source and, from macOS 27, shipped as arm64e only. There is no source to
recompile and no x86 build to patch. Static ARM→x86 translation of the shipped
binaries runs into pointer authentication, runtime dispatch in Objective-C and
Swift, JIT-generated code, and a fresh set of signatures every point release.

The honest scope of this repo is reconnaissance: know exactly what is on the
other side of the wall, and where the wall actually is.

On that last point, the reconnaissance produced a result worth stating up front:
**the wall is not where it is usually placed.** AMD publishes complete ISA
documentation and an open reference driver, so a kernel-mode GPU driver is
tractable. What is not tractable is Metal — a closed userspace API with a closed
shader compiler, which is what applications actually call. See
[docs/02-hardware-targets.md](docs/02-hardware-targets.md).

---

## Documents

- [PROGRESS.md](PROGRESS.md) — work log, queue, and a list of this repo's own
  known methodological limitations
- [docs/01-patchers-not-drivers.md](docs/01-patchers-not-drivers.md) — what the
  kext bundle metadata reveals about the stack
- [docs/02-hardware-targets.md](docs/02-hardware-targets.md) — which hardware is
  actually easy to write drivers for, and where the wall really is
- [docs/03-air-format.md](docs/03-air-format.md) — the state of knowledge on
  Metal's shader format, and why the shader compiler is the *tractable* part
- [docs/04-apple-x86-artifacts.md](docs/04-apple-x86-artifacts.md) — what x86
  material Apple still ships, and which of it is any use
- [docs/05-metal-surface.md](docs/05-metal-surface.md) — how big Metal actually
  is, measured: 218 classes, 2 558 methods, and why that number decomposes into
  something bounded
- [docs/06-metal-vulkan-divergence.md](docs/06-metal-vulkan-divergence.md) —
  where the two execution models diverge, and why MoltenVK's existence is not
  evidence that the reverse direction is comparable work
- [docs/07-boot-protocol.md](docs/07-boot-protocol.md) — XNU's boot handoff
  measured across architectures, and why the bootloader is the one component
  that is already finished
- [docs/08-building-xnu-for-x86.md](docs/08-building-xnu-for-x86.md) — whether
  the published kernel still builds for Intel, and the surprise that it is the
  easier of Apple's two targets
- [docs/09-emulation-path.md](docs/09-emulation-path.md) — the alternative to
  porting: translate ARM at runtime instead. Why Apple's VM platform is a far
  better emulation target than real Apple silicon, and where that road ends
- **[docs/10-inside-macos27.md](docs/10-inside-macos27.md)** — the shipped
  macOS 27 beta opened up and measured: 13 kernelcaches and not one of them
  x86, every system image named arm64e, and the two x86 binaries that *are*
  in there

Every claim is tagged **[measured]**, **[verified]**, **[literature]** or
**[open]** so a reader can tell an experiment from a citation from a guess.

---

## Tools

### `tools/macho_audit.py`

Parses Mach-O and universal ("fat") headers directly and reports which
architecture slices are present across a tree — per file and in aggregate,
including the arm64 / arm64e distinction that matters for pointer
authentication. Works on any system tree, installer payload, kext bundle or
framework.

```bash
python tools/macho_audit.py /path/to/System --json out.json --entries
```

### `tools/metal_surface.py`

Parses Apple's `metal-cpp` headers and counts the Metal API surface — classes,
methods, enums and constants — then decomposes it by kind of work, separating
mechanical descriptor plumbing from load-bearing encoder and device behaviour.

```bash
python tools/metal_surface.py /path/to/metal-cpp --json out.json
```

### `tools/xar_explore.py`, `tools/zip_carve.py`, `tools/image_arch_scan.py`

The chain for reading a macOS installer without a Mac and without implementing
APFS. `xar_explore.py` reads the package table of contents and extracts members;
`image_arch_scan.py` validates Mach-O headers across a raw byte range, reporting
its own noise floor; `zip_carve.py` recovers zip member listings from raw image
bytes — names are stored uncompressed — and decompresses individual members by
offset to identify their architecture.

```bash
python tools/xar_explore.py Install*.pkg --json toc.json
python tools/zip_carve.py Install*.pkg --start N --length N --grep dyld --archcheck
```

### `tools/boot_protocol.py`

Extracts XNU's `boot_args` handoff struct from `pexpert/pexpert/<arch>/boot.h`
and compares the field inventory across architectures, classifying each field as
core, EFI-dependent or boot-security. Self-validates against XNU's own
compile-time size assertion.

```bash
python tools/boot_protocol.py /path/to/xnu --json out.json
```

### `tools/xnu_arch_check.py`

Counts per-architecture platform code in an XNU source checkout and enumerates
the kernel build targets the tree still declares. The probe paths are verified
against a Tahoe checkout, so a missing directory in a later tree is a real
deletion rather than a bad guess.

```bash
python tools/xnu_arch_check.py /path/to/xnu --json out.json
```

---

## Reproducing

```bash
git clone --depth 1 --branch xnu-12377.121.6 \
    https://github.com/apple-oss-distributions/xnu.git _work/xnu-tahoe
python tools/xnu_arch_check.py _work/xnu-tahoe --json data/xnu-tahoe-26.5.json
```

`_work/` is gitignored; the repository itself is text and stays small.

## Sources

- macOS 27 is Apple-silicon-only — [MacRumors, 10 Jun 2026](https://www.macrumors.com/2026/06/10/macos-golden-gate-last-to-support-intel-apps/)
- Tahoe as the last Intel release — [AppleInsider, 17 Jun 2025](https://appleinsider.com/articles/25/06/17/opencore-and-hackintosh-are-sadly-dead-after-apple-ends-intel-mac-support)
- Apple open source — [github.com/apple-oss-distributions](https://github.com/apple-oss-distributions)

## Licence

Tools are MIT. Measurements are facts and belong to nobody.
