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
   **uncompressed** — so it can be read in place at a known offset without
   extracting a copy.
2. That DMG is **UDIF v4** with a `koly` trailer, data fork at +0, 15.79 GiB.
3. A full linear scan for Mach-O headers across all 15.79 GiB found **zero**
   binaries, with only 17 magic hits rejected by header validation across the
   whole image — a near-zero noise floor. Everything is packed.
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
the package — not a stripped one, not a legacy one, none.

The thirteenth is worth its own line: **`vma2`** is the Apple Virtual Machine
platform — the target described in
[docs/09-emulation-path.md](09-emulation-path.md) via XNU's own `VMAPPLE.h`.
Apple ships a kernel for it in the retail installer.

## Finding 2: every system image is named arm64e

The payload proper, `AssetData/payloadv2/`, is 118 members and 13.96 GiB. The
largest items:

| Member | Size |
|---|---|
| `payloadv2/image_patches/cryptex-system-rosetta` | zip64 sentinel — see below |
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
`com.apple.MobileSoftwareUpdate.UpdateBrainService` — the software-update
"brain", which is installer and updater infrastructure, and whose own
`version.plist` gives `ProjectName: UpdateBrainAsset`,
`BuildAliasOf: MobileSoftwareUpdate`. It is a shared component of Apple's update
machinery, not part of the operating system being installed. Its being universal
most plausibly reflects a build configuration shared across products; it is not
evidence of Intel support, and nothing else in the package is consistent with
such support.

## Finding 4: Rosetta is the largest single item in the payload

`AssetData/payloadv2/image_patches/cryptex-system-rosetta` is the biggest member
in the listing. Its local header carries `0xFFFFFFFF` as the uncompressed size,
which is the zip64 sentinel meaning the true size lives in an extra field — so
the exact figure is **[open]** here, but it is larger than 4 GiB.

This closes the loop on [docs/04-apple-x86-artifacts.md](04-apple-x86-artifacts.md):
Apple still ships a great deal of x86 material, and the largest x86 artifact in
macOS 27 is the machinery for running x86 code **on Apple silicon**. Never the
other way.

## What this does not establish

Stated explicitly, because the temptation to over-read a good measurement is the
main risk here:

- **The payload chunks and cryptexes are opaque containers.** `payload.NNN`,
  the cryptexes, `.dmg.aea` (Apple Encrypted Archive) — none were opened. The
  installed system's individual binaries were therefore **not** enumerated, and
  this document cannot claim "zero x86 binaries in the installed system" as a
  measured fact. What it can claim is that every system image in the package is
  named arm64e and no x86 image exists to install.
- **94 members were undecodable** by the carve (unsupported compression or
  streamed sizes) and are unaccounted for.
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
