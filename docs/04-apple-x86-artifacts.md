# What x86 material Apple still ships

A reasonable question: Apple distributes various system images and runtimes -
are any of them x86, and does any of it help?

Three candidates, checked. One negative, one genuinely interesting, one ironic.

## 1. macOS VM restore images (IPSW) - Apple silicon only

**[verified] Negative result.**

Apple publishes macOS restore images through a public catalogue at
`https://mesu.apple.com/assets/macos/com_apple_macOSIPSW/com_apple_macOSIPSW.xml`.
These `.ipsw` files are what Virtualization.framework consumes to build a macOS
VM, and they are the closest thing Apple has to an official "here is a macOS
image for a virtual machine".

They are for **Apple silicon Macs only**. The IPSW restore format was never
adopted for Intel Macs, which use the traditional installer and recovery route.
There is no x86 equivalent in that catalogue.

This matches the QEMU `vmapple` situation: that machine model needs
`AVPBooter.vmapple2.bin`, a trimmed `aux.img` and a `disk.img`, all of which can
only be extracted from a running Apple silicon Mac.

## 2. iOS Simulator runtimes - x86_64, and this one is real

**[verified] for the architecture claim. [open] for the contents claim - see below.**

This is the interesting one, and it is under-discussed.

The iOS Simulator is not emulation. A simulator runtime is a native build of
iOS's framework stack compiled for the **host** architecture, running as ordinary
processes on the host macOS kernel. On an Intel Mac, that means Apple compiled
and shipped **x86_64 builds of modern iOS frameworks** - and continued doing so
long after the Apple silicon transition began.

Established: simulator runtimes from iOS 13.7 onward carry both
`x86_64-simulator` and `arm64-simulator` slices, and Intel Macs compile and run
the x86_64 ones exclusively. This is why XCFrameworks must ship a simulator
element containing both architectures.

### Why this is worth something

It is an official, current, Apple-signed corpus of **modern Apple framework
binaries built for x86_64**. For the API archaeology that a compatibility layer
requires - what does the Metal surface actually export, what is the ABI, how are
the objects laid out - that is a legitimate research artifact rather than a
guess. It also demonstrates that Apple's framework sources still build for
x86_64; the constraint on shipping a macOS x86 build is commercial, not
technical.

### Why it is not a system

Being precise, because this is exactly the sort of finding that gets
over-claimed:

- The Simulator is **not a bootable OS**. It runs on the host's XNU, the host's
  WindowServer, and the host's GPU driver. Simulator Metal forwards to the
  host's Metal implementation. It therefore *presupposes* the entire graphics
  stack that is missing - it cannot supply one.
- These are **iOS** frameworks. No AppKit, no Finder, no macOS window server.
- The corpus is **frozen**. macOS 27 is Apple-silicon-only, so Xcode from 27
  onward has no reason to ship x86_64 simulator runtimes at all. What exists is
  what exists, at Tahoe-era Xcode.

### Open question

Whether a shipped x86_64 simulator runtime actually contains a standalone
`Metal.framework` binary - as opposed to a thin forwarding shim into the host -
has **not been verified here**. There is no Mac in this environment. Determining
it requires unpacking a `.simruntime` bundle and running `macho_audit.py` over
it, which is a concrete, cheap experiment for anyone with an Intel Mac or a
Tahoe-era Xcode install. It is queued in [PROGRESS.md](../PROGRESS.md).

## 3. Rosetta for Linux VMs - the wrong direction, officially supported

**[verified].**

Apple currently ships, documents and supports an x86-64 translation engine that
runs *inside Linux VMs* on Apple silicon. It is part of Virtualization.framework,
documented publicly, and used in production by Docker Desktop and OrbStack to run
x86-64 containers on ARM Macs.

So Apple maintains a high-quality, actively supported x86↔ARM translator. It
runs x86 code on ARM hardware - precisely the opposite of what running macOS 27
on a PC would need. There is no Apple-provided ARM→x86 path, and Apple has said
Golden Gate is the last release with full Rosetta support at all.

## Summary

| Artifact | x86? | Bootable OS? | Useful how |
|---|---|---|---|
| macOS IPSW VM images | no - ARM only | yes, on ARM | not at all here |
| iOS Simulator runtimes | **yes, x86_64** | no | research corpus for API/ABI archaeology |
| Rosetta for Linux VMs | x86 guest on ARM host | n/a | wrong direction |

The pattern is consistent: Apple still produces x86 artifacts, but every one of
them either runs *on* a Mac or runs x86 code *on* Apple silicon. Nothing points
outward to non-Apple hardware, which is the whole design intent.

## Sources

- [Downloading macOS IPSW files for Mac VMs - Der Flounder](https://derflounder.wordpress.com/2022/11/17/downloading-macos-ipsw-files-for-use-with-mac-virtual-machines-on-apple-silicon-macs/)
- [Both ios-arm64-simulator and ios-x86_64-simulator - Apple Developer Forums](https://developer.apple.com/forums/thread/666335)
- [Compiling for iOS on Apple M1 - Mercari Engineering](https://engineering.mercari.com/en/blog/entry/20211129-compiling-for-ios-on-apple-m1/)
- [Running Intel Binaries in Linux VMs with Rosetta - Apple Developer Documentation](https://developer.apple.com/documentation/Virtualization/running-intel-binaries-in-linux-vms-with-rosetta)
- [VMApple machine emulation - QEMU documentation](https://www.qemu.org/docs/master/system/arm/vmapple.html)
