# Work log and queue

Running record of what has been established, what is in progress, and what is
queued. Every claim in this repository is tagged with how it was arrived at:

- **[measured]** - produced by a tool in `tools/`, output committed to `data/`
- **[verified]** - read directly from a primary source (Apple source tree,
  shipped bundle metadata, official documentation)
- **[literature]** - taken from published third-party reverse engineering, not
  independently reproduced here
- **[open]** - not established; stated as a question, not an answer

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
| 12 | Metal tracks hazards automatically by default; Vulkan requires explicit barriers. Metal→Vulkan must therefore synthesise a per-resource tracker that the API surface count does not show - a subsystem independently reported as the hottest code in a comparable project | [literature] `docs/06-metal-vulkan-divergence.md` |
| 13 | MoltenVK's documented limitations amount to four narrow bullets, so Vulkan→Metal is effectively solved - which is why citing it as evidence for the reverse is a category error | [verified] MoltenVK user guide |

| 14 | XNU's x86 boot handoff is 49 fields / exactly 4096 bytes: 12 EFI-dependent, 15 boot-security. arm64 is 13 fields, no EFI, no security state. The x86 entry contract is written in EFI's vocabulary, which is why the loader must be a UEFI application | [measured] `data/boot-protocol.json` |
| 15 | The bootloader participates in the sealed-system-volume chain: it supplies the ARV root hash and manifest for both the system volume and Base System, plus the APFS volume key and SIP configuration | [verified] `pexpert/pexpert/i386/boot.h` |

| 16 | Building XNU for Intel needs no Kernel Debug Kit; building for Apple silicon does, plus a per-SoC platform identifier. Apple's README states this outright. The open-source kernel is *more* self-sufficient on x86 than on ARM | [verified] XNU `README.md` |
| 17 | All four declared XNU build dependencies (DTrace, AvailabilityVersions, libdispatch, xnu headers) are published; DTrace is marked optional. The real gate is that the build needs Xcode, i.e. a Mac | [verified] XNU `README.md` |
| 18 | Apple's VM platform (VMAPPLE) uses standard GICv3 and PL011 rather than Apple's AIC and custom UART, and paravirtualises PAC and CTRR with no secure monitor. It is a far cleaner emulation target than real Apple silicon | [verified] `pexpert/pexpert/arm64/VMAPPLE.h` |
| 19 | Emulating a weak-ordered ARM guest on a strongly-ordered x86 host is the favourable direction for memory ordering; no hardware assist is needed, unlike x86-on-ARM which required Apple to add a TSO mode | [verified] architecture semantics |
| 20 | macOS 27 beta `26A5388g` ships 13 kernelcaches, 12 for Apple silicon Mac platforms and one (`vma2`) for the Apple Virtual Machine platform. There is no x86 kernelcache | [measured] `data/gg-zip-members.json` |
| 21 | Every system image in the package is named arm64e - `arm64eBaseSystem.dmg`, `cryptex-system-arm64e`, `arm64eSURamDisk.dmg` - with no x86 counterpart anywhere in 1 842 members | [measured] same |
| 22 | Exactly 3 Mach-O binaries are directly visible in the 16.46 GiB payload; the only two carrying x86_64 slices both belong to `UpdateBrainService`, i.e. update infrastructure rather than the installed system | [measured] `data/gg-member-archs.json` |
| 23 | The largest single item in the payload is `cryptex-system-rosetta` - the x86-on-ARM translation runtime. Apple's biggest x86 artifact in macOS 27 points inward, as every other one does | [measured] same |
| 24 | `kernelcache.release.vma2` unwrapped: IM4P + LZFSE, 23 085 403 → 80 871 424 bytes, **arm64e** (cputype `0x0100000c`, PTRAUTH subtype), MH_FILESET with 216 bundled kexts. Architecture read from the header, not inferred from the name | [measured] `data/gg-vma2-kernel.json` |
| 25 | The VM kernel's kexts include `AppleVirtualPlatform`, `AppleARMGIC` (confirming `VMAPPLE.h`), `AppleVirtIOStorage`, and **`AppleParavirtGPUIOGPUFamily`** - so VM graphics is Apple's own paravirtual GPU protocol, not virtio-gpu. Zero x86-related kexts | [measured] same |
| 26 | All **13 of 13** kernelcaches unwrapped and read: every one is arm64e and `MH_FILESET`. Mac platforms carry 342-370 kexts in 119-126 MB; `vma2` carries 216 in 81 MB. Finding #20 no longer rests on filenames | [measured] `data/gg-kernelcaches.json` |
| 27 | The payload containers are named formats, not mystery blobs: `RIDIFF10` and `BXDIFF50` are Apple binary deltas (hence the `*_patches/` directory names), and `payload.NNN` are `pbzm` - a `pbzx`-derived chunked container whose header parses cleanly but whose per-chunk codec is not xz, LZFSE, gzip or zlib | [measured] probe in place |

| 28 | Exhaustive sweep: **4 515 Mach-O binaries** are reachable across the whole package and exactly **2** carry x86 code, both in `UpdateBrainService`. The 13 kernels contain 4 492 embedded Mach-O headers and **every one is arm64e** | [measured] `data/gg-installer-app.json` + kernel sweep |
| 29 | `Install macOS 27 Golden Gate Beta.app` is arm64/arm64e only across all 20 of its binaries, so it does **not** launch on an Intel Mac and report incompatibility - it cannot start at all | [measured] `data/gg-installer-app.json` |
| 30 | The vma2 kernel's declared virtual span equals its file size exactly, so the collection maps 1:1 and a loader can place it as one contiguous blob. Entry point `0xfffffe0009e3c480`, virtBase `0xfffffe0007004000` | [measured] `data/vma2-loadmap.json` |
| 31 | Device tree node names are recoverable from the kernel's own `__PRELINK_INFO`; property names are recoverable from driver cstring sections, but unevenly - `AppleARMPlatform` yields 258, `AppleVirtualPlatform` 35, `AppleARMGIC` **zero** | [measured] `data/vma2-*-strings.json` |

| 32 | An early XNU panic prints **nothing**: it says so itself, in `"Kernel panicked very early before serial init, spinning forever..."`. It formats the real message into a stack buffer and calls a shared halt routine, so an empty serial log plus a fixed PC is a panic, not a hang. The message survives at the halt and can be read out of a `pmemsave` dump | [measured] read from guest memory |
| 33 | Return addresses on the guest stack are PAC-signed and the signature reaches **below bit 48**, so masking to 48 bits still leaves garbage. Keeping 40 bits recovers a frame chain that resolves cleanly | [measured] frame walk over the dump |
| 34 | `pe_identify_machine` returns before assigning any defaults if `pe_arm_get_soc_base_phys()` is zero, and that reads the **second** cell of `arm-io`'s `ranges`. A wrong `ranges` therefore leaves every clock at zero, and the kernel dies far away in `_enable_timebase_event_stream` with `invalid bit index (4294967294)` - which is `flsll(0) - 1` decremented once more | [verified] against xnu source + reproduced |
| 35 | The minimum this kernel demands of a device tree before it will leave early boot: `arm-io` with non-zero `ranges[1]` and a `device_type`; `/cpus/cpuN` with `state` as the **string** `"running"` and a `timebase-frequency`; `/chosen/random-seed` of **256** bytes; and a `chosen/memory-map` node, whose absence is only an `assert` and so goes unchecked in a release kernel | [measured] each one found by fixing the previous panic |

## Stage 5 - PASSED

**Root cause, one field.** `boot_args.deviceTreeP` must be a **virtual**
address. We were passing a physical one. XNU copies it into
`PE_state.deviceTreeHead`, `arm_vm_init` assigns
`segEXTRADATA = (vm_offset_t)PE_state.deviceTreeHead` and lets that become
`segLOWEST`, then `arm_vm_physmap_slide` computes `segLOWEST - gVirtBase` as a
length:

    0x4be04000 - 0xfffffe0000000000 = 0x2004be04000   (mod 2^64) = 2.00 TiB

A 2 TiB granular walk starting inside level 1 entry 0x7DF steps up through 0x7E0
and into 0x7E1, which is never built, whose empty descriptor masks to zero and
reaches `phystokv` as `illegal PA: 0x0`. Measured, not inferred: freezing the
call at 0xa00cb24 read x1 = 0x2004be04000 before the fix and x1 = 0x7004000
after, the latter being exactly gVirtBase to the kernel's link base.

`2 << 40` is VM_MIN_KERNEL_ADDRESS, so the `0x200` that kept appearing in the
high bits of unrelated-looking values all through this investigation - and which
was twice dismissed as a tagged pointer - was the top of that wrap pointing
straight at the cause.

**Second fix, needed to get past serial init.** `pe_serial.c:831` panics
unconditionally if there is no `defaults` device tree node. Added.

**Where the boot is now.** Past `arm_vm_init`, past the `defaults` lookup, into
serial init. The panic changed from a silent halt to XNU's exception report
(`"%s at pc 0x%016llx, lr 0x%016llx (saved state: %p%s)"` with a register dump),
so the kernel is now trying to describe its own failure rather than spinning.

Exceptions captured with `-d int`:

    Hypervisor Call, handled as PSCI                        expected
    Undefined Instruction, ESR 0x0, ELR 0xfffffe0009e92dc0  <- the blocker
    Data Abort, ESR 0x96000045, FAR 0xb1

The instruction at 0xfffffe0009e92dc0 is `0xe7ffdeff`, and it is present in
Apple's **unmodified** kernel - verified against `vma2.kernel`, not just the
patched build. QEMU's `-cpu max` does not decode it. Whether it is an
undocumented Apple instruction or a poison value that should never be reached is
the next question, and the two lead to very different work.

---

## Stage 5 - the investigation, kept for method

Everything below in "In progress" is a chronological log with several claims
that were later retracted. Read this summary before it, not after.

**Where the boot stops.** `phystokv: illegal PA: 0x0`, printed by nothing
because it happens before serial init, then a shared halt routine spins. It
presents as a silent hang with an empty log.

**The failing chain, every value measured in one frozen guest:**

    0xa00c9e4 -> 0xa00cb24 -> 0xa0098e0 -> 0xa009a1c -> phystokv(0)

    x24 = 0xfffffe1000000000   the walked address, = KERNEL_PMAP_HEAP_RANGE_START
    x26 = 0x7E1               its level 1 index
    x25 = 0                   the entry read: it does not exist
    x0  = 0                   entry & bits[47:12], the rejected argument

