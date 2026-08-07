# Work log and queue

Running record of what has been established, what is in progress, and what is
queued. Every claim in this repository is tagged with how it was arrived at:

- **[measured]** — produced by a tool in `tools/`, output committed to `data/`
- **[verified]** — read directly from a primary source (Apple source tree,
  shipped bundle metadata, official documentation)
- **[literature]** — taken from published third-party reverse engineering, not
  independently reproduced here
- **[open]** — not established; stated as a question, not an answer

The distinction matters. This repo is worth nothing if it becomes another pile
of confident forum assertions.

---

## Established

| # | Finding | Basis |
|---|---|---|
| 1 | All 29 Mach-O binaries in the core Hackintosh kext stack are x86-only; zero arm64 slices | [measured] `data/community-kexts.json` |
| 2 | XNU at macOS 26.5 carries 83 814 lines of x86 platform code in 199 files; `config/MASTER.x86_64` present | [measured] `data/xnu-tahoe-26.5.json` |
| 3 | WhateverGreen and AppleALC match on `IOResources` and pull `com.apple.kpi.unsupported`; they patch Apple drivers rather than implement anything | [verified] shipped `Info.plist` |
| 4 | VoodooPS2Controller, RealtekRTL8111 and IntelMausiEthernet are real from-scratch drivers | [verified] `Info.plist` + project sources |
| 5 | AMD publishes full GPU ISA documentation (R600 → RDNA 3.5), machine-readable instruction specs, and an open reference driver | [verified] gpuopen.com |
| 6 | Apple has not published macOS 27 source; newest tags `xnu-12377.121.6` / `macos-265`, both 17 Jun 2026 | [verified] apple-oss-distributions |
| 7 | `.air` is standard LLVM bitcode; `.metallib` is a FourCC container; target triple `air64-apple-macosx*` is unregistered in upstream LLVM | [literature] see `docs/03-air-format.md` |
| 8 | Apple's macOS VM restore images (IPSW, via mesu.apple.com) are Apple-silicon only; no x86 equivalent exists | [verified] |
| 9 | iOS Simulator runtimes ship real `x86_64-simulator` slices; Apple built modern framework binaries for x86_64 well into the transition | [verified] |
| 10 | Apple ships and supports an x86→ARM translator for Linux VMs; there is no ARM→x86 counterpart | [verified] |

## In progress

- **Metal API surface sizing.** How many classes and methods would a
  reimplementation actually have to cover? Nobody has published a number.

## Queue

1. **Metal API surface sizing** — count the public `MTL*` protocol and class
   surface from published headers; produce a concrete "how big is this job"
   figure rather than an adjective.
2. **Local image audit** — run `macho_audit.py` against the Big Sur
   `BaseSystem.dmg` in `_downloads/`. Big Sur is the first universal release, so
   it is the earliest point where the arm64/x86_64 ratio inside Apple's own
   shipped system becomes measurable. Blocked on reading APFS from Windows;
   needs a plan.
3. **dyld shared cache support** in `macho_audit.py`. From Big Sur on, most
   system libraries are not standalone files — they live inside the shared
   cache. Any audit that ignores it undercounts massively, and the current tool
   ignores it. This is a known limitation of finding #1's methodology when
   applied to a full system tree.
4. **XNU x86 build feasibility** — can the published XNU actually be built for
   x86_64 standalone, or does it require unpublished dependencies? This is
   checkable and has not been checked here.
5. **macOS 27 source watch** — the moment the GG tag appears, run
   `xnu_arch_check.py` against it and commit the diff against the Tahoe
   baseline.
6. **Simulator runtime audit** — unpack a Tahoe-era `.simruntime` bundle and run
   `macho_audit.py` over it, to settle whether the x86_64 iOS Simulator runtime
   contains a standalone `Metal.framework` binary or only a forwarding shim into
   the host. Needs a Mac or an Xcode install; cannot be done in this
   environment. See `docs/04-apple-x86-artifacts.md`.

## Known limitations of what is already here

Recording these because a repo that only lists its strengths is advertising.

- `macho_audit.py` does not parse the dyld shared cache (queue item 3). Its
  numbers are correct for loose binaries and kexts, and would badly undercount a
  modern full system volume.
- Finding #2 counts lines in architecture-specific directories. It does not
  count `#ifdef __x86_64__` blocks scattered through shared code, so the true
  x86 footprint in XNU is larger than 83 814 lines by an unmeasured amount.
- Nothing in `docs/03-air-format.md` has been reproduced here. There is no Mac
  and no Metal toolchain in this environment, so it is literature review and is
  labelled as such throughout.
