# The bootloader is the solved part

> **Status: [measured].** Produced by `tools/boot_protocol.py` from Apple's
> published XNU source at `xnu-12377.121.6` (macOS 26.5). Raw output in
> `data/boot-protocol.json`.
>
> Self-check: the tool independently computes the x86 `boot_args` at **4096
> bytes**, which is exactly the size XNU's own compile-time assertion enforces
> (`sizeof(boot_args) == 4096`). The extraction agrees with the source.

"Write a new bootloader" is the usual first proposal for getting macOS onto
non-Apple hardware. This document answers the prior question - what does a
bootloader actually have to hand the kernel? - and the answer makes the proposal
look different.

## The handoff, measured

XNU's boot protocol is a plain C struct published in Apple's own source at
`pexpert/pexpert/<arch>/boot.h`. It is not reverse engineered, not
undocumented, not secret.

```
arch             hdr B  fields   core   efi   sec    bytes  asserted
--------------------------------------------------------------------
i386/x86_64       7680      49     22    12    15     4096      4096
arm64             2805      13     13     0     0     1140         -
arm               2684      13     13     0     0      348         -
```

Two things fall out immediately.

## 1. The x86 boot protocol *is* a UEFI protocol

Twelve of the 49 x86 fields exist only because the kernel expects to be launched
by UEFI firmware:

```
efiMode                             MemoryMapDescriptorVersion
MemoryMap                           efiRuntimeServicesPageStart
MemoryMapSize                       efiRuntimeServicesPageCount
MemoryMapDescriptorSize             efiRuntimeServicesVirtualPageStart
efiSystemTable                      pciConfigSpaceBaseAddress
pciConfigSpaceStartBusNumber        pciConfigSpaceEndBusNumber
```

The kernel wants a memory map in EFI memory-type terms, EFI runtime services
already defragmented and mapped at both a physical and a virtual address, and a
pointer to the EFI system table in the runtime area.

The arm64 protocol has **none of this**. Thirteen fields, all core: virtual and
physical base, memory size, a flattened device tree pointer, video, command
line, boot flags. That is iBoot's handoff, and it is EFI-free.

This is the concrete reason OpenCore is a UEFI application rather than a
freestanding loader. It is not a design preference - the x86 XNU entry contract
is written in EFI's vocabulary. Any x86 loader has to be a UEFI application or
provide a complete UEFI environment, which is what OpenDuetPkg does for legacy
BIOS machines.

## 2. The bootloader is inside the boot-security chain

Fifteen of the 49 x86 fields - more than the EFI set - are security state the
loader must supply:

```
csrActiveConfig       csrCapabilities        keyStoreDataStart/Size
apfsDataStart/Size    KC_hdrs_vaddr
arvRootHashStart/Size          arvManifestStart/Size
bsARVRootHashStart/Size        bsARVManifestStart/Size
```

`arv` is Apple Root Verification: the root hash and manifest of the sealed
system volume, passed separately for the system volume and the Base System. The
loader locates these files and hands the kernel their physical addresses. The
sealed-system-volume verification chain therefore *runs through the bootloader*
- it is a participant, not a bystander. `csrActiveConfig` is SIP configuration,
and `apfsDataStart` is the APFS volume key structure.

None of this exists in the arm64 struct, where the equivalent guarantees are
enforced earlier by signed iBoot.

## What this means for "start with the bootloader"

The finding is not what one hopes for, but it is clean:

**The bootloader is the one component of this problem that is completely
finished.** The protocol is published by Apple in full. OpenCore implements it,
correctly, today, and boots macOS 26 Tahoe on non-Apple x86 hardware. There is
no unsolved research problem here and no missing documentation.

Writing a new x86 loader would mean reimplementing a working, documented,
open-source component - and at the end of it, `boot_args` would be handed to a
kernel that, on macOS 27, does not exist for x86. The struct is an interface.
The interface is public and satisfied. What is missing is the implementation on
the far side of it.

This is why [docs/02-hardware-targets.md](02-hardware-targets.md) put the wall
at Metal and not at the boot chain, and the measurement here supports that: 49
fields is a small, closed, fully specified contract, and it has been met for
years.

## The one genuinely open question here

Whether the macOS 27 kernel still *has* an x86 entry path at all - i.e. whether
`pexpert/pexpert/i386/boot.h` and `config/MASTER.x86_64` survive the Golden Gate
source drop - is unanswered, because Apple has not published that source. It is
tracked as the primary open item in [PROGRESS.md](../PROGRESS.md) and
`tools/xnu_arch_check.py` exists to answer it in one command.

If those files are gone, this document describes a protocol with no
implementation behind it on either side.

## Reproducing

```bash
git clone --depth 1 --branch xnu-12377.121.6 \
    https://github.com/apple-oss-distributions/xnu.git _work/xnu-tahoe
python tools/boot_protocol.py _work/xnu-tahoe --json data/boot-protocol.json
```