`KERNEL_PMAP_HEAP_RANGE_START` is `VM_MIN_KERNEL_AND_KEXT_ADDRESS +
ARM_TT_L1_SIZE`, i.e. gVirtBase + 64 GiB (pmap.h:252, in the branch commented
"for large memory systems with no KTRR/CTRR such as virtual machines").

**The defect, with nothing inferred:** a non-allocating walk over the heap
level 1 range, whose tables have not been built yet.

**Verified correct, so do not re-investigate:** virtBase (equals
VM_MIN_KERNEL_ADDRESS), physBase, memSize, the device tree, the 19 hypercall
answers, both populated level 1 entries (0x7DF and 0x7E0), and the physical
aperture (128 blocks of 32 MiB = exactly 4 GiB from gPhysBase).

**Retracted below, do not rebuild on any of these:** that the walked address is
below the aperture; that it comes from x2 (it is x24 - the `ubfx` reads x24);
that the argument is `avail_start`; that `avail_start` being unset is the cause
(it is a consequence); that the slide is deterministic across runs; that
`ptov_table` or `chosen/memory-map` are involved; that the region around
0xa00ca50 is dead code.

**Apparatus, four faults found and fixed. Use `dis.ps1` and `cond_trap.py`:**

1. Registers read at the halt are meaningless - scratch registers are clobbered
   by the whole panic path. Freeze at the instruction instead.
2. `-d` logging starves the guest under TCG; the freeze is not reached inside
   the wait. No `-d` when reading registers.
3. Stale QEMU processes hold the fixed monitor port and answer instead of the
   new guest. Kill them first.
4. A 256 MiB `pmemsave` does not finish before the script kills QEMU, leaving
   the previous run's file. Poll the size to completion.

Also: `-d in_asm` logs blocks as *translated*, not each time they execute, so a
block's presence never proves it ran on a given pass. And nothing may be
compared across runs: the aperture slide differs every boot.

**CONFIRMED AND ROOT-CAUSED.** Freezing the call at 0xa00cb24 and reading the
arguments to the granular walk:

    x00 = 0xfffffdf01c000000    start, inside the aperture (L1 0x7DF)
    x01 = 0x2004be04000         length: 2.00 TiB
    x02 = 0xfffffff01c000000    pa_offset, negative as expected

A 2 TiB walk starting in 0x7DF steps up through 0x7E0 and into the unmapped
0x7E1, which is exactly the observed failure. The runaway loop is real.

And the length decomposes exactly:

    0x2004be04000 = 0x4be04000 - 0xfffffe0000000000   (mod 2^64)
                    ^ our device tree  ^ gVirtBase = VM_MIN_KERNEL_ADDRESS

`2 << 40` is VM_MIN_KERNEL_ADDRESS itself, so this is `segLOWEST - gVirtBase`
with `segLOWEST` holding the **physical** address of our device tree.

The path: we put a physical address in `boot_args.deviceTreeP`; XNU copies it to
`PE_state.deviceTreeHead`; `arm_vm_init` assigns
`segEXTRADATA = (vm_offset_t)PE_state.deviceTreeHead` and lets that become
`segLOWEST`; then `arm_vm_physmap_slide(temp_ptov_table, gVirtBase,
segLOWEST - gVirtBase, ...)` subtracts a virtual base from a physical address.

So the defect is ours, in the loader, and it is a physical-versus-virtual
mix-up in one field. Everything the kernel did with it was correct.

Note this also explains the 0x200 that kept appearing in the upper bits of
values through this whole investigation and was dismissed twice as a tagged
pointer: it is the top of `2 << 40` surviving the wrap.

**Superseded hypothesis, kept for the reasoning:** A runaway loop. If
the `size` passed to `arm_vm_page_granular_prot` is far too large, then
`while (align_start < align_end)` steps upward through level 1 entries, crosses
0x7DF (the aperture) and 0x7E0 (the kernel), reaches 0x7E1 which is unmapped,
and panics. This is the only reading so far that explains why the *first* call
succeeds and a later iteration fails, without needing anything else to be wrong.

Candidate source: `real_avail_end - args->topOfKernelData` at the second
`arm_vm_physmap_slide` call. A previously measured x9 of 0x2004be04000, about
128 GiB, is the right order of magnitude for a length that would walk that far.

Test it first, and test it by measurement: freeze at the call into
0xa0098e0 and read x0, x1, x2 (start, length, pa_offset). A length near 128 GiB
confirms it; a length near 4 GiB kills it. Do not reason further about it before
that number is in hand.

**Then, if the hypothesis dies.** Locate `init_ptpages` in the binary, freeze its call for the heap
range, and establish whether it runs before the failing walk. Locate it, do not
assume it - assuming produced every wrong turn above.

---
## In progress

**Track: booting the shipped kernel far enough to learn from it.**

