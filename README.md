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
