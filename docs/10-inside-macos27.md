# What is actually inside the macOS 27 installer

> **Status: [measured].** Produced by `tools/xar_explore.py`,
> `tools/image_arch_scan.py` and `tools/zip_carve.py` from
> `InstallAssistant_27.0_26A5388g.pkg`, 16 972 015 289 bytes. Raw output in
> `data/gg-installer-toc.json`, `data/gg-image-arch-scan.json`,
> `data/gg-zip-members.json` and `data/gg-member-archs.json`.
>
> This is, as far as we can establish, the first published per-binary
> architecture census of macOS 27. Everything below came out of the shipped
> bytes, not out of a release note.

## Provenance

The package identifies itself in its own `PackageInfo`:

```xml
identifier="com.apple.pkg.InstallAssistant.Seed.macOS27Seed"
bundle path="./Applications/Install macOS 27 Golden Gate Beta.app"
```

and `version.plist` gives `ProductBuildVersion 26A5388g`, `IsSeed: true`.
The "Golden Gate" name is confirmed from Apple's own metadata rather than from
press coverage.

## Method

The chain is package → disk image → zip archives → binaries, and reading it
properly would mean implementing APFS. Three cheaper steps sufficed:

1. `InstallAssistant.pkg` is a **xar** archive. Its table of contents shows five
   members, of which `SharedSupport.dmg` is 15.8 GB and, importantly, stored
   **uncompressed** - so it can be read in place at a known offset without
   extracting a copy.
2. That DMG is **UDIF v4** with a `koly` trailer, data fork at +0, 15.79 GiB.
3. A full linear scan for Mach-O headers across all 15.79 GiB found **zero**
   binaries, with only 17 magic hits rejected by header validation across the
   whole image - a near-zero noise floor. Everything is packed.
4. What it *is* packed in turned out to be **zip**. Zip stores member names
   uncompressed, so a linear carve recovers the complete file listing without
   any filesystem support, and individual members can then be decompressed by
   offset.

Result: **1 842 members, 16.46 GiB declared uncompressed.**

## Finding 1: thirteen kernelcaches, none of them x86

```
kernelcache.release.mac13g   kernelcache.release.mac15j   kernelcache.release.mac17g
kernelcache.release.mac13j   kernelcache.release.mac15s   kernelcache.release.mac17j
kernelcache.release.mac14g   kernelcache.release.mac16g   kernelcache.release.mac17p
kernelcache.release.mac14j   kernelcache.release.mac16j   kernelcache.release.vma2
kernelcache.release.mac15g
```

Twelve are named for Apple silicon Mac platforms. There is no x86 kernelcache in
the package - not a stripped one, not a legacy one, none.

The thirteenth is worth its own line: **`vma2`** is the Apple Virtual Machine
platform - the target described in
[docs/09-emulation-path.md](09-emulation-path.md) via XNU's own `VMAPPLE.h`.
Apple ships a kernel for it in the retail installer.

All thirteen are **IM4P** (Image4 payload) containers, tag `krnl`, description
`KernelManagement_host-514`, with the payload **LZFSE**-compressed (`bvx2`
magic). The `vma2` cache is 23 085 654 bytes against roughly 32 MB for the real
Mac platforms - consistent with a VM kernel needing fewer drivers.

### All thirteen, unwrapped and read

`tools/im4p_extract.py` parses the DER container and decompresses the payload.
Run over every kernelcache in the package (`data/gg-kernelcaches.json`):

| kernelcache | IM4P payload | kernel | arch | type | kexts |
|---|---:|---:|---|---|---:|
| mac13g | 32 531 724 | 121 585 664 | arm64e | fileset | 342 |
| mac13j | 32 897 807 | 123 027 456 | arm64e | fileset | 345 |
| mac14g | 33 166 830 | 123 731 968 | arm64e | fileset | 349 |
| mac14j | 33 213 172 | 123 748 352 | arm64e | fileset | 353 |
| mac15g | 32 958 186 | 122 912 768 | arm64e | fileset | 347 |
| mac15j | 33 439 881 | 124 698 624 | arm64e | fileset | 355 |
| mac15s | 32 950 102 | 122 765 312 | arm64e | fileset | 347 |
| mac16g | 33 454 969 | 125 435 904 | arm64e | fileset | 363 |
| mac16j | 33 338 960 | 124 452 864 | arm64e | fileset | 362 |
| mac17g | 33 666 365 | 126 156 800 | arm64e | fileset | 370 |
| mac17j | 32 018 221 | 121 389 056 | arm64e | fileset | 368 |
| mac17p | 31 656 495 | 119 537 664 | arm64e | fileset | 362 |
| **vma2** | 23 085 403 | 80 871 424 | arm64e | fileset | 216 |

**Thirteen of thirteen are arm64e**, read from the `cputype` field of each
decompressed Mach-O rather than inferred from a filename. Every one is an
`MH_FILESET` kernel collection. The Mac platforms carry 342-370 bundled kexts
in 119-126 MB; the virtual platform carries 216 in 81 MB, which is what a
machine with no real hardware to drive looks like.

