# Can the published XNU still be built for x86?

> **Status: [verified]** from Apple's own build instructions in
> `README.md` of `xnu-12377.121.6` (macOS 26.5), plus **[measured]** inventory
> of the vendored headers in `data/xnu-external-headers.json`.
>
> **Not reproduced.** No build was attempted - Apple's toolchain requires macOS
> and there is none in this environment. What follows is Apple's documented
> procedure and what it implies, not a build log.

[docs/07-boot-protocol.md](07-boot-protocol.md) established that the boot
contract is public and satisfied. The next question on the porting track is
whether the kernel behind that contract can actually be built from the published
source, or whether Apple withholds pieces that make it unbuildable.

The answer is more favourable than expected, and it contains a genuine surprise.

## The surprise: Intel is the *easier* target

Apple's README gives both build commands. Compare them.

**Intel:**

```sh
make SDKROOT=macosx ARCH_CONFIGS=X86_64 KERNEL_CONFIGS=RELEASE
```

**Apple silicon:**

```sh
make SDKROOT=macosx KDKROOT=${KDK} TARGET_CONFIGS="RELEASE ARM64 T8101"
```

The ARM build needs two things the Intel build does not:

1. **The Kernel Debug Kit.** Apple's README states it plainly: *"This step is
   required for building on Apple silicon. If you are building only for Intel,
   you can skip this step."* The KDK requires an Apple Developer account and
   must match your exact macOS version and build number.
2. **A per-SoC platform identifier** - `T8101` for a MacBookAir10,1, with a
   lookup table of Mac models at the end of the README.

So the open-source kernel is *more* self-sufficient on x86 than on ARM. Building
for Intel needs no account-gated, version-matched binary drop and no per-machine
configuration. This runs against the intuition that the ARM path is the
supported one and the Intel path is the neglected leftover.

## Declared dependencies, and whether they are published

Apple lists four, all obtainable from opensource.apple.com:

| Dependency | Purpose | Published? |
|---|---|---|
| DTrace | CTF tools (`ctfconvert`, `ctfdump`, `ctfmerge`) | yes - and marked *optional* |
| AvailabilityVersions | version macros | yes |
| libdispatch | `libfirehose_kernel` | yes |
| xnu headers | bootstrapped from the tree itself | yes |

Nothing in that list is withheld. This is the part people assume is the
blocker, and it is not.

## The vendored headers, and what they imply

`EXTERNAL_HEADERS/` carries headers copied in from other projects to break
dependency cycles. Inventory:

| Component | Files | Bytes |
|---|---|---|
| (top level) | 15 | 3 016 854 |
| corecrypto | 42 | 345 809 |
| image4 | 21 | 134 741 |
| img4 | 17 | 150 408 |
| architecture | 13 | 41 218 |
| CoreEntitlements | 12 | 49 481 |
| libDER | 11 | 59 469 |
| mach-o | 10 | 132 332 |
| CoreTrust | 2 | 42 550 |
| acpi | 2 | 55 724 |
| sys | 3 | 4 812 |

These are **headers only**. The kernel compiles against them; the
implementations come from elsewhere. Note what they are: `corecrypto`,
`CoreTrust`, `CoreEntitlements`, `image4`/`img4`, `libDER` - cryptography, code
signing, entitlement checking and Image4 secure-boot verification. Whether each
of those has a published implementation is **[open]**; corecrypto is known to be
released, and CoreTrust and image4 are not believed to be, but that was not
verified here.

This matters more for a from-scratch Darwin than for a kernel build: Apple's own
procedure builds successfully because the SDK supplies what the headers declare.

## The gate nobody lists as a dependency

`SDKROOT=macosx` and `xcrun` and `xcodebuild`. **The build requires Xcode, and
Xcode requires macOS.**

That is the actual constraint on this step, and it is a bootstrapping problem
rather than a licensing or availability one: to build Darwin you need a Mac, or
a macOS VM, or a cross-toolchain nobody has assembled. It is not "the source is
missing" - it is "the compiler runs on the thing you are trying to replace."

## What this does and does not mean

**Does:** the x86 kernel is not abandoned source. As of Tahoe it is a
first-class, documented build target with a shorter dependency list than ARM.
For PureDarwin, ravynOS or anyone maintaining an x86 Darwin base, that is real
and it is the good news in this repository.

**Does not:** produce anything resembling macOS. A built kernel is the ~5% of
the system that is open. It has no graphics driver, no WindowServer, no
AppKit, no Metal, and - per
[docs/01-patchers-not-drivers.md](01-patchers-not-drivers.md) - the community
kext stack consists of patches that need Apple's closed drivers to be present
before they do anything. Booting a self-built XNU on a PC gets you a console.

**And the whole thing is conditional on the Golden Gate source drop.** Every
statement above is measured against Tahoe. If `config/MASTER.x86_64` and
`pexpert/pexpert/i386/boot.h` do not survive into the macOS 27 release, this
document describes a capability that ended in 2026.
`tools/xnu_arch_check.py` answers that in one command the day Apple publishes.

## Reproducing the inventory

```bash
python - <<'EOF'
import json, os
eh = "_work/xnu-tahoe/EXTERNAL_HEADERS"
out = {}
for dp, _dn, fn in os.walk(eh):
    if not fn:
        continue
    k = os.path.relpath(dp, eh).split(os.sep)[0]
    d = out.setdefault(k, {"files": 0, "bytes": 0})
    d["files"] += len(fn)
    d["bytes"] += sum(os.path.getsize(os.path.join(dp, f)) for f in fn)
print(json.dumps(out, indent=2))
EOF
```

Build commands and the KDK statement are quoted from `README.md` in the XNU
source tree itself.
