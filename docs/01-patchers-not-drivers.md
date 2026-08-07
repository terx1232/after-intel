# Patchers, not drivers

The headline measurement in this repo is that all 29 Mach-O binaries in the
Hackintosh kext stack are x86-only, with zero arm64 slices. On its own that is a
weak observation — of course nobody built them for ARM, there was no reason to.

The interesting finding is *why* building them for ARM would not have helped,
and it is visible directly in the bundle metadata.

## What the Info.plists say

Read the IOKit personalities. They divide the stack cleanly in two.

### A real driver

```
VoodooPS2Controller.kext
  IOProviderClass : IOACPIPlatformDevice, IOPlatformDevice
  IOClass         : ApplePS2Controller, AppleACPIPS2Nub
```

This matches a real hardware node published by the ACPI platform layer and
provides a controller class that talks to the device. Remove Apple's PS/2
support entirely and this still works, because it *is* the implementation.

### The graphics and audio "drivers"

```
WhateverGreen.kext
  IOProviderClass : IOResources, IOPCIDevice
  IOMatchCategory : IOFramebuffer
  OSBundleLibraries: com.apple.kpi.*, com.apple.iokit.IOPCIFamily

AppleALC.kext
  IOProviderClass : IOResources, IOHDACodecDevice
  IOMatchCategory : ALCUserClientProvider
  OSBundleLibraries: com.apple.kpi.*, com.apple.iokit.IOPCIFamily
```

Two things stand out.

**They match on `IOResources`.** That is not hardware. It is a pseudo-provider
that always exists, and matching against it is the standard trick for "load me
unconditionally at boot". A kext that actually drove a GPU would match the PCI
device and publish an `IOFramebuffer` subclass. WhateverGreen publishes no such
thing — it names `IOFramebuffer` only as a *match category*, so it can slot in
alongside Apple's framebuffer rather than replace it.

**AppleALC's provider is `IOHDACodecDevice`.** That class is published by
Apple's own `AppleHDAController`. AppleALC cannot exist without Apple's audio
stack already running; it attaches to it and supplies the codec configuration
data that Apple ships only for genuine Mac hardware.

**Neither declares any graphics or audio family in `OSBundleLibraries`.** No
`IOGraphicsFamily`, no `IOAudioFamily`, no `AppleHDA`. What they do declare is
`com.apple.kpi.unsupported` — the private kernel interfaces you pull in when you
intend to rewrite other kexts in memory. That is the actual mechanism: Lilu
provides a patching framework, and these plugins use it to modify Apple's real
drivers at runtime.

## Why this settles the question

The stack is not portable to a platform where Apple's drivers do not exist,
because it does not contain drivers. It contains corrections to Apple's drivers.
Recompiling a patch for arm64 gives you a patch with nothing to patch.

This is also why the wall is where it is, and not somewhere softer. On macOS 27
there is no x86 `AppleHDAController` to attach to and no x86 framebuffer to slot
beside. The missing piece is not a build target — it is the several million
lines of closed graphics and audio implementation that the patches were always
sitting on top of.

## The honest counter-argument

VoodooPS2Controller proves the community *can* write a real driver from nothing.
So the objection "they only ever wrote patches" is false, and worth retiring.

The question is what it is a driver *for*. PS/2 is a 1987 interface: two I/O
ports, an 8-bit status register, a documented command set, and a scancode
stream. It is a few thousand lines and it is completely specified in public
documentation that has not changed in nearly forty years.

The distance from that to a Metal-capable GPU driver is the whole problem. For
scale: the Asahi Linux GPU driver for Apple's own hardware took years of
full-time reverse engineering by a specialist, with an open kernel to build
against, freedom to instrument the whole system, and no code-signing in the way.
Producing an equivalent for a closed OS you cannot rebuild, against hardware
whose driver interface Apple never documented, is not the same task scaled up.
It is a different task.

## Reproducing

```bash
python tools/macho_audit.py \
    _downloads/Lilu-*-RELEASE _downloads/WhateverGreen-*-RELEASE \
    _downloads/VirtualSMC-*-RELEASE _downloads/AppleALC-*-RELEASE \
    _downloads/VoodooPS2Controller-*-RELEASE _downloads/BrcmPatchRAM-*-RELEASE \
    --json data/community-kexts.json --entries
```

The Info.plist claims above are read straight from the release bundles of
Lilu 1.7.2, WhateverGreen 1.7.0, AppleALC 1.9.7, VirtualSMC 1.3.7,
VoodooPS2Controller 2.3.7 and BrcmPatchRAM 2.7.2.