### The vma2 kernel in detail

`tools/im4p_extract.py` parses the DER container and decompresses the payload.
For `kernelcache.release.vma2` (full output in `data/gg-vma2-kernel.json`):

```
payload      : 23 085 403 bytes, lzfse (bvx2)
decompressed : 80 871 424 bytes (3.50x)

architecture    : arm64e   (cputype 0x0100000c, cpusubtype 0xc0000002)
file type       : fileset (MH_FILESET, 12)
load commands   : 227 (16 216 bytes)
segments        : 7
fileset entries : 216
```

So the architecture is no longer an inference from a filename. The `cputype`
field was read out of the decompressed Mach-O header: **arm64e**, with the
pointer-authentication ABI bits set in the subtype. The kernel collection
bundles 216 kexts, beginning with `com.apple.kernel`.

What those 216 contain is itself informative:

| Looking for | Found |
|---|---|
| the platform driver | `com.apple.driver.AppleVirtualPlatform` |
| interrupt controller | `com.apple.driver.AppleARMGIC` - the GICv3 driver, exactly as `VMAPPLE.h` declares |
| storage | `com.apple.iokit.AppleVirtIOStorage` |
| **graphics** | **`com.apple.driver.AppleParavirtGPUIOGPUFamily`** |
| anything x86 | **nothing - zero matches** |

The graphics entry is the one that matters and it corrects
[docs/09-emulation-path.md](09-emulation-path.md), which assumed the VM guest
would talk to virtio-gpu. It does not. It talks to **Apple's own
paravirtualised GPU interface**. That cuts both ways: a paravirtualised device
has a defined guest/host protocol rather than silicon to emulate, which is
better than an Apple GPU - but the protocol is Apple's, undocumented, and on a
real Mac the host side is implemented by Virtualization.framework forwarding
into the real Metal driver. Anyone emulating vmapple on x86 would have to
implement that host side themselves. Graphics is not free on this path either;
it is a separate reverse-engineering project.

## Finding 2: every system image is named arm64e

The payload proper, `AssetData/payloadv2/`, is 118 members and 13.96 GiB. The
largest items:

| Member | Size |
|---|---|
| `payloadv2/image_patches/cryptex-system-rosetta` | zip64 sentinel - see below |
| `payloadv2/image_patches/cryptex-system-arm64e` | 1 525 685 858 |
| `payloadv2/basesystem_patches/arm64eBaseSystem.dmg` | 1 186 686 256 |
| `usr/standalone/update/ramdisk/arm64eSURamDisk.dmg` | 213 909 531 |
| `boot/094-19975-168.dmg.aea` | 285 212 672 |

The naming is unambiguous and there is no counterpart anywhere in the listing:
`arm64eBaseSystem.dmg` with no `x86_64BaseSystem.dmg`, `cryptex-system-arm64e`
with no `cryptex-system-x86_64`, `arm64eSURamDisk.dmg` with no x86 ramdisk.

## Finding 3: exactly two x86 binaries, and both are the installer

Decompressing the head of all 1 650 members with content and identifying Mach-O
headers gives **three** binaries directly visible in the whole 16.46 GiB:

```
x86_64+arm64e   12 621 952  .../UpdateBrainService.xpc/Contents/MacOS/UpdateBrainLibrary.dylib
x86_64+arm64       172 752  .../UpdateBrainService.xpc/Contents/MacOS/com.apple.MobileSoftwareUpdate.UpdateBrainService
arm64e           6 027 296  .../BootabilityBundle/Restore/Bootability/BootabilityBrain.framework/Versions/A/BootabilityBrain
```

So there *is* x86_64 code in the macOS 27 installer, which is worth stating
plainly because the simple version of the story says there is none.

But note where it is. Both x86-bearing binaries belong to
`com.apple.MobileSoftwareUpdate.UpdateBrainService` - the software-update
"brain", which is installer and updater infrastructure, and whose own
`version.plist` gives `ProjectName: UpdateBrainAsset`,
`BuildAliasOf: MobileSoftwareUpdate`. It is a shared component of Apple's update
machinery, not part of the operating system being installed. Its being universal
most plausibly reflects a build configuration shared across products; it is not
evidence of Intel support, and nothing else in the package is consistent with
such support.

## Finding 4: the exhaustive x86 hunt

Findings 1-3 look at particular places. This is the sweep: every Mach-O header
this repository can reach anywhere in the package, tallied by architecture.

| Corpus | How it was read | Mach-O | x86 slices |
|---|---|---:|---:|
| Installer app (`Payload`) | pbzx -> XZ -> cpio `odc`, 1 130 members | 20 | **0** |
| `SharedSupport.dmg` zip members | carved and head-decompressed, 1 650 checked | 3 | **2** |
| Inside all 13 kernelcaches | IM4P -> LZFSE -> scan for embedded headers | 4 492 | **0** |
| **Total** | | **4 515** | **2** |

