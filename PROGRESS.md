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
| 11 | The Metal graphics surface is 218 classes / 2 558 methods / 918 enum values; 46.5% of Metal's methods are descriptor property accessors, ~480 are load-bearing | [measured] `data/metal-surface.json` |
| 12 | Metal tracks hazards automatically by default; Vulkan requires explicit barriers. Metal→Vulkan must therefore synthesise a per-resource tracker that the API surface count does not show — a subsystem independently reported as the hottest code in a comparable project | [literature] `docs/06-metal-vulkan-divergence.md` |
| 13 | MoltenVK's documented limitations amount to four narrow bullets, so Vulkan→Metal is effectively solved — which is why citing it as evidence for the reverse is a category error | [verified] MoltenVK user guide |

| 14 | XNU's x86 boot handoff is 49 fields / exactly 4096 bytes: 12 EFI-dependent, 15 boot-security. arm64 is 13 fields, no EFI, no security state. The x86 entry contract is written in EFI's vocabulary, which is why the loader must be a UEFI application | [measured] `data/boot-protocol.json` |
| 15 | The bootloader participates in the sealed-system-volume chain: it supplies the ARV root hash and manifest for both the system volume and Base System, plus the APFS volume key and SIP configuration | [verified] `pexpert/pexpert/i386/boot.h` |

| 16 | Building XNU for Intel needs no Kernel Debug Kit; building for Apple silicon does, plus a per-SoC platform identifier. Apple's README states this outright. The open-source kernel is *more* self-sufficient on x86 than on ARM | [verified] XNU `README.md` |
| 17 | All four declared XNU build dependencies (DTrace, AvailabilityVersions, libdispatch, xnu headers) are published; DTrace is marked optional. The real gate is that the build needs Xcode, i.e. a Mac | [verified] XNU `README.md` |
| 18 | Apple's VM platform (VMAPPLE) uses standard GICv3 and PL011 rather than Apple's AIC and custom UART, and paravirtualises PAC and CTRR with no secure monitor. It is a far cleaner emulation target than real Apple silicon | [verified] `pexpert/pexpert/arm64/VMAPPLE.h` |
| 19 | Emulating a weak-ordered ARM guest on a strongly-ordered x86 host is the favourable direction for memory ordering; no hardware assist is needed, unlike x86-on-ARM which required Apple to add a TSO mode | [verified] architecture semantics |
| 20 | macOS 27 beta `26A5388g` ships 13 kernelcaches, 12 for Apple silicon Mac platforms and one (`vma2`) for the Apple Virtual Machine platform. There is no x86 kernelcache | [measured] `data/gg-zip-members.json` |
| 21 | Every system image in the package is named arm64e — `arm64eBaseSystem.dmg`, `cryptex-system-arm64e`, `arm64eSURamDisk.dmg` — with no x86 counterpart anywhere in 1 842 members | [measured] same |
| 22 | Exactly 3 Mach-O binaries are directly visible in the 16.46 GiB payload; the only two carrying x86_64 slices both belong to `UpdateBrainService`, i.e. update infrastructure rather than the installed system | [measured] `data/gg-member-archs.json` |
| 23 | The largest single item in the payload is `cryptex-system-rosetta` — the x86-on-ARM translation runtime. Apple's biggest x86 artifact in macOS 27 points inward, as every other one does | [measured] same |

## In progress

**Track: what is actually inside the shipped macOS 27 installer.**

- **Open the opaque containers.** `payloadv2/payload.NNN`, the cryptexes and the
  `.dmg.aea` Apple Encrypted Archives were not opened, so the installed
  system's individual binaries remain un-enumerated. Until that is done,
  finding #21 rests on image *naming*, not on a binary census of the installed
  system. Establishing whether the containers are readable at all is the next
  step.
- **Decode a kernelcache.** The 13 kernelcaches did not decode as bare Mach-O,
  so they are IM4P-wrapped or LZSS-compressed. Confirming their architecture
  directly would turn finding #20 from a naming argument into a header
  measurement.

## Queue

1. **OpenCore x86-specific surface** — measure how much of OpenCorePkg is
   architecture-bound, using the checkout already in `_downloads/`.
2. **Argument buffers, residency and heap aliasing** — three gaps left [open] by
   finding #12. Deferred behind the bootloader track at the user's direction.
3. **Local image audit** — run `macho_audit.py` against the Big Sur
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