- **`phystokv: illegal PA: 0x0` in `arm_vm_init`.** Where the boot now stops.
  The frame chain puts the caller at a `phystokv(tte & ARM_TTE_TABLE_MASK)`,
  so a translation table entry is empty during a page table walk. Unlike
  findings #34 and #35 this is not a missing property, and supplying one will
  not fix it; the question is which mapping the kernel expects to exist by that
  point. Running the **unpatched** kernel against the same fixed tree settles
  where this comes from: it does not reach `arm_vm_init` at all, but spins at
  `movz x0, #0xC1000000; hvc #0; cbnz x0, .` with x0 = -1, because QEMU answers
  unknown SMCCC calls with -1 per SMCCC 1.3.

  So the three workarounds in this build form a chain, and each one pays for
  the one before it: stubbing the paravirtual hypercalls gets past that spin
  but leaves the pointers they were supposed to return still null; the two
  `null_guard` diversions stop the resulting data abort but skip the work those
  routines were doing; and the skipped work is what leaves a translation table
  entry empty. `phystokv: illegal PA: 0x0` is the bill for all of it.

  **Done** - `hvc_impl.py` answers the 19 checker sites with `movz x0, #0`, and
  the unmodified kernel then reaches the same place the triple-workaround build
  reached, with all three workarounds gone. The 21 consumer sites are left
  failing honestly; their return values are not knowable from this side and all
  of them run at IOKit matching time, not in early boot.

  What remains at `phystokv: illegal PA: 0x0` is now located to the
  instruction. The failing call is

      ldr  x8, [x8, #0x1d0]        ; translation table root, from a global
      lsr  x9, <vaddr>, #36        ; level 1 index
      ldr  x8, [x8, x9, lsl #3]    ; l1_tte = root[index]
      and  x0, x8, #<mask>         ; l1_tte & ARM_TTE_TABLE_MASK
      bl   phystokv                ; <- zero

  with **no** preceding `if (l1_tte == ARM_TTE_EMPTY) { alloc_ptpage(); }`. So
  this is not the allocating walker at arm_vm_init.c:629-639 but the one that
  assumes the entry exists (:737, :752). The level 1 entry is empty, meaning
  the virtual address being walked is not covered by the boot page tables.

  **Correction.** An earlier note here read x8 and x9 out of a register dump
  taken at the halt and concluded the level 1 index was zero. Those are scratch
  registers and the whole panic path runs between the failing instruction and
  the halt, so they were clobbered; the conclusion was built on garbage.
  Trapping *at* the call instead - replacing the `bl` with `b .` so the CPU
  freezes with registers intact - gives the real state, and the index is
  `0x7E0`, exactly what the address implies.

  What that trap then showed: the level 1 table at `0xfffffe000781c000` had
  **one** non-empty entry out of 2048, at index `0x7df`, while the walk needed
  `0x7E0`. Each entry at that level covers 64 GiB, and the boundary between
  those two falls at `0xfffffe0000000000`. Separating physBase from the load
  address had moved virtBase to `0xfffffdfffe000000`, just below that line,
  while the kernel sits just above it - so virtBase and the kernel landed in
  different level 1 entries and XNU's early tables only populate one.

  That was self-inflicted, and it means the earlier claim that the panic
  "predates the change" was stated too confidently: the message matched, but
  the cause for this layout is now established and the cause before it is not.

  Constraining the load offset to at most `0x7004000` puts virtBase back in the
  same entry as the kernel (`--phys-base 0x47004000 --ram-base 0x40000000`
  gives virtBase `0xfffffe0000000000`, index `0x7E0` for both) while keeping
  physBase at the true base of RAM. The first walk then succeeds: the entry
  reads `0x2000000047820003` instead of zero.

  The panic persists, and freezing inside `phystokv` itself - replacing its
  `bl panic` at 0xa008d84 with `b .` so registers survive - shows it comes from
  a **different** call site: x30 unstrips to 0xfffffe000a009a20, so the call is
  at 0xa009a1c in function 0xa0098e0, not the 0xa009bec that was trapped
  before.

  The address being walked is measured, not inferred: `0xfffffdf038000000`,
  carried in x1 and x2. Against `gVirtBase = 0xfffffe0000000000` that is

      gVirtBase - 0xfc8000000

  and `0xfc8000000` is exactly what x20 holds. So the kernel is walking an
  address **63 GiB below virtBase** on a machine with 4 GiB of RAM. Nearby
  registers are the same shape: x25 = 0x2008000000, x24 = gVirtBase + 64 GiB,
  x21 = 0xfffffff038000000, and x26 = 0xfffffffffe000000 = -x23 with
  x23 = 0x2000000.

  This is no longer a missing mapping. An address that far outside RAM comes
  from a computation producing an impossible value, and one wrong input was
  found: `build_image` handed the device tree the load address while boot_args
  got the true RAM base, so the tree claimed DRAM ran from the image for the
  full memory size, past the real end of RAM. Fixed.

  **State after that fix, measured three ways and not yet explained:**

  * Serial output is **zero bytes**. The kernel does not reach serial init, so
    the stage is not complete. This is the decisive test, because the early
    panic path announces itself with "Kernel panicked very early before serial
    init, spinning forever..." - any bytes at all would mean we were past it.
  * The panic is **unchanged**. Freezing all five `bl` sites into the halt
    routine with `b .` shows PC resting at 0xfffffe0009e91e60, the one site
    that prints, and the format string it was handed - x19, saved from the
    first argument at entry - reads
    `"%s: illegal PA: 0x%llx; phys base 0x%llx, size 0x%llx @%s:%d"`.
    Still phystokv.

  A note here previously said the `illegal PA` message was gone because a
  search over 256 MB of dumped RAM found no panic text written at runtime.
  That was wrong: the dump was taken before the text had been formatted, so
  its absence said nothing about whether the panic had changed. Reading the
  format string out of the frozen frame settles it directly and shows it had
  not.

  **The addresses being walked lie below gVirtBase.** Freezing the failing call
  itself - `b .` at 0xa009a1c, rather than at the panic or at a neighbouring
  site, which is what earlier attempts got wrong - gives registers that relate
  exactly:

      x20 = 0xff2000000                     (64 GiB - 224 MiB)
      x01 = 0xfffffdf00e000000 = gVirtBase - x20

  That matters because `phystokv(pa) = pa - gPhysBase + gVirtBase`, so any
  valid physical address produces a virtual address **at or above** gVirtBase.
  An address below it cannot have come from phystokv, and it lands in level 1
  entry 0x7DF - the one immediately below the kernel's own 0x7E0, and the one
  that has no table.

  A first reading of that was "the kernel wants virtual space beneath gVirtBase
  and we gave it none". Tested and **wrong**: lowering virtBase as far as
  QEMU's dtb allows, loading at 0x40100000 to leave 0x6f04000 of space
  underneath, does not change the halt.

  The magnitude points somewhere better. Rewrite the address as

      gVirtBase - 0xff2000000  =  (gVirtBase + 0xE000000) - 0x1000000000

  and `gVirtBase + 0xE000000` is a perfectly ordinary kernel address.
  `0x1000000000` is `1 << 36`, and 36 is exactly the level 1 index shift for
  this granule.

  **The arithmetic is now read, not guessed.** At 0xa0099a0 the walker does

      cb1503f4    sub  x20, xzr, x21

  Register 31 in a shifted-register `sub` is XZR, not SP, so that is a
  negation: `x20 = -x21`. And x21 is the function's second argument, saved by
  `mov x21, x2` at 0xa00992c. The measured values agree exactly:
  `-0xfffffff00e000000 = 0xff2000000`.

  So the walked address is `gVirtBase + x2`, and at the failing call
  `x2 = 0xfffffff00e000000`, which as a signed value is **-0xFF2000000**, about
  -63.8 GiB. The second argument is negative. Some caller computed a size or
  offset by subtracting and went below zero.

  **Located.** The walker has 37 callers. Thirty-six of them pass `movz x2, #0`.
  Exactly one computes it:

      0xa00cb08   cb010102   sub  x2, x8, x1      ; the size argument
      0xa00cb0c   aa0803e0   mov  x0, x8          ; the start
      0xa00cb10   aa0903e1   mov  x1, x9
      0xa00cb24   97fff36f   bl   0xa0098e0

  so the call is `f(x8, x9, x8 - x1_old, ...)` and the third operand is a
  length. The measured result is -0xFF2000000, meaning x1 exceeds x8 by
  63.8 GiB, and a length computed as `start - end` rather than `end - start`
  is exactly the shape that produces it.

  This is the whole chain, end to end: a length that comes out negative, added
  to gVirtBase inside the walker after `sub x20, xzr, x21` negates it, giving a
  virtual address roughly one level 1 entry below the kernel, in the table
  entry that has nothing in it, whose empty descriptor masks to zero and
  reaches phystokv as `illegal PA: 0x0`.

  Freezing just after the subtraction, at 0xa00cb0c, where both endpoints are
  still live, gives them:

      x01 = 0xfffffe0000000000     the end   - exactly gVirtBase
      x08 = 0xfffffdf016000000     the start - already below gVirtBase
      x02 = 0xfffffff016000000     the difference, negative

  So the subtraction is not the defect. It computes `start - end` correctly for
  the values it is given, and **x8 arrives already wrong**: a start below the
  base of the kernel's virtual space, which nothing legitimate produces.

  x09 at the same instant is `0x2004be04000`. Its low 32 bits, `0x4be04000`,
  are the physical address of **our own device tree** for this build, with
  `0x200` sitting in the bits above. That is a pointer carrying something in
  its upper bits that does not belong there, and it is the first appearance of
  one of our own placed addresses inside this computation.

  The `chosen/memory-map` node was the first suspicion, since it had been added
  empty and real firmware fills it with `DTMemoryMapRange` entries describing
  the device tree and boot args. Filling it properly - `build_image` now writes
  both entries once the placements are known, and checks the tree did not
  change size - **does not affect this at all**: x2 reads `0xfffffff016000000`
  with the entries present, byte for byte what it read with the node empty, and
  serial output is still zero.

  The fill is kept because supplying those ranges is correct on its own terms,
  but it is not this bug. x8 does not derive from the memory map.

  **The bad value is stored, not computed.** Tracing writes to x8 in the
  caller leads to

      0xa00ca90   adrp x8, 0xfffffe0007925000
      0xa00ca94   ldr  x8, [x8, #0x920]

  and reading that global out of guest memory, alongside two neighbours whose
  identity is certain from their contents:

      [0xfffffe0007960000] = 0x40000000            gPhysBase
      [0xfffffe000795c2f8] = 0xfffffe0000000000    gVirtBase
      [0xfffffe0007925920] = 0xfffffdf0375ac000    below gVirtBase

  So a global variable is holding a virtual address roughly 63.8 GiB below the
  base of kernel virtual space, and everything downstream - the negative
  length, the negation, the empty level 1 entry, `illegal PA: 0x0` - follows
  from reading it. The defect is wherever that global is written, which is
  earlier in boot than anything examined so far.

  This also disposes of the `0x200` in x9 as a lead: x9 is loaded from
  `[0xfffffe0007960000]`, which holds a clean `0x40000000`, so the value seen
  in the register at the freeze was from a later reload and not the input to
  this computation.

  **The global has exactly one writer, and it settles the stage.** Resolving
  every `adrp` to that page and checking the accesses through it: eleven loads,
  one store, at 0xa00a090. The value stored is built immediately before it:

      0xa00a080   movz x9, #0xfdf000000000
      0xa00a084   movk x9, #0xffff000000000000     ; x9 = 0xfffffdf000000000
      0xa00a088   sub  x8, x9, x8
      0xa00a090   str  x8, [x21, #0x920]

  `0xfffffdf000000000` is a **constant compiled into the kernel**, assembled
  from immediates. It is not anything this port supplies, and it cannot be
  changed by a loader.

  And it is the whole answer to the empty entry:

      (0xfffffdf000000000 >> 36) & 0x7FF  =  0x7DF

  which is precisely the level 1 entry that was found empty, sitting one below
  the kernel's own 0x7E0. So the kernel has a fixed virtual region a terabyte
  below where our `gVirtBase` puts it, expects that region to be mapped, and
  reaches it through the walker that does *not* allocate.

  **Named, from the source.** `arm_vm_init.c:1857`:

      unsigned long physmap_l1_entries =
          ((real_phys_size + ARM64_PHYSMAP_SLIDE_RANGE) >> ARM_TT_L1_SHIFT) + 1;
      physmap_base = VM_MIN_KERNEL_ADDRESS - (physmap_l1_entries << ARM_TT_L1_SHIFT);
      ...
      physmap_base += physmap_slide;      // early_random()

  which is exactly the `sub x8, x9, x8` and the store. So:

  * the constant `0xfffffdf000000000` is **VM_MIN_KERNEL_ADDRESS**;
  * the global at 0x7925920 is **physmap_base**, the physical aperture;
  * this build has **ARM_LARGE_MEMORY** enabled, so the aperture is placed
    below VM_MIN_KERNEL_ADDRESS rather than at `phystokv(topOfKernelData)`;
  * the measured `0xfffffdf0375ac000` is VM_MIN_KERNEL_ADDRESS plus a random
    slide of 0x375ac000, which makes it a **correct** value, not a corrupt one.

  So the address was never wrong. It is below *our* gVirtBase, and that is the
  defect: we set gVirtBase to 0xfffffe0000000000, a terabyte **above**
  VM_MIN_KERNEL_ADDRESS. The kernel lays its virtual world out downward from
  VM_MIN_KERNEL_ADDRESS, so anything it computes there falls beneath a base we
  placed too high, into a level 1 entry nobody made.

  Every earlier hypothesis failed because each one assumed we had passed a
  wrong value. We had not. We had passed a wrong *base*, and every value
  derived from it looked wrong in consequence.

  **Caveat, and it is a real one.** The identification rests on the constant
  matching and the instruction sequence matching, but the arithmetic does not
  reconcile. With `real_phys_size` of 4 GiB, `physmap_l1_entries` is at least 1,
  so `physmap_base` must land at least 64 GiB *below* VM_MIN_KERNEL_ADDRESS.
  The measured value, 0xfffffdf0375ac000, is 0x375ac000 *above* it. Those agree
  only if `physmap_l1_entries` were 0, which
  `((size + SLIDE_RANGE) >> ARM_TT_L1_SHIFT) + 1` cannot produce.

  **Reconciled, and it inverts the conclusion.** Two constants settle it:

      VM_MIN_KERNEL_ADDRESS     = (0ULL - (2ULL << 40)) = 0xfffffe0000000000
      ARM64_PHYSMAP_SLIDE_RANGE = 1ULL << 30            = 1 GiB

  So `0xfffffdf000000000` in the instruction stream is not
  VM_MIN_KERNEL_ADDRESS itself. It is `VM_MIN_KERNEL_ADDRESS - (1 << 36)`,
  folded by the compiler because `physmap_l1_entries` is 1 for this memory
  size. Then:

      physmap_l1_entries = ((4 GiB + 1 GiB) >> 36) + 1 = 1
      physmap_base       = 0xfffffe0000000000 - 64 GiB = 0xfffffdf000000000
                         + slide 0x375ac000            = 0xfffffdf0375ac000

  which is the measured value exactly, and the slide is inside its 1 GiB range.

  Therefore **physmap_base is correct, and so is our virtBase**: we set it to
  0xfffffe0000000000, which *is* VM_MIN_KERNEL_ADDRESS, not a terabyte above
  it. The previous entry here claimed the opposite and was wrong - it read the
  folded constant as the unfolded one.

  What is actually true is narrower and better. The kernel legitimately places
  its physical aperture 64 GiB below VM_MIN_KERNEL_ADDRESS, in level 1 entry
  0x7DF, and walks it with the non-allocating walker. XNU creates those tables
  in `init_ptpages(cpu_tte, physmap_base, ROUND_L1(physmap_end), ...)`. So the
  question is no longer what value is wrong - none of them are - but why that
  entry is absent from the table being walked at the moment it is walked.

  **It is not absent.** Reading the root table out of guest memory after the
  load-offset fix:

      root = 0xfffffe000781c000
      [0x7df] = 0x3800000047824003     the physical aperture
      [0x7e0] = 0x2000000047820003     the kernel

  Both level 1 entries exist, and `init_ptpages` at arm_vm_init.c:1982 runs
  before the segment work that leads to the failing call. So the level 1 story
  is finished, and the load-offset fix finished it.

  The remaining failure is **deeper in the walk** - a hole at level 2 or 3
  inside the table at 0x47824000, reached by the walker that does not allocate.
  init_ptpages builds only level 1 pages, by its own comment; the levels below
  are filled by whoever maps the aperture, through the *allocating* walker at
  arm_vm_init.c:629-639.

  **The hole is located, and the aperture itself is correct.** The level 2
  table at 0x47824000 holds 128 non-empty entries at indices 0x1C through 0x9B.
  128 blocks of 32 MiB is exactly 4 GiB, and `[0x1C] = 0x60000040000601` is a
  block descriptor for physical 0x40000000, i.e. gPhysBase. So the physical
  aperture is mapped fully and correctly.

  The failing address, 0xfffffdf016000000, has level 2 index **0xB** - below
  the mapped range, not inside a gap in it. And it sits below `physmap_base`
  (0xfffffdf0375ac000) by 0x215ac000.

  The relationship that matters:

      physmap_base - slide = 0xfffffdf000000000
      failing address      = 0xfffffdf000000000 + 0x16000000

  So the address is computed from the **unslid** aperture base while the
  aperture was mapped at the **slid** one. `physmap_slide` comes from
  `early_random()`, and something is reading the base from before
  `physmap_base += physmap_slide` was applied.

  That reading was tested and **does not hold up as stated**. Patching
  `mov x9, x0` at 0xa00a068 to `mov x9, xzr`, on the theory that x0 carried the
  random contribution, left the slide in place: physmap_base came back as
  0xfffffdf02d708000, still offset, so that instruction is not where the
  randomness enters.

  More important, the slide **differs between boots** - 0x375ac000 on one run,
  0x2d708000 on the next. That confirms `early_random()` is live, and it
  undermines the arithmetic above: the failing address and physmap_base were
  each measured once, in *different* runs, so the tidy relationship
  `failing = physmap_base - slide + 0x16000000` may be an artifact of comparing
  two boots with two different slides.

  **That correction was itself wrong.** Re-measuring physmap_base on a second
  run of the same build returns `0xfffffdf02d708000` byte for byte. The slide
  is **deterministic**, not random per boot: TCG is deterministic and
  `early_random()` has no entropy source here, so it produces the same value
  every time. The two different slides seen earlier came from two different
  *kernel builds*, not two boots of one.

  So cross-run comparison is valid, provided the build is held fixed. What is
  not valid is comparing across builds, and that is what happened. The
  relationship `failing = physmap_base - slide + 0x16000000` is therefore
  neither confirmed nor refuted by any of this - it needs re-measuring with
  both values taken from one build, which is a weaker requirement than the one
  stated above.

  **The launcher discrepancy is resolved, and it matters for everything above.**
  The same image, byte-verified to contain the freeze, gives PC at 0xa00cb0c
  through one script and the halt through the other. The difference is that the
  second passes `-d int,guest_errors` to QEMU. Logging every exception slows
  TCG heavily, so within the fixed wait the guest has not reached the freeze,
  and the register read returns a state that means nothing.

  Practical consequence: **measurements must come from the launcher without
  `-d`**, and any reading in this log taken through the logging launcher is
  suspect until repeated. The logging build is still the right one for
  capturing exceptions, but not for reading registers at a freeze.

  This is the second time in this stage that a measurement apparatus, rather
  than the kernel, produced a false result - the first being registers read at
  the halt instead of at the failing instruction. Both cost more than the bugs
  they were meant to find.

  **Clean measurement, one run, one build, no `-d`:**

      physmap_base      = 0xfffffdf02d708000     unslid base + 0x2d708000
      address walked    = 0xfffffdf016000000     unslid base + 0x16000000
      difference        = -0x17708000            below the aperture start

  So the earlier reading holds after all, now on evidence that does not cross
  runs: the kernel walks an address **below the start of its own physical
  aperture**, and both values are offsets from the same unslid base. The walked
  address has level 2 index 0xB while the mapped range is 0x1C through 0x9B,
  which is consistent - it is outside the aperture, not in a gap within it.

  What has not been established is why anything computes an address below
  physmap_base at all.

  **Third apparatus problem, and the worst of them: stray QEMU processes.**
  Every launcher here uses a fixed monitor port. QEMU instances from earlier
  runs were still alive - two of them, hours old - and a new launcher would
  connect to whichever process already held the port, then report *that*
  guest's registers, running an older image. The symptom that exposed it: a
  build with a freeze at 0xa00caa0 reported PC at 0xa00cb0c, an address patched
  in a different build entirely.

  Killing them and re-running gives PC at 0xa00caa0, as placed.

  **Any measurement in this log taken before this point may have come from a
  stale guest.** The findings that are safe are the ones read out of the kernel
  file statically, and the ones confirmed across more than one build. The
  register readings need repeating with the port checked first.

  With a verified-clean run, at the freeze just after `ldr x8, [x9, #8]`:

      x08 = 0xfffffdf01311c000     already below physmap_base
      x09 = 0xfffffe000abebe00     a stack address
      x11 = 0x40000000             gPhysBase

  so x8 arrives from a stack slot already holding a value beneath the aperture.

  The launchers now kill stale processes before starting. With that in place
  and no `-d`, serial output is still **zero bytes**, so the kernel genuinely
  does not reach serial init - that conclusion survives the apparatus fixes.

  The slot itself is the lead. `ldr x8, [x9, #8]` with x9 a stack address, and
  `+8` on a struct pointer, matches the `.va` field of a `ptov_table` entry;
  `arm_vm_init.c:1528` assigns `temp_ptov_table[ptov_index].va = physmap_base`.
  The slot holds 0xfffffdf01311c000, below physmap_base, so either a later
  entry is slid downward on purpose or one is being filled from something other
  than physmap_base.

  **Confirmed from source, and it yields a contradiction.** The struct is

      typedef struct { pmap_paddr_t pa; vm_map_address_t va; vm_size_t len; }
          ptov_table_entry;

  so `+8` is `.va`, as inferred. And `arm_vm_physmap_slide` fills it:

      temp_ptov_table[i].pa = orig_va - gVirtBase + gPhysBase;
      if (i == 0) temp_ptov_table[i].va = physmap_base;
      else        temp_ptov_table[i].va = prev.va + prev.len;

  Entry 0 is physmap_base and every later entry stacks *upward* from it. So no
  entry can ever be below physmap_base - yet the slot read holds
  0xfffffdf01311c000, which is below it. Those cannot both be true of a
  correctly filled table.

  `temp_ptov_table` is a **stack array** passed in by pointer, so the obvious
  reading is that the slot being read has not been filled yet and holds stack
  residue that happens to look like a plausible address. That is a hypothesis,
  not a finding: it predicts the value should vary with anything that changes
  the stack.

  **Tested, and it holds.** Changing only the kernel command line:

      physmap_base   0xfffffdf02d708000 -> 0xfffffdf02d708000   unchanged
      x8             0xfffffdf01311c000 -> 0xfffffdf029604000   moved

  physmap_base is identical byte for byte while x8 moves, so x8 is **not
  derived from physmap_base**. It is uninitialised stack, and the prediction
  that identified it was stated before the test rather than fitted afterwards.

  So the kernel reads a `temp_ptov_table` slot that was never filled and uses
  its contents as a virtual address. Correct code does not do that on a correct
  machine, so some earlier step that should have populated those entries did
  not run - and whatever prevents it is on our side, in the boot state we hand
  over. Which entry is expected, and which caller was meant to fill it, is the
  next question.

  **And that question has a complication that must not be skipped.**
  `arm_vm_physmap_init` opens with

      ptov_table_entry temp_ptov_table[PTOV_TABLE_SIZE];
      bzero(temp_ptov_table, sizeof(temp_ptov_table));

  The array is zeroed on entry, so an unfilled entry holds **zero**, not stack
  residue. What was measured is residue that moves with the stack. Both cannot
  describe the same slot, so exactly one of these is true:

  * the slot x8 is loaded from is **not** in `temp_ptov_table` at all, and the
    identification from the `+8` offset - which matched the struct layout but
    was never confirmed to point at that array - is wrong; or
  * the `bzero` did not run, or did not cover this slot.

  The confirmed part stands: the value is stack-resident and not derived from
  physmap_base. What it belongs to is not established. Distinguishing the two
  requires finding what x9 points at, by tracing where x9 is set rather than by
  matching an offset against a plausible struct.

  **Resolved, and it is the first case: the load never runs.**

      0xa00ca68   add  x8, x13, x8          loop arithmetic
      0xa00ca8c   b    0xa00caa0            <- jumps over everything below
      0xa00ca90   adrp x8, 0xfffffe0007925000
      0xa00ca94   ldr  x8, [x8, #0x920]     physmap_base
      0xa00ca98   str  x8, [x0, #8]         write it to [x0+8]
      0xa00ca9c   ldr  x8, [x9, #8]         read it back
      0xa00caa0   <- the freeze sits here, and the branch lands here too

  x0 and x9 both hold 0xfffffe000abebe00, so on the fall-through path the store
  and the load touch the same address and x8 would come back as physmap_base
  exactly. It does not, because the branch at 0xa00ca8c was taken and the load
  never executed.

  So x8 arrives from `add x8, x13, x8` in the loop above, and no ptov_table
  read is involved at any point. The `+8` matching the struct layout was
  coincidence, and the entire ptov_table line - including the bzero
  contradiction it raised - was reasoning about an instruction the CPU skipped.

  Every failed inference in this stage failed the same way: a static reading of
  the code never checked against which path actually runs. A freeze yields
  register values, not control flow, and those are different evidence.

  Following that with a freeze on `ldp x8, x13, [x13, #8]` at 0xa00ca64, the
  next candidate source for x8, shows PC at the halt instead: **that
  instruction does not execute either.** The region around 0xa00ca50-0xa00ca9c
  is largely dead on this path, and reading it was never going to explain
  anything.

  **Method, stated so it is not repeated a ninth time.** A freeze proves an
  instruction *was* reached; the halt proves it was not. Reading a listing
  proves nothing about either. Before analysing any instruction here, establish
  it is on the executed path - either by freezing it, or by capturing the trace
  with QEMU's `-d in_asm` over a bounded window and reading the path rather
  than guessing it.

  **Applied immediately, and it corrects the paragraph above.** A `-d in_asm`
  trace, 2466 translation blocks, contains block 2355:

      0xa00ca90:  adrp x8, #0xfffffe0007925000
      0xa00ca94:  ldr  x8, [x8, #0x920]      physmap_base
      0xa00ca98:  str  x8, [x0, #8]
      0xa00ca9c:  ldr  x8, [x9, #8]
      0xa00caa0:  and  x11, x11, #0x1ffffff
      0xa00caa8:  cmp  x12, x11
      0xa00caac:  b.hs 0xa00cabc

  Those instructions **do** execute. The freeze at 0xa00ca64 failed to trigger
  because that address lies in a different block which is not entered, not
  because the surrounding region is dead. Generalising from one failed freeze
  to "the region does not run" was itself the same mistake in a new form.

  So the `ldr x8, [x9, #8]` is live after all. What remains unexplained is why
  it does not return physmap_base, given the store two instructions earlier
  writes physmap_base to `[x0, #8]` and x0 and x9 were both measured as
  0xfffffe000abebe00. Either they differ at that moment and the later
  measurement is misleading, or something between the store and the load
  intervenes.

  **The trace answers it, and vindicates the ptov_table reading.** Block 2357:

      0xa00cac0:  mov  w12, #0x1ffffff
      0xa00cac4:  add  x8, x8, x12                     +0x1ffffff
      0xa00cac8:  and  x8, x8, #0xfffffffffe000000     mask down
      0xa00cacc:  orr  x8, x8, x11                     | orig_offset
      0xa00cad0:  str  x8, [x9, #8]                    store back

  `0x1ffffff` is `ARM_TT_TWIG_OFFMASK` at a 16 KiB granule, and add-then-mask
  is `ROUND_TWIG`. That matches arm_vm_physmap_slide lines 1532-1539 exactly:

      temp_ptov_table[i].va = ROUND_TWIG(temp_ptov_table[i].va) + orig_offset;

  So `[x9, #8]` **is** `ptov_table[i].va`, this code **is**
  `arm_vm_physmap_slide`, and the identification retracted earlier was correct
  all along. The retraction was caused by generalising from the one freeze that
  did not fire.

  Score for this stage so far: eight inferences retracted, and one of those
  retractions now itself retracted. The pattern is consistent - every error came
  from reasoning about code without checking execution, in both directions.

  **Measured before the ROUND_TWIG, freezing at 0xa00cac0:**

      x08 = 0xfffffdf00b340000    the .va being adjusted
      x11 = 0                     orig_offset
      x12 = 0x1340000             new_offset

  `new_offset > orig_offset`, so the `ROUND_TWIG(va) + orig_offset` branch is
  the right one for these inputs and it is not the defect: `.va` arrives here
  **already below physmap_base**, at 0xfffffdf00b340000 against a base of
  0xfffffdf02d708000. Rounding it up cannot be what put it there.

  **And a limitation of the trace that must be recorded before it misleads
  again.** `-d in_asm` logs blocks as they are *translated*, not each time they
  execute. A block appearing in the log proves it ran at least once, never that
  it ran on a particular pass. So the earlier reasoning "block 2355 contains
  the ptov_index == 0 store, therefore that branch was taken this time" does not
  follow. Distinguishing passes needs `-d exec` or per-pass freezes, not the
  block listing.

  **A contradiction inside a single run, which undercuts the central premise.**
  Freezing on the store at 0xa00ca98 fires, so the `ptov_index == 0` branch does
  run. At that instant x8 holds 0xfffffdf00ebd0000, having just been loaded by
  `ldr x8, [x8, #0x920]` from 0xfffffe0007925920. Dumping memory from the same
  frozen guest reads 0xfffffdf02d708000 at that very address.

  A register and the memory it was just loaded from disagree, with the CPU
  stopped in between. One of these is true and none is established:

  * the dump address translation is wrong for this build, so the dump is being
    read at the wrong offset;
  * physmap_base is written again between the load and the dump, which cannot
    happen while the guest is frozen unless the freeze is not where it appears;
  * the freeze fires on a different pass than the one whose registers are read.

  Until this is resolved, **every comparison of x8 against physmap_base in this
  entry is unsafe**, including the "address below the aperture" conclusion that
  the last several commits were built on. That premise came from exactly this
  comparison.

  **And the run-to-run behaviour settles part of it.** The identical image,
  frozen at the same instruction, two consecutive runs:

      x08 = 0xfffffdf00ebd0000
      x08 = 0xfffffdf03a94c000

  physmap_base is **not deterministic across runs**. The earlier note claiming
  it was - and using that to license cross-run comparison - is wrong; that
  conclusion came from two reads that happened to agree. `early_random()` is
  evidently seeded from something that varies, most likely the timebase.

  So the correct rule is the one first written and then wrongly withdrawn:
  nothing may be compared across runs. Any figure in this entry derived from
  two separate boots has to be discarded, and that includes the arithmetic
  linking x8 to physmap_base and the slide. What survives is only what was read
  from a single frozen guest, or from the kernel file.

  **The register-versus-memory contradiction is explained: the dump lags one
  run.** In a single frozen guest, x8 freshly loaded from physmap_base reads
  0xfffffdf003b50000 while the dump of that same address reads
  0xfffffdf03a94c000 - which is exactly the x8 value the *previous* run
  reported. The 256 MiB `pmemsave` does not finish before the script kills
  QEMU, so the file left on disk is the one written by the run before.

  That is the fourth apparatus fault in this stage, after registers read at the
  halt, `-d` starving the guest, and stale QEMU processes holding the monitor
  port. It means **every dump-derived figure in this entry belongs to the
  preceding boot**, not the one whose registers were quoted beside it. The
  physmap_base values, the level 1 and level 2 table contents, the panic
  message searches: all need re-reading with the dump verified complete before
  it is parsed.

  The fix is to wait for `pmemsave` to finish - check the file size reaches the
  requested length before closing the monitor - rather than sleeping a fixed
  interval and hoping.

  **With that fixed, the premise collapses.** One run, dump verified complete:

      x08 (freshly loaded from physmap_base) = 0xfffffdf02f9f8000
      physmap_base read from the dump        = 0xfffffdf02f9f8000

  They are equal. `x8` **is** physmap_base, exactly, and there is no address
  below the aperture. Every commit built on "the kernel walks an address below
  physmap_base" rested on a dump that lagged one boot, comparing this run's
  register against the previous run's memory while the slide changed between
  them.

  What that leaves standing is narrow but real: the boot still halts, serial is
  still silent, and the panic is still `phystokv: illegal PA: 0x0`. Everything
  said about *why* since the level 1 tables were confirmed populated has to be
  discarded and redone with the corrected apparatus.

  x0 on the first hit is 0x47824000, not zero, so that call succeeds and the
  failing one comes later; catching it needs a conditional trap rather than a
  freeze on first arrival.

  Earlier notes read x21 at the panic frame and treated it as this address. It
  belongs to the printing function's frame, not the walk, and its variation
  with memSize (0x38000000 / 0x26000000 / 0x08000000 at 4G and 2G) is not
  evidence about the walk. Measure at 0xa009a1c, not at the panic.

  A `startup_bootstrap` string found near the stack was noted earlier as a sign
  of progress. It is not evidence: the serial test contradicts it, and the
  string exists in the kernel image anyway.

  Superseded detail, kept because the reasoning is reusable: the index
  `ubfx x9, x2, #36, #11`, so the level 1 index is bits [46:36] of the address
  being walked, and the walker's first argument (x21) is
  `0xfffffe0007004000` - the kernel collection base. But bits [46:36] of that
  address are `0x7E0`, while the measured index (x9) is **0**, and the entry
  read back (x8) is **0**.

  An index of zero cannot come from a kernel virtual address: every address of
  the form `0xfffffe...` has `0x7E0` in that field. So the value indexed was
  not a kernel VA. Establishing what it actually was, and which of the walker's
  arguments carried it, is the next step - x2 is clobbered by the call chain by
  the time the halt is reached, so it has to be caught before the call rather
  than read after it.

  Separating physBase from the load address did not cause this. It moved
  virtBase down by 0x9004000, so the physical aperture now starts below the
  kernel's base where before it started exactly at it - a real change in
  layout. But the panic is the same on both sides of it, and says so: it read
  `phys base 0x49004000` before and `phys base 0x40000000` after, with
  everything else identical. The empty entry predates the change.

**Track: what is actually inside the shipped macOS 27 installer.**

- **Open the opaque containers.** `payloadv2/payload.NNN`, the cryptexes and the
  `.dmg.aea` Apple Encrypted Archives were not opened, so the installed
  system's individual binaries remain un-enumerated. Until that is done,
  finding #21 rests on image *naming*, not on a binary census of the installed
  system. Establishing whether the containers are readable at all is the next
  step.
- **Identify the `pbzm` per-chunk codec.** This is now the single thing standing
  between us and a binary census of the installed macOS 27 system. The container
  is understood (finding #27); the codec is not. Candidates worth testing:
  Apple's LZBITMAP, or another `libcompression` algorithm. Everything else in
  the package has been read.
- **`AVPBooter.vmapple2.bin` on an Intel Mac.** Whether Tahoe on Intel ships the
  ARM VM firmware at
  `/System/Library/Frameworks/Virtualization.framework/Versions/A/Resources/`
  is unverified and cannot be checked from this machine. If it does, the single
  hard blocker on the emulation route is removed for anyone without Apple
  silicon. Needs the user's MacBook Pro.

## Queue

1. **OpenCore x86-specific surface** - measure how much of OpenCorePkg is
   architecture-bound, using the checkout already in `_downloads/`.
2. **Argument buffers, residency and heap aliasing** - three gaps left [open] by
   finding #12. Deferred behind the bootloader track at the user's direction.
3. **Local image audit** - run `macho_audit.py` against the Big Sur
   `BaseSystem.dmg` in `_downloads/`. Big Sur is the first universal release, so
   it is the earliest point where the arm64/x86_64 ratio inside Apple's own
   shipped system becomes measurable. Blocked on reading APFS from Windows;
   needs a plan.
3. **dyld shared cache support** in `macho_audit.py`. From Big Sur on, most
   system libraries are not standalone files - they live inside the shared
   cache. Any audit that ignores it undercounts massively, and the current tool
   ignores it. This is a known limitation of finding #1's methodology when
   applied to a full system tree.
4. **XNU x86 build feasibility** - can the published XNU actually be built for
   x86_64 standalone, or does it require unpublished dependencies? This is
   checkable and has not been checked here.
5. **macOS 27 source watch** - the moment the GG tag appears, run
   `xnu_arch_check.py` against it and commit the diff against the Tahoe
   baseline.
6. **Simulator runtime audit** - unpack a Tahoe-era `.simruntime` bundle and run
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

  **Redone, first measurement with the corrected apparatus.** Freezing on the
  `bl panic` inside phystokv:

      x00 = 0xfffffe000705c287    the format string
      x01 = x02 = 0xfffffdf030000000
      x03 = 0xfffffff030000000
      x04 = 0

  `panic()` is variadic and Apple's ABI passes variadic arguments on the stack,
  not in registers. So x1-x4 are not the arguments and never were - every
  earlier reading of them as `__func__`, `pa`, `gPhysBase`, `size` was wrong on
  that ground alone.

  The stack at that instant holds something more useful. `[sp+0x00]` and
  `[sp+0x08]` decode as ASCII to `"\0emory-m"` + `"ap"`, the string
  **`memory-map`**. That is the node name in
  `SecureDTLookupEntry(NULL, "chosen/memory-map", &memory_map)` at
  arm_vm_init.c:1318, the lookup immediately preceding the TrustCache block
  where phystokv is called.

  So the failure sits in the TrustCache path, the same place the first device
  tree fix of this stage touched. Whether the `memory-map` entries now supplied
  are the wrong shape, rather than merely absent, is what to check next.

  **Correction, one commit later.** x30 at that same freeze reads
  0x5cde7e000a009a20, which unstrips to 0xfffffe000a009a20, so the caller is
  0xa009a1c - the walker, not the TrustCache block. The `memory-map` string on
  the stack is residue from an earlier lookup, not the current context, and
  reading it as evidence of the current call path repeated the exact mistake
  this stage keeps making: treating whatever is lying nearby as though it were
  the thing being executed.

  The failure remains at 0xa009a1c. Nothing about TrustCache follows from the
  stack contents.

  **Conditional trap, everything from one guest, and it contradicts itself.**
  `cond_trap.py` diverts the call at 0xa009a1c into a stub that freezes only
  when x0 is zero, so the failing iteration is caught rather than the first
  healthy one. At that freeze:

      x00 = 0                        the argument phystokv rejects
      x02 = 0xfffffdf004000000       the address being walked
      physmap_base = 0xfffffdf003a78000     (walked address is 0x588000 ABOVE it)
      root  = [0xfffffe00078991d0] = 0xfffffe000781c000
      L1[0x7df] = 0x3800000047824003        valid
      L2[0x2]   = 0x60000040000601          valid

  The masking instruction is `and x0, x8, #imm` with N=1, immr=52, imms=35,
  which is bits 47:12. `0x3800000047824003 & 0xFFFFFFFFF000` is 0x47824000, not
  zero. So every input is present and correct, the address is inside the
  aperture rather than below it, both table levels resolve, and the argument is
  still zero.

  Note this also disposes of "the address is below the aperture" for the second
  time, now from a single guest with the dump verified complete: it is above.

  Something between reading the entry and masking it is not what the static
  listing shows. Resolving it needs the value of x8 at 0xa009a18, captured in
  the same freeze - which means a stub that saves registers rather than one
  that only tests them.

  **Resolved.** Extending the stub to preserve scratch registers into the
  freeze - it never returns on the failing path, so clobbering callee-saved
  registers is free - gives the values that were previously invisible:

      x25 = 0                       the table entry read: ZERO
      x26 = 0x7E1                   the index actually used
      x24 = 0xfffffe1000000000      the address actually walked

  The index is 0x7E1, not 0x7DF, because the `ubfx` was mis-decoded: in
  `d364bb09` the Rn field is **24**, so the instruction is
  `ubfx x9, x24, #36, #11` and the address comes from x24, not x2. That checks
  out exactly: `(0xfffffe1000000000 >> 36) & 0x7FF = 0x7E1`.

  So the walked address is `gVirtBase + 64 GiB`, one level 1 entry **above** the
  kernel's own 0x7E0, and that entry is empty. Every previous attempt compared
  the wrong address against the wrong table entry, which is why the inputs kept
  measuring correct while the argument stayed zero.

  The whole "below the aperture" family of readings was an artifact of taking x2
  for the walked address. It is above, not below, and it is above *gVirtBase*
  rather than relative to physmap_base at all.

  Next: identify what `gVirtBase + 64 GiB` is meant to be. It is one L1 entry
  past the kernel, which smells like the exclusive end of a range being walked
  inclusively, or `ROUND_L1` of something that lands on the boundary.

  **Identified.** `osfmk/arm/pmap/pmap.h:252`:

      #if defined(ARM_LARGE_MEMORY)
      /* For large memory systems with no KTRR/CTRR such as virtual machines */
      #define KERNEL_PMAP_HEAP_RANGE_START (VM_MIN_KERNEL_AND_KEXT_ADDRESS + ARM_TT_L1_SIZE)

  `ARM_TT_L1_SIZE` at a 16 KiB granule is `1 << 36`, i.e. 64 GiB, so

      KERNEL_PMAP_HEAP_RANGE_START = 0xfffffe0000000000 + 0x1000000000
                                   = 0xfffffe1000000000

  which is exactly the address in x24. The comment names our configuration
  outright: large memory, no KTRR/CTRR, virtual machines.

  So the kernel is walking the start of its own pmap heap range, one level 1
  entry above the kernel itself, and that entry has never been created. Every
  other value involved is correct, which is why nothing upstream ever measured
  wrong.

  That closes the identification for this stage. What remains is to establish
  who is supposed to create the 0x7E1 entry and why it did not happen here -
  and whether that is something a loader can pre-build or something the kernel
  does that our boot state prevented.

  **And the code that should create it is identified too.**
  `arm_vm_init.c:2321`, with a comment that describes the measurement exactly:

      /*
       * In this configuration, the bootstrap mappings (arm_vm_init) and
       * the heap mappings occupy separate L1 regions.  Explicitly set up
       * the heap L1 allocations here.
       */
      #if defined(ARM_LARGE_MEMORY)
      init_ptpages(cpu_tte, KERNEL_PMAP_HEAP_RANGE_START & ~ARM_TT_L1_OFFMASK,
                   VM_MAX_KERNEL_ADDRESS, FALSE, ...);

  So XNU knows the bootstrap mappings and the heap occupy separate level 1
  regions and populates the heap ones with a dedicated `init_ptpages` call. That
  call did not take effect here, which is why entry 0x7E1 is empty.

  The chain is now complete end to end, every link measured:

      init_ptpages for the heap L1 range does not populate entry 0x7E1
        -> a walk of KERNEL_PMAP_HEAP_RANGE_START (gVirtBase + 64 GiB) reads 0
        -> masking 0 gives 0
        -> phystokv(0) panics with "illegal PA: 0x0"
        -> the early panic path prints nothing, since serial is not up
        -> a shared halt routine spins, which looked like a silent hang

  Remaining for the stage: why that `init_ptpages` call does not populate the
  entry. Whether it runs at all is the first thing to check, with a freeze on
  it, and `cpu_tte` at that moment is the second.

  **The argument is `avail_start`, and this reframes the empty entry as
  correct.** `init_ptpages` allocates the entries it finds missing:

      if (*l1_tte == ARM_TTE_EMPTY) {
          ptpage_vaddr = alloc_ptpage(static_map);
          *l1_tte = (kvtophys(ptpage_vaddr) & ARM_TTE_TABLE_MASK) | ...;

  so the measured `x25 = 0` is **expected**: the entry is empty because it is
  about to be created. Nothing was wrong with it.

  `alloc_ptpage` (arm_vm_init.c:480), in the `map_static == FALSE` branch that
  line 2327 selects:

      vaddr = phystokv(avail_start);
      avail_start += ARM_PGBYTES;

  So the value phystokv rejects is `avail_start`, and it is zero.
  `avail_start` is assigned at arm_vm_init.c:1941 from
  `args->topOfKernelData`, which our boot_args carries as 0x4bf04000 - verified
  non-zero by reading the emitted structure back. So the assignment has not
  happened by the time this call runs.

  Corrected chain, replacing the one in the previous commit:

      alloc_ptpage is called with avail_start still zero
        -> phystokv(0) panics with "illegal PA: 0x0"
        -> nothing prints, serial is not up
        -> a shared halt routine spins, presenting as a silent hang

  The empty level 1 entry, the aperture, the addresses and the tables were all
  correct throughout. The single defect is that the page allocator's cursor is
  zero when the heap level 1 tables are built.

  **Confirmed in memory.** Reading the globals adjacent to physmap_base, from
  the same frozen guest:

      0xfffffe00079258e0  0x0000000100000000    4 GiB - real_phys_size, set
      0xfffffe0007925900  0                     zero
      0xfffffe0007925908  0                     zero
      0xfffffe0007925910  0                     zero
      0xfffffe0007925918  0                     zero
      0xfffffe0007925920  0xfffffdf003a78000    physmap_base, set

  `real_phys_size` and `physmap_base` both hold correct values while four
  adjacent slots are zero, and `avail_start` is declared among them
  (arm_vm_init.c:338-345 declares first_avail, static_memory_end, avail_start,
  avail_end, real_avail_end, real_phys_size, physmap_base, physmap_end in that
  order).

  Both are assigned inside `arm_vm_init`: `real_phys_size` at line 1829,
  `avail_start` at line 1941. The first took effect and the second did not,
  which is the whole defect stated as narrowly as the evidence allows.

  These are `SECURITY_READ_ONLY_LATE` variables, so they live in a segment that
  is writable early and locked later. A write that lands before the lock works;
  one that arrives after is dropped. Whether our page tables make that segment
  read-only too early is the next thing to test, and it would explain a silently
  dropped store with no exception - which matches the zero exception count.

  **And the reason is ordering, not a lost write.** The stores into those slots
  are at 0xa020f78, 0xa020f80, 0xa020f8c and 0xa021110. Freezing the first one
  leaves PC at the halt, so **execution never reaches the assignment**.
  `avail_start` is zero because nothing has written it yet, not because a write
  was dropped - which also disposes of the read-only-too-early theory from the
  previous entry without needing to test it.

  So the allocation at arm_vm_init.c:2327 runs *before* line 1941. Source order
  does not constrain that: 2327 sits inside a function defined later in the file
  but called earlier. And it is inside
  `#if defined(KERNEL_INTEGRITY_KTRR) || CTRR || PV_CTRR`, which is active for
  us: VMAPPLE paravirtualises CTRR per `VMAPPLE.h`, finding #18.

  That gives the stage its answer in one sentence: the kernel builds the heap
  level 1 tables through a code path gated on kernel integrity, and on this
  platform that path runs before the page allocator's cursor is initialised, so
  the first allocation it attempts calls `phystokv(0)`.

  What is still open is why the ordering differs here from real hardware, and
  the honest candidates are narrow now: either the integrity path is being
  entered when it should not be, or something it depends on completes earlier on
  a real machine. Both are checkable by freezing the entry to that function and
  reading what selected it.

  **Call structure, measured.** 0xa0098e0 has 37 call sites across four
  functions:

      0xa009168   25 calls   per-segment, so this is the protection pass
      0xa009e04    6 calls
      0xa009fd0    5 calls   the large one, plausibly arm_vm_init itself
      0xa00c9e4    1 call    at 0xa00cb24 - the failing path

  Which means 0xa0098e0 is **not** `init_ptpages`: it takes eight arguments and
  is called once per segment, matching `arm_vm_page_granular_prot`. An earlier
  entry above assumed it was init_ptpages; that assumption is withdrawn.

  The failing chain, fully measured, is:

      0xa00c9e4 -> 0xa00cb24 -> 0xa0098e0 -> 0xa009a1c -> phystokv(0)

  with x24 at the failure equal to KERNEL_PMAP_HEAP_RANGE_START, and the
  assignment to avail_start never reached.

  Note the tension that remains and should not be smoothed over: if 0xa0098e0
  is the protection pass rather than init_ptpages, then the argument reaching
  phystokv may not be avail_start after all, and the identification two entries
  above needs re-testing. The measured facts stand; the naming does not.

  **Tension resolved with data already in hand.** At 0xa009a18 the instruction
  is `and x0, x8, #mask`, and x8 at the failing moment was measured as
  `x25 = 0`. So the argument reaching phystokv is the **masked table entry**,
  not `avail_start`. The `alloc_ptpage` identification is wrong and is
  withdrawn, along with everything derived from it: the read-only-too-early
  theory, the ordering argument about line 1941, and the claim that the defect
  is an uninitialised allocator cursor.

  `avail_start` being zero and the assignment being unreached are both true and
  both irrelevant to this failure. They are downstream of it: execution stops
  before line 1941 *because* it panics here, not the other way round. I had the
  causality backwards.

  What stands, all measured in one guest with the apparatus corrected:

      the failing chain 0xa00c9e4 -> 0xa00cb24 -> 0xa0098e0 -> 0xa009a1c
      the walked address x24 = 0xfffffe1000000000 = KERNEL_PMAP_HEAP_RANGE_START
      the level 1 index  x26 = 0x7E1
      the entry read     x25 = 0, i.e. that entry does not exist
      the argument       x0 = entry & bits[47:12] = 0

  So 0xa0098e0 walks the heap level 1 range through a path that does **not**
  allocate, and entry 0x7E1 has not been created by the time it does. That is
  the defect, stated with nothing inferred: a non-allocating walk over a range
  whose tables are not built yet.

  The next question is the right one at last: which code was supposed to create
  0x7E1 before this walk, and why it has not run. `init_ptpages` at line 2327 is
  the candidate from source, but it must be located in the binary and frozen
  rather than assumed, since assuming is what produced every wrong turn above.

## Stage 6 - started, device tree requirements

With stage 5 passed the kernel walks into platform init and states each missing
piece by name. Requirements found and satisfied so far, all read out of the
shipped kernel's own strings rather than guessed:

| requirement | source | status |
|---|---|---|
| `defaults` node must exist | `pe_serial.c:831`, unconditional panic | added |
| GIC node must be at `/arm-io/gic` | string at 0xfffffe00070dae04, next to the error | renamed from `interrupt-controller` |
| GIC `reg` must be exactly 32 bytes | "expecting 32 bytes but got %u bytes" | already correct, four 64-bit values |

**Current blocker:** `%s: cannot find GICR base for core %u`, from
`find_gicr_pe_base`. The strings following it in the binary are `/cpus`,
`state`, `running`, so it walks the cpu nodes.

Two guesses were tried and both failed, recorded so they are not repeated:

* `gicr-base`, `gicr-stride`, `gicr-count`, `gicr-bases` on the gic node -
  invented names, the kernel never looks for them. Removed.
* `reg-private` on each cpu node, taken from the kernel's string table at
  0xfffffe0007137142 - a real Apple property name, but it did not satisfy this
  lookup. Left in place since it is legitimate, but it is not the answer.

**Do not guess a third time.** Disassemble `find_gicr_pe_base` and read what it
looks up. Note also that GICv3 discovery normally scans redistributor frames
matching GICR_TYPER affinity against MPIDR, in which case the answer may not be
a device tree property at all but the cpu node's `reg` failing to match QEMU's
MPIDR for core 0.

**`find_gicr_pe_base` disassembled, at 0xfffffe000a75beb4.** It references only
two strings: `/arm-io/gic` and `reg`. No per-cpu property is involved at all,
which is why `reg-private` changed nothing - that guess was wrong for a reason
now visible rather than merely unproductive.

The `reg` layout is confirmed correct as we emit it:

    bl 0xa75a5e0              SecureDTGetProperty(node, "reg", ...)
    cmp w8, #0x1f             size must be 32
    bl 0xa75c5d4              -> x20
    ldp x9,  x1,  [x8]        reg[0] = GICD base, reg[1] = GICD size
    ldp x24, x19, [x8, #16]   reg[2] = GICR base, reg[3] = GICR size
    add x0, x24, x20          GICR base + x20

so reg[0..3] mean exactly what this tree already puts there, and the 32-byte
demand is met by four 64-bit values.

The remaining unknown is the helper at 0xa75c5d4 whose result is added to the
GICR base. It references `name`, `defaults`, `serial-device` - the serial
strings - so it is a generic device tree search helper being passed `"name"` as
an argument, not a GICR-specific routine. An intermediate reading of it as the
per-core offset computation was wrong.

Next: disassemble past 0xa75bf88 to find which comparison produces the panic,
and freeze it to read the value being rejected. The reg property is not the
problem, so the failure is in what that helper returns or in a bound check
after it.

## Early console attempt - built, does not work, and the reason is instructive

`ibootcore/early_console.py` replaces XNU's early print routine with nine
instructions that write straight to a PL011 transmit register, so that panics
appear as text instead of having to be excavated from memory dumps. It
self-verifies: readback matches, and the internal branches resolve.

It produces **no output**, on either the printing panic path or the current one.

The reason is not the choice of path. It is that the MMU is on by the time any
of this runs, and 0x09000000 is a **physical** address. Nothing maps it as a
virtual address, so the stores go nowhere. XNU reaches devices through
`ml_io_map`, which returns a virtual address chosen at runtime, and that address
is not known ahead of time - which is exactly why the kernel's own early print
cannot work either and says so in its message.

So an early console needs one of:

* the routine to run before the MMU is enabled, where physical addressing works;
* a device mapping installed by our own page tables at a known virtual address,
  which means building tables rather than letting the kernel build them; or
* the value `ml_io_map` returned for the UART, read out of the guest after the
  fact and then hardcoded into a second build.

The third is the cheapest to try and is measurable: freeze after serial init,
read the mapped address, rebuild with it. The tool is written to take `--uart`
for exactly that.

**The GICR panic condition, disassembled.** At 0xfffffe000a75bf8c:

    mrs  x8, MPIDR_EL1           read MPIDR
    and  w0, w8, #0xff           take Aff0, the low byte
    ldr  x8, [x23, #0x6c8]       entry count
    cbz  x8, -> panic            empty table panics immediately
    movz x9, #0                  index
    ldr  x10, [x22, #0x6c0]      table base
    loop:
      ldr  x12, [x11 + x9]       entry, table starts at base+8
      lsr  x13, x12, #32
      cmp  w0, w13, uxtb         match Aff0 against a byte in the entry
      b.eq -> found
      add  x9, x9, #0x20         stride 32 bytes
      cmp  x9, x8
      b.hs -> panic              exhausted

So the kernel matches `MPIDR_EL1`'s Aff0 against a table of 32-byte per-core
entries. The panic has two possible causes and they need different fixes:

* the table is **empty**, so `cbz` takes it straight to the panic - meaning
  whatever builds it from the device tree did not run or found nothing;
* the table is populated but **no entry matches** Aff0 - meaning the cpu node
  identifiers disagree with what QEMU reports in MPIDR. QEMU's virt gives core 0
  an MPIDR of 0x80000000, so Aff0 is 0, and our cpu node has `reg` and `cpu-id`
  both 0, which ought to match.

**One measurement separates them:** freeze at 0xa75bf94 and read x8. Zero means
the table was never built; non-zero means a match failure. Do that before
touching the device tree again - the last two device tree guesses here both
failed.

**Correction: that loop is an MMIO scan, not a device tree table.** Measured at
a freeze on 0xa75bf94:

    x00 = 0                     Aff0, from MPIDR_EL1 = 0x80000000
    x20 = 0x08000000            GICD base, parsed correctly from reg
    x24 = 0x080a0000            GICR base, parsed correctly
    x01 = 0xf60000              GICR size, parsed correctly
    [x23+0x6c8] = 0xf60000      not a count - the GICR region **size**
    [x22+0x6c0] = 0xfffffe000c010000   the ml_io_map'd GICR base

And the stride was misread: `91408129` has the shift bit set, so
`add x9, x9, #0x20` is actually `0x20 << 12` = **0x20000**, the correct GICR
frame stride.

So the loop walks the redistributor frames over MMIO, reads `GICR_TYPER` at
frame+8, takes Aff0 from its upper half, and compares against MPIDR. There is no
table built from the device tree and **no property to add** - the previous
reading of this as a per-core table was wrong, and so were both device tree
guesses that followed from it.

The zeros read at that address prove nothing either: `pmemsave` dumps RAM, and
the redistributor is MMIO outside the dumped range.

Every value the device tree supplies here is now confirmed correct. The failure
is that the scan finds no frame whose TYPER Aff0 is 0, which points at the
mapping rather than the tree: either `ml_io_map` returned an address that does
not reach the device, or the scan starts at the wrong place within the region.

**Next measurement:** read GICR_TYPER through the monitor with `x/2xg` at the
mapped virtual address 0xfffffe000c010000, which goes through QEMU's own
translation and will show the real register rather than a RAM dump.

**GIC `reg` must be offsets, not absolute addresses - and that fix cleared the
whole GIC stage.** Comparing the same frame read two ways settled it:

    physical  0x080a0000:  +0x00 = 0x0                GICR_CTLR
                           +0x08 = 0x0000000001000011 GICR_TYPER, Aff0 = 0
    virtual   0xfffffe000c010000: 0xffffffffffffffff  not mapped

The register was there all along with an Aff0 of 0 that would have matched
MPIDR. The mapped address returned all-ones, QEMU's answer for an unassigned
address, so the scan read Aff0 as 0xff, never matched, and panicked.

`pe_arm_map_interrupt_controller` maps `soc_phys + offset`, as its own log string
admits. With absolute addresses in `reg` the kernel mapped
0x08000000 + 0x080a0000. Emitting `reg` relative to arm-io's ranges base fixes
it, and this corrects the note on the arm-io node which claimed nothing consumed
the offset form.

**Result: GIC init passes.** The boot moved from the halt into
`PE_init_platform`'s video and progress setup - the strings around the new
resting point are `kPEDisableScreen`, `iBoot version: %s`, `BootCLUT`,
`Pict-FailedBoot`, `-noprogress`, `progress-dy`, and the pixel format
`BBBBBBBBG`.

**Then two further states, both measured:**

* Without a framebuffer in boot_args, it spins in a purely arithmetic delay loop
  at 0xa75cc90 whose bound is zero: `x10 = 0`, `x11 = 0xcdd55d14`, and
  `cmp x10, x11; b.ls` is therefore always taken. A loop whose limit came from a
  value nobody set.
* With `--fb 1024x768` it panics instead, format string `"%s"` with the real text
  as a variadic argument on the stack, and not through the printing path.

Next: read that variadic argument off the stack at the halt. The technique is
established - freeze, then walk the frame - but the format being bare `%s` means
the message is a pointer in the argument area rather than a static string.

**The kernel is now running on dynamically allocated, randomised stacks.** SP at
the halt reads 0xfffffe8530027120 on one run and 0xfffffeab3c027120 on the next -
different every boot, and far outside the linear physmap. That is a real sign the
VM subsystem is working: the kernel has left its bootstrap stack and is
allocating properly mapped ones.

Two consequences for method:

* A RAM dump with a fixed offset cannot reach that stack. It has to be read
  through the monitor, which uses QEMU's own translation. `dis.ps1` now does
  this automatically from whatever SP reports.
* Stack addresses join the aperture slide in being un-comparable across runs.

Stack contents at the halt:

    [sp+0x20]  0xfffffdf0410d7f78    an address in the physical aperture
    [sp+0x28]  0xfffffe000ab49288    kernel address, repeated at +0x38
    [sp+0x48]  0xaddbfe0009eaf3e4    PAC-signed return -> 0xfffffe0009eaf3e4

`[sp+0x00]` is zero, so the `%s` argument is not in this frame and the chain has
to be walked. The return address gives the next frame: 0xfffffe0009eaf3e4.

**Stage 6 state at the end of this session.**

Passed: the `defaults` node, the `/arm-io/gic` node name, the 32-byte `reg`
check, and GIC initialisation itself - the last unlocked by emitting `reg` as
offsets from arm-io's `ranges` base rather than absolute addresses.

Reached: `PE_init_platform`'s video and progress setup. The kernel is on
dynamically allocated, randomised stacks, which means the VM subsystem is
genuinely working.

Blocked on: a panic whose format string is a bare `%s`, so the text is a
variadic argument that has to be found by walking the frame chain. `[sp+0x00]`
is zero; the next return address is 0xfffffe0009eaf3e4. Reading each stack slot
as a string through the monitor was attempted and printed nothing, so either the
filter or the monitor pacing needs work - the technique is right, the
implementation in `dis.ps1` is not finished.

Also unresolved, and worth doing early because it makes everything after it
easier: no serial output yet. `early_console.py` exists and self-verifies but
writes to a physical address that is unmapped once the MMU is on. The cheapest
fix is to read the address `ml_io_map` returned for the UART out of a running
guest and pass it as `--uart`. Until then every failure has to be excavated
rather than read.

**The UART is never mapped, which kills the cheapest console route.** Scanning
24 pages from 0xfffffe000c000000 for a PL011 flag register - `FR` at +0x18,
which reads a recognisable ~0x90 and cannot be confused with ordinary memory -
finds nothing. The GIC mappings are in that range, so device mappings do land
there; the UART simply is not among them.

That follows from where the boot stops: the panic in `PE_init_platform`'s video
setup happens before `ml_io_map` is ever called for the serial port, so there is
no mapped address to read out and pass to `early_console.py --uart`.

Two routes remain, and both are more work than the one just ruled out:

* run the print before the MMU is enabled, where the physical address works.
  The trampoline already runs in that state, so it could at least prove the UART
  path end to end, though it cannot print the kernel's own messages;
* install a device mapping ourselves at a known virtual address, which means
  building page tables in the loader instead of letting the kernel build them.

Worth checking first, because it is cheaper than either: whether XNU is even
selecting our PL011. The `defaults` node we supply is empty, so no
`serial-device` phandle is specified and the kernel picks its own. `VMAPPLE.h`
lists PL011 as a platform feature, so support exists, but nothing has confirmed
the kernel chose it rather than looking for an Apple UART or dockchannel.

**Why the serial port was silent all along: `/defaults` needed a
`serial-device` phandle.** `serial_init` does

    if (!get_serial_device_phandle(&phandle)) {
        // XNU has not been configured to use a serial device
        return 0;
    }

so an empty `defaults` node makes the kernel select **no serial device at all**
and return before any driver runs. The node was originally added empty on the
reasoning that the kernel would then pick its own - it does not, it gives up.
That single missing property is why nothing was ever printed, through this
entire bring-up.

Three fixes went in together, all read from `pe_serial.c` rather than guessed:

* `/defaults/serial-device` = a phandle, and `AAPL,phandle` on the UART node to
  match. `SecureDTFindNodeWithPhandle` connects the two.
* the compatible string is **`arm,pl011`**, lower case. The table at
  `driver_setup_functions` spells it that way; ours said `ARM,pl011` and would
  never have matched.
* the UART's `reg` is an offset from arm-io's ranges base, exactly like the
  GIC's: `pl011_uart_setup` maps `pe_arm_get_soc_base_phys() + reg->block_offset`.

The port is still silent, so something before `serial_init` still stops the
boot, but three real defects are gone and none of them was guessed.

**State after those fixes.** Freezing the panic entry at 0xa79d9a8 does *not*
fire, so that function is not being called; the CPU instead rests at
0xfffffe000a01241c with PAC-signed returns on the stack to 0xfffffe000a0125fc
and 0xfffffe0009e3a68c, the latter in the exception vector region. So the
current stop is an exception path, not a `panic()` call, which is a different
shape of failure from everything before it and needs the exception log read
rather than a message hunted.

**The kernel is alive and servicing interrupts.** With the serial device fixes
in, a `-d int` capture over 25 seconds records 736 lines:

    56x  FIQ            timer interrupts, each followed by a clean
                        "Exception return from AArch64 EL1 to AArch64 EL1"
    41x  Data Abort     page faults, also returning cleanly
     4x  Hypervisor Call

Every exception is taken *and returned from*. So the GIC delivers interrupts,
the timer fires, and the fault handlers work. The interrupts arrive at
0xfffffe0009e92034, which is inside a bounded TLB invalidation loop -
`tlbi` with CRn=8, stepping by 4 for 0x1000 iterations - so the kernel is doing
ordinary bulk work, slowly, under TCG.

That is a different class of state from everything before: not a halt, but a
running kernel. It still ends at the halt afterwards.

**The panic arguments are located.** Freezing the entry to the panic machinery
at 0x9e92168 gives:

    x00 = 3
    x01 = 0xfffffe0007063190   "panic"
    x02 = 0xfffffe000723102d   "%s"
    x03 = 0xfffffe38100272b8   the argument to that %s

so x3 holds the message. Reading it back has not worked yet: the monitor in this
QEMU has no string format, and reading it as bytes produced nothing printable,
so either the address is not text or the read is wrong. x2 read correctly as
"%s", which shows the technique works and the problem is specific to x3.

The byte-order fix in `dis.ps1` works - x2 now reads back as `"%s"` correctly,
stopping at the NUL instead of running into the next string. x3 at
0xfffffe4c360272b8 still reads as unreadable, and that address has the same shape
as the kernel stack (0xfffffe..027xxx), so it is a stack address whose read is
failing rather than a bad pointer. Earlier stack reads through the monitor
succeeded with `x/2xg`, so the difference is in the read itself, not the address.

That is where this session ends. `dis.ps1` now: kills stale QEMU, waits for the
dump to complete, reads registers, walks the stack through the monitor, decodes
strings from registers with correct byte order, and hunts for the mapped PL011.
Every one of those exists because a measurement went wrong without it.

**Reading the panic text: what works and what does not.**

`gva2gpa` is the reliable way to follow a pointer out of a register. Parsing the
monitor's hex output directly failed in both directions - one word at a time
timed out and looked like an unreadable address, one big read let the address
prefixes into the match and produced garbage. Translating to a physical address
and reading the RAM dump has no parsing at all, and `dis.ps1` now does that.

With it working, none of the candidates is the message:

    x02 -> gpa 0x4723102d   "%s", correct
    x03 -> gpa 0x4d0df2b8   not text
    x07 -> 0xfffffe0008443de8, contains `pacibsp` - a function pointer
    [sp+0x00] = 0
    0xfffffe000ab49288, which appears twice on the stack - zeros in the
                        kernel file, so a BSS global

So the assumed call signature is wrong. `x0 = 3, x1 = "panic", x2 = "%s"` does
not map onto `panic(fmt, ...)`, and the variadic argument is not at `[sp]`
either. Either 0x9e92d78 is not the panic entry, or its first arguments mean
something other than what was assumed.

**Do not guess the signature.** Disassemble 0x9e92d78's prologue and see which
registers it saves and where it reads its arguments from, the same way
`find_gicr_pe_base` was settled. Four attempts to read the message by assuming
the layout have now failed, and each one cost a boot.