**Of 4 515 Mach-O binaries reachable in macOS 27, exactly two carry x86 code**,
and both are the `UpdateBrainService` components identified in finding 3 -
software-update infrastructure, not the operating system.

The kernel sweep is worth stating separately because it is the strongest form
of the result: 4 492 embedded Mach-O headers across thirteen kernel
collections, and **every single one is arm64e**. Not one x86 header exists
inside any kernel Apple ships in this package.

### The installer app will not launch on an Intel Mac

A specific consequence, because the common assumption is the opposite. It is
widely supposed that `Install macOS 27 Golden Gate Beta.app` opens on an Intel
Mac and then reports the machine as unsupported. It does not open at all: its
twenty Mach-O binaries are arm64 and arm64e only, with no x86 slice anywhere.
An Intel Mac has no code in that bundle it can execute.

Reproduce with:

```bash
python tools/xar_explore.py InstallAssistant_27.0_26A5388g.pkg --extract Payload --out .
python tools/pbzx_cpio.py Payload --json data/gg-installer-app.json
```

## Finding 5: Rosetta is the largest single item in the payload

`AssetData/payloadv2/image_patches/cryptex-system-rosetta` is the biggest member
in the listing. Its local header carries `0xFFFFFFFF` as the uncompressed size,
which is the zip64 sentinel meaning the true size lives in an extra field - so
the exact figure is **[open]** here, but it is larger than 4 GiB.

This closes the loop on [docs/04-apple-x86-artifacts.md](04-apple-x86-artifacts.md):
Apple still ships a great deal of x86 material, and the largest x86 artifact in
macOS 27 is the machinery for running x86 code **on Apple silicon**. Never the
other way.

## What this does not establish

Stated explicitly, because the temptation to over-read a good measurement is the
main risk here:

- **The payload containers were not opened**, so the installed system's
  individual binaries were **not** enumerated. This document cannot claim "zero
  x86 binaries in the installed system" as a measured fact. What it can claim is
  that every system image is named arm64e, no x86 image exists to install, and
  all thirteen kernels are arm64e by header read.

  The blockers are now precise rather than vague, which is worth recording
  because it tells the next person exactly what to attack. Probing the stored
  members in place gives their formats directly:

  | Member | Magic | What it is |
  |---|---|---|
  | `image_patches/cryptex-system-rosetta` | `RIDIFF10` | Apple binary delta |
  | `image_patches/cryptex-system-arm64e` | `RIDIFF10` | Apple binary delta |
  | `basesystem_patches/arm64eBaseSystem.dmg` | `BXDIFF50` | Apple binary delta |
  | `payload.NNN` (×40+) | `pbzm` | chunked container |

  The directory names are literal: `image_patches` and `basesystem_patches` hold
  **patches**, not standalone images, in Apple's undocumented `RIDIFF`/`BXDIFF`
  delta formats.

  `pbzm` is structurally a `pbzx` derivative - same chunked layout, 8 MiB
  chunks, big-endian `[uncompressed][compressed][data]` triples, and the header
  parses cleanly as such (chunk 0: 8 388 608 → 7 258 876 bytes). But the
  per-chunk codec is **not** xz, LZFSE, gzip or zlib; the payload carries no
  magic this survey recognises. Identifying it is the concrete next step for
  anyone wanting a binary census of the installed system. **[open]**
- An earlier revision of this document said 94 members were undecodable because
  of unsupported compression or streamed sizes. That was wrong: a later check
  found **no** members using an unsupported method and **none** streamed without
  a size. Those failures were the survey's own - the head-decompression read was
  capped at 1 MiB of compressed input, so members whose first record exceeded it
  errored out rather than being undecodable in principle. Corrected rather than
  quietly dropped.
- The zip64 sentinel means one size figure above is a lower bound.
- This is a **beta seed**, build `26A5388g`. The release build may differ.

## Why it matters for this repository

Every structural claim made earlier from public sources now has direct
confirmation from shipped bits:

- [docs/07](07-boot-protocol.md) argued the bootloader is finished but has
  nothing to hand off to on x86. Measured: thirteen kernelcaches, no x86 one.
- [docs/04](04-apple-x86-artifacts.md) argued Apple's remaining x86 artifacts
  all point inward. Measured: the biggest one is the Rosetta cryptex.
- [docs/09](09-emulation-path.md) argued VMAPPLE is the tractable emulation
  target. Measured: Apple ships `kernelcache.release.vma2` in the retail
  installer, so the VM platform is a shipping, supported configuration rather
  than a curiosity.

## Reproducing

```bash
python tools/xar_explore.py InstallAssistant_27.0_26A5388g.pkg --json toc.json
# SharedSupport.dmg offset comes from that TOC
python tools/image_arch_scan.py InstallAssistant_27.0_26A5388g.pkg \
    --start 13035914 --length 16958964736 --json arch-scan.json
python tools/zip_carve.py InstallAssistant_27.0_26A5388g.pkg \
    --start 13035914 --length 16958964736 --json members.json --limit 0
```

The package itself is not redistributed here and is not in this repository. Only
measurements are.
