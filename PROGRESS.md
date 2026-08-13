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

**0x9e92d78 is a trace record writer, not panic.** Its prologue settles it
without another boot:

    mrs  x8, TPIDR_EL1            per-cpu pointer
    ldr  x10, [x8, #0x190]
    add  x10, x9, x10, lsl #16    x10 = buffer + index * 0x10000
    str  w0, [x10, #8]
    ldr  x11, [sp, #0]            an argument off the stack
    stp  x1, x2, [x10, #0x10]     registers stored into the record
    stp  x3, x5, [x10, #0x20]
    stp  x7, x11, [x10, #0x30]
    str  x4, [x10]

It writes the incoming registers into a fixed-size per-cpu record in a ring
buffer. That is tracing, not panicking. `x0 = 3`, `x1`, `x2` are values being
recorded, not panic arguments, and every attempt to read a message out of them
was chasing the wrong call.

It also explains `0xe7ffdeff`: it sits in the middle of this routine, and
replacing it with `nop` removed every exception, which is consistent with a
marker or barrier in a trace path rather than an instruction with semantics.

So the halt at 0x9e921bc, reached from 0x9e9216c right after this trace call,
may not be a panic at all. That has to be established before anything else:
the whole "read the panic message" line of work assumed a panic that has not
been shown to exist.

**A pointer read that finally works: `gva2gpa` then `xp`.** Translate the
virtual address, then read it *physically*. `xp` takes a physical address, so no
page tables are involved and the output has exactly one form. That removed every
parsing failure at once:

    X02 -> gpa 0x4723102d  [656e616f6c007325 3a63696e61700065 74706d6574746120 6c616564206f7420]
    X03 -> gpa 0x4d0df2b8  [fffffe9afe0272d0 fffffe9afe027b00 10a8fe0008443de8 fffffe9afe0272d8]
    X07 -> gpa 0x48443de8  [a9bf7bfdd503237f ...]

Decoding X02 little-endian gives `"%s"` followed by the neighbouring strings
`"panic:"` and `" attempt to deal..."`, which confirms both the address and the
byte order.

X07 decodes to `d503237f a9bf7bfd` - `pacibsp; stp x29, x30, [sp, #-16]!` - a
function prologue, so X07 is a code pointer.

X03 holds **pointers**, not text: the first is 0xfffffe9afe0272d0, which is 0x18
past x3's own address, so this is an argument-list structure pointing back into
the same stack region. The message is therefore one dereference further on, and
the technique to follow it now exists and is reliable.

## Stage 6 - read this first

**Where the boot stops:** `panic: non-sensical crypto hash method:` with an empty
value, from the Image4 secure-boot path. Everything before it now passes.

**Passed this stage, all read from the kernel rather than guessed:**

| requirement | how it was found |
|---|---|
| `/defaults` node | `pe_serial.c:831`, unconditional panic |
| `/defaults/serial-device` phandle + `AAPL,phandle` on the UART | `serial_init` returns early without it, which is why the port was silent throughout |
| compatible `arm,pl011`, lower case | the `driver_setup_functions` table spells it that way |
| GIC node at `/arm-io/gic` | the path sits beside the error string |
| GIC and UART `reg` as **offsets** from arm-io's ranges base | both map `soc_base_phys + reg->block_offset` |
| `/product` node | `panic: failed to get product node` |
| `/chosen` NVRAM properties, not `/options` | `IONVRAM.cpp` reads them from `/chosen` |
| valid CHRP NVRAM image, adler from offset 20 | the kernel printed both checksums |

**Serial output works.** `early_console.py --uart 0xfffffe000c000000` prints, and
routing the halt into the kernel's own printer (`mov x0, x2; mov x1, x3; bl` over
the three words at 0x9e92164) makes XNU format its own panics. Use that: every
failure names itself now, and the three fixes after it landed in one session
against one message per session before.

**The kernel is alive.** 56 timer interrupts, 41 page faults, all with clean
exception returns. GIC, timer and fault handlers all work.

**The remaining blocker needs material, not analysis.** The manifest lookup at
0xfffffe0008431aac queries an object two dereferences into a graph, not the
device tree. Named properties on `/chosen/manifest-properties` are not found -
`sha2-384` and `sha1` were both tried. It is very likely a DER Image4 manifest
blob that the kernel parses. The manifest for this platform exists in the shipped
installer; extract it rather than synthesise one.

**Apparatus: six faults found and fixed in this stage.** Registers read at the
halt are clobbered; `-d` starves the guest; stale QEMU processes answer the
monitor port; a 256 MiB `pmemsave` outlives the script; the monitor reader
desynchronises unless it drains and waits for the prompt; PowerShell's `:x`
silently ignores a `UInt64`. Four of the six produced **false negatives**, which
get believed rather than checked. Use `dis.ps1` and `uartscan.ps1`, which carry
the fixes.

**Build the image and trampoline together**, always:

    python build_image.py <kernel> --out image.bin --phys-base 0x47004000 \
      --ram-base 0x40000000 --mem-size 4G --cmdline="-v" \
      --fb 1024x768 --fb-addr 0x50000000 --trampoline trampoline.bin

Anything that changes the device tree's size moves boot_args, and a separately
built stub then points into the middle of the tree. That produced a machine
resetting into an exception vector with 2 452 392 logged exceptions, and cost two
sessions before it was found.

---
## Stage 6 - into IOKit

Following pointers with `gva2gpa` + `xp` finally made panic messages readable,
and the kernel then named its own requirements one after another. Each was added
and the next appeared:

    panic: failed to get product node          -> added /product
    panic: failed to get manifest properties   -> added /chosen/manifest-properties,
                                                  /chosen/asmb, /options
    NVRAM size is 0 bytes, possibly due to
    bad config with iBoot + xnu mismatch       -> gave /options a real
                                                  nvram-proxy-data buffer

The routine driving these walks a fixed list, and the paths sit in the string
table beside the messages: `/chosen`, `/defaults`, `/product`,
`/chosen/manifest-properties`, `/chosen/asmb`.

**The NVRAM message came from `IONVRAM.cpp`**, which is an IOKit driver. So the
boot is past platform initialisation entirely and into driver matching - stage 6
proper.

After the NVRAM buffer went in the state changed shape again: PC reads
0x0000000049e3d200, a **physical** address, which is 0xfffffe0009e3d200 in
virtual terms - just past the kernel entry point, with the MMU off. That is a
restart: the machine reset and the kernel began again.

Whether that reset is a failure or the kernel deliberately re-entering is the
next thing to establish, and it needs the exception log rather than a register
read.

**Nodes added this round, all empty of content on purpose.** The manifest and
asmb nodes carry sealed-system-volume material - the ARV root hash and manifest a
real loader supplies, per finding #15. Inventing values there would be worse than
leaving them absent, so the nodes exist to satisfy the lookups and their contents
remain an open, honest problem.

**The reset is a fault loop in an exception vector.** A `-d int,guest_errors`
capture records **408 732** undefined-instruction exceptions, all at the same
address, with the vector target equal to the faulting address:

    Taking exception 1 [Undefined Instruction] on CPU 0
    ...with ESR 0x0/0x2000000
    ...with ELR 0x49e3d200
    ...to EL1 PC 0x49e3d200

The instruction at that address is `14000000`, a branch to itself, and it is
**identical in Apple's unmodified kernel** - verified against `vma2.kernel`, so
it is not one of our patches. Its position, VBAR + 0x200, is the synchronous
exception vector for the current exception level.

So after the NVRAM node went in, the machine reset, the kernel restarted with the
MMU off, took a synchronous exception immediately, landed in the vector Apple
fills with a deliberate spin, and stayed there.

That is a different failure from anything before it and needs the *first*
exception identified, not the 408732nd. The log's early entries, before the loop
establishes itself, are where to look - and `-d int` writes them in order, so the
head of the file is the evidence.

**The first exception, which is the one that matters.** The head of the log,
before the vector loop establishes itself:

    Taking exception 1 [Undefined Instruction] on CPU 0
    ...with ESR 0x0/0x2000000
    ...with SPSR 0x200003c4
    ...with ELR 0x49e401cc          <- the real fault
    ...to EL1 PC 0x49e3d000

Physical 0x49e401cc is 0xfffffe0009e401cc, and the instruction there is
`f800854c` = `str x12, [x10], #8`, a post-indexed store. It is **byte-identical
to Apple's unmodified kernel**, so it is not one of our patches. The
surrounding code is a loop:

    movz x13, #0x2000000
    str  x12, [x10], #8      <- faults
    add  x12, x12, x13
    subs x11, x11, #1
    b.ne back

which is building page table entries with a 32 MiB stride.

An ordinary store reported as an undefined instruction is not what it appears to
be. ESR EC 0 is "unknown reason", which QEMU also emits for conditions other
than a genuinely undefined encoding, so the encoding is probably fine and
something about the machine state at that instant is not. SPSR reads 0x200003c4:
DAIF fully masked, EL1t, and the V flag set.

That is where the next session starts, and it should freeze at 0xfffffe0009e401cc
and read x10, x11, x12 rather than reason about the encoding.

**Operands at the faulting store, measured by freezing it:**

    PC  = 0x49e401cc          physical, so the MMU is off
    X00 = 0x47004000          our load address
    X10 = 0x478a4118          the store target, inside the loaded image
    X11 = 0x7dd               2013 iterations remaining
    X12 = 0x0040000046000601  a block descriptor for physical 0x46000000
    X13 = 0x2000000           32 MiB stride

Every value is sane. 2013 iterations at 32 MiB is exactly 64 GiB, one level 1
entry's worth, and the target is a valid physical address in our own image.
The instruction encoding is valid and identical to Apple's.

So "undefined instruction" is not describing an undefined encoding here.
Possibilities worth testing, in order of cheapness:

* this is the *second* boot, after a reset. On reset QEMU re-runs the
  `-device loader` entries, so the CPU starts at the trampoline again with the
  image restored - meaning the fault may be a consequence of restarting into a
  state the kernel does not expect, not of this instruction at all;
* ESR EC 0 also covers traps QEMU raises for unimplemented system behaviour,
  which would point at the state around the store rather than the store;
* the store target sits inside the loaded image and this early code writes page
  tables over it. If the image and the table area overlap, the kernel is
  overwriting its own text and the fault follows a page or two later.

The third is measurable straight away: compare X10's range against the image
extent this build reports.

**The store was innocent; the trampoline was passing a stale boot_args.**
Reading boot_args at a hardcoded address gave all zeros, which exposed the real
problem: adding `--fb` puts a framebuffer node in the device tree, the tree grows
from 2 KiB to 11 992 bytes, and boot_args moves from 0x4be05000 to **0x4be07000**.
The trampoline was still built for the old address and handed the kernel a
pointer into the middle of the device tree.

So every measurement taken with `--fb` was of a kernel given a garbage
boot_args. The reset, the undefined instruction, the page-table store that
looked like it was overwriting the kernel - all of it followed from that, and
the store itself was doing exactly what it should.

Rebuilding the trampoline with `--x0 0x4be07000` restores a normal boot: PC is a
virtual address again, so the MMU comes up and the kernel reaches the same state
as the non-framebuffer build.

**The lesson is structural, not incidental.** The trampoline is built by a
separate command from the image, and nothing checks that the address it carries
matches the one the image reports. Any change that resizes the device tree
silently invalidates it. `build_image.py` should emit the trampoline itself, or
at minimum the two should be checked against each other before a run.

**`pl011_uart_setup` is now reached.** Located by its own panic string
("Unable to find the 'reg' property on the PL011 UART devicetree node" at
0xfffffe00070db82c, referenced from 0xa75e390, function starting at
0xfffffe000a75deb0), a freeze on its entry fires: PC stops there.

So the device tree is finally correct enough that XNU selects our PL011 and
calls its driver setup. All four device tree fixes were needed together: the
`serial-device` phandle in `/defaults`, `AAPL,phandle` on the UART node, the
lower-case `arm,pl011` compatible string, and `reg` as an offset from arm-io's
ranges base.

The port is still silent. The mapped-PL011 scan finds nothing, but it also finds
nothing at the GIC addresses which are certainly mapped, so the scan itself is
broken rather than the mapping being absent. Fix the scan before concluding
anything from it - this is the same class of mistake as the four apparatus
faults already recorded, and it would be the fifth.

**The UART is mapped, and its address is now known: 0xfffffe000c000000.**
Reading +0x18 there returns `0x00000090` - a PL011 flag register with both FIFOs
empty. That is not a value ordinary memory produces, so the identification is
certain. The driver setup worked and the device is live.

Two apparatus faults had to be fixed to see it, and both had produced
convincing-looking negative results:

* the monitor reader desynchronised. Reading once after a fixed sleep means a
  slow reply is collected by the *next* command, and after a dozen queries the
  answers no longer match the questions. The symptom is an empty reply, which
  looks exactly like a failed read. It now drains first and accumulates until
  the prompt returns.
* PowerShell's `:x` format silently does nothing to a `UInt64`, so addresses
  went to the monitor as decimal digits behind an `0x` prefix. Every read was of
  a nonsense address and the scan reported "nothing readable in that range" -
  which reads as a finding and is not one. Casting to `Int64` fixes it.

That is the fifth and sixth apparatus fault in this stage. Both produced false
negatives rather than false positives, which is the more dangerous direction:
a wrong answer gets checked, an absent one gets believed.

`early_console.py --uart 0xfffffe000c000000` now assembles against the real
address, but the port stays silent, and the reason is no longer a mystery: the
current halt arrives through 0x9e9216c, which does **not** print, rather than
0x9e91e60, which does. The patched routine is never called on this path.

## Serial output works

`early_console.py`, pointed at the mapped UART and patched onto the path that
actually executes, prints. The port carries the string the kernel had in x1:

    panic

Five bytes, clean, no faults. So the chain is proved end to end: the device tree
describes the UART correctly, `ml_io_map` maps it at 0xfffffe000c000000, the
driver is set up, and writes reach QEMU.

**The failed attempt was worth more than the successful one.** The first version
built the address with a single `movz`, which covers 16 bits at one shift and
silently truncated 0xfffffe000c000000 to 0x0c000000 - unmapped. The store faulted
and **XNU printed its own 3060-byte crash report** through its own console:

    Kernel data abort. at pc 0xfffffe0009e92d88, lr 0xfffffe0009e9216c
      x0: 0xfffffe0007063191  x2: 0x000000000c000000
      esr: 0x96000005  far: 0x000000000c000018

which proves the kernel's native console is alive too. It simply is not used on
the halt path currently taken - that path traces and stops without printing.

Two things follow. Any failure can now be made to print by patching the executed
path, so the excavation from memory dumps that this whole stage required is over.
And the kernel's own console will produce a full boot log the moment the boot
reaches a path that uses it.

**Panic messages are now readable on the wire.** Routing the halt path into the
kernel's own printing function - `mov x0, x2; mov x1, x3; bl <print>` over the
three words at 0x9e92164 - makes XNU format and print the panic itself:

    IONVRAMCHRPHandler creation failed
     @IONVRAM.cpp:1691

followed by its full register dump. No more excavating from memory.

**`nvram_image.py` builds a valid CHRP store.** The layout and checksum are read
from `iokit/Kernel/IONVRAMCHRPHandler.cpp`, not guessed:

    chrp_nvram_header  = sig | cksum | len(16-byte blocks) | name[12]
    apple_nvram_header = chrp | adler32 | generation | padding[8]

and the checksum is a byte sum with end-around carry over `sig` plus `len`
through `name`, skipping the checksum field. The tool recomputes both the
checksum and the Adler-32 after writing and refuses to emit an image that fails
its own validation.

It does **not** fix the panic. Reading `nvram_validate_header_v1v2` shows the
kernel checks only the name and the checksum - the signature byte is not
validated at all - and our image satisfies both. So the failure comes from a
different check inside handler creation, and the next step is to find which,
now that the message arrives as text.

**NVRAM accepted.** Three defects, each named by the kernel itself once the
serial console was printing:

1. `IONVRAMCHRPHandler creation failed` with a valid image. The store hangs off
   **/chosen**, not /options - `IONVRAM.cpp` does
   `IORegistryEntry::fromPath("/chosen", gIODTPlane)` and reads `bankSizeKey`
   and `proxyDataKey` from there. The handler was being handed nothing at all;
   the image had never been the problem.

2. `header adler 0x7AD10967 != calculated_adler 0x9AC90968`. The kernel printed
   both values, which located the fault exactly. `adler32_with_version` starts
   at `offsetof(struct apple_nvram_header, generation)` = **20**, not at the end
   of the 32-byte header:

       chrp header  0..15
       adler       16..19
       generation  20..23    <- checksum starts here, covering itself
       padding     24..31

3. With those fixed the checksum matches, the handler is created, and the boot
   moves on.

**The new panic is from a different subsystem entirely:**

    panic: non-sensical crypto hash method

That is the sealed-system-volume chain - the ARV material a real loader supplies
and which our `/chosen/manifest-properties` and `/chosen/asmb` nodes are
deliberately empty of. It is the blocker that was flagged in advance as needing
material from outside rather than more reverse engineering.

Worth noting how fast these three went compared to everything before them. With
the console working, each failure named itself and the fix followed from reading
one function. The whole of stage 5 was spent extracting single messages from
memory dumps.

**Manifest properties, read from the kernel's own strings.** The panic
"non-sensical crypto hash method: " with nothing after the colon named the
missing property directly. Around 0xfffffe0007234f1a the kernel spells out both
the name and the permitted values:

    crypto-hash-method    with `sha1` and `sha2-384` immediately following
    certificate-production-status      certificate-security-mode
    effective-production-status-ap     effective-security-mode-ap
    mix-n-match-prevention             allow-ecid-mismatch
    uses-avp-root-ca

`uses-avp-root-ca` is worth noting: AVP is Apple Virtual Platform, so this code
path exists for exactly the machine we are pretending to be.

Populating `/chosen/manifest-properties` with those clears the panic. **The
values chosen describe an unlocked development machine** - production status
off, security mode off, mix-and-match allowed. That is a real loosening of
secure boot rather than a placeholder, and a loader shipping them would be
declaring the machine unlocked. It is recorded here rather than buried in the
code.

**State after that.** The serial output stops, so the redirected panic path is
no longer reached. Two exceptions and then silence, against 2 452 392 lines of
exception loop before:

    Data Abort, ESR 0x96000006, FAR 0x945d70,  ELR 0x4a7abde4
    Data Abort, ESR 0x96000006, FAR 0x148,     ELR 0x4a0129c0

Both ELRs are physical addresses, so the MMU is off and this is early code.
FAR 0x148 is a small offset from null - a field read through a null pointer.
Whether the machine reset and restarted, or never brought the MMU up this time,
has to be established before reading anything more into it.

**The trampoline is now emitted by `build_image.py` itself.** `--trampoline PATH`
writes the stub from the addresses the build just computed, and prints the exact
QEMU command line to go with it.

This closes a defect that caused the two most misleading failures in the whole
project. Building the stub with a separate command lets the two disagree, and
anything that changes the device tree's size moves boot_args. Adding the
framebuffer node did it once; adding the manifest properties did it again,
growing the tree from 11 992 to 12 400 bytes and moving boot_args from
0x4be07000 to 0x4be08000. The kernel then received a pointer into the middle of
the device tree, and the symptoms looked like deep kernel faults:

* a machine that reset and spun in an exception vector, 2 452 392 exceptions;
* a page-table store that appeared to be overwriting the kernel's own text;
* an "undefined instruction" on an ordinary, valid `str`.

None of it had anything to do with the code being investigated. Two separate
sessions of analysis went into those symptoms before the cause was found, and
both times the cause was the same stale number.

**Still open:** the manifest properties did not take. The panic returns as
"non-sensical crypto hash method: " with nothing after the colon, so
`crypto-hash-method` is still not being found. The names taken from around
0xfffffe0007234f1a may be display labels for a printout rather than device tree
property names - Image4 manifest fields are conventionally four-character codes.
That needs establishing from the code that reads them, not from the strings that
sit near them.

**The manifest lookup is not a device tree read.** Disassembling the only
reference to the `crypto-hash-method` string, at 0xfffffe0008431aac:

    adrp x1, "crypto-hash-method"
    add  x2, sp, #0x10          output buffer
    mov  x0, x20                the object being queried
    bl   0xfffffe00084299c0     lookup(obj, key, &out)
    adrp x1, "sha1"
    movz w2, #4                 compare four bytes
    bl   0xfffffe0008447a2c

and x20 comes from `[[x0 + 0x10] + 0x8]` - a field two dereferences into an
object graph, not the device tree. Both `sha2-384` and `sha1` were tried as
device tree properties and neither is found; the panic prints an empty value
either way.

So `/chosen/manifest-properties` is very likely a **single blob** that the
kernel parses - an Image4 manifest in DER - rather than a node whose children
are individual properties. Adding named properties to a node cannot satisfy a
parser expecting a serialised structure.

That reframes this blocker as it was described in advance: it needs **material
from outside**, specifically a manifest, not more names guessed from the string
table. The manifest for this platform exists inside the shipped installer, so
the next step is to find and extract it rather than to synthesise one.

Two attempts at synthesising the properties are recorded here as failures so
that a third is not made from the same assumption.

**Apple's own manifest for this platform, extracted.** The installer ships it at

    AssetData/boot/Firmware/Manifests/restore/
      macOS Customer Software Update/apticket.vma2macosap.im4m

`vma2macosap` is the Apple Virtual Machine - the same platform whose kernel this
project boots. It is 4 819 bytes, deflate, and `im4m_props.py` reads 21
properties out of it:

    BORD 32        CEPO 1         CHIP 65024 (0xFE00)
    CPRO True      CSEC True      SDOM 1
    EKEY True      EPRO True      ESEC True
    prtp "VirtualMac2,1"          tagt "VMA2MACOSAP"
    tatp "vma2macos"              sdkp "macosx"
    apmv "27.0"                   love "26.1.388.5.7,0"
    DGST, srvn                    digests

`prtp` is "VirtualMac2,1", matching the model this device tree already claims,
which is how the file was confirmed to be the right one rather than assumed.

**Two things this settles.**

The property names are **four-character codes**, not the long labels near the
panic string - those are what the kernel prints, not what it looks up. Both
earlier syntheses used the labels and could never have worked.

And `CPRO` and `CSEC` are **true** in Apple's manifest. The first synthesis set
them to zero, declaring an unlocked development machine and describing that as a
deliberate loosening of secure boot. Apple's own values say the opposite, so that
loosening was both unnecessary and wrong. Corrected.

**Still not enough.** Putting the four-character properties on
`/chosen/manifest-properties` does not clear the panic either. Combined with the
disassembly - the lookup queries an object two dereferences into a graph - the
kernel is parsing the manifest **blob**, not reading a node. The next attempt
should hand it the raw 4 819 bytes rather than a decomposition of them.

The manifest and the parser are committed, so that work is not repeated.

**Third attempt, also failed: the raw blob in the device tree.** Supplying the
4 819-byte manifest as `/chosen/manifest-properties`, as `/chosen/manifest`, and
as `manifest` and `IM4M` properties inside the node - the device tree grew from
12 400 to 32 264 bytes, so it was certainly delivered - leaves the panic
unchanged.

So the manifest is not read from the device tree in any form. Three shapes have
now been tried and eliminated:

1. long display-label properties on the node - wrong names entirely;
2. four-character-code properties on the node - right names, wrong place;
3. the raw DER blob, on the node and on /chosen - right data, wrong place.

The disassembly said as much and should have been trusted sooner: `x20` comes
from `[[x0 + 0x10] + 0x8]`, two dereferences into an object the caller passes
in. The device tree is not in that path at all.

**Next, and it is a different kind of step:** find the callers of the function
containing 0xfffffe0008431aac and see where that object is built. It is likely
an Image4 environment assembled earlier in boot, possibly from the trust cache
or from a registry entry, and whatever populates it is what needs feeding - not
the device tree.

---

## Stage 6 - read this first

**Driver matching: working. Storage discovery: one step short.**

The kernel boots to `!BSD` and sits in `IOKitBSDInit` asking for a root volume:

    Waiting on <dict><key>IOProviderClass</key><string>IOMedia</string>
                    <key>Content</key><string>Apple_HFS</string></dict>

Everything before that works. AppleARMGICv3 starts and registers as an interrupt
controller, AppleVirtualPlatformPCIE brings up the host bridge, Apple's own
IOPCIConfigurator walks the bus and configures three devices, AMFI, Sandbox,
Quarantine, EndpointSecurity, AppleCredentialManager, AppleVPKeyStore,
CoreAnalyticsHub, IOHIDSystem, IOSurfaceRoot, APFS, NFS and TMPFS all load.

The disk is present as a PCI nub:

    Registering: ../pcie@37000000/AppleVirtualPlatformPCIE/scsi@2

and `info pci` on the monitor confirms what is on the wire - 1b36:0008 host
bridge at 0:0, 1af4:1000 ethernet at 0:1, 1af4:1042 SCSI at 0:2.

What has not happened is `AppleVirtIOPCITransport` binding to it. Its
personality is `IOProviderClass = IOPCIDevice`, `IOPCIPrimaryMatch =
0x00001af4&0x0000FFFF`, no other condition. The kext is in the boot collection
with `OSBundleRequired = Local-Root`, it loads, and it registers the class. All
1114 personalities reach the catalogue.

### What has been eliminated, so it is not tried again

| Hypothesis | How it died |
|---|---|
| MSI delivery was missing | Replaced the RAM stand-in frame with QEMU's real GICv2m (`-M virt,msi=gicv2m`, frame at 0x08020000). No change. |
| Wrong virtio device ID | Transitional mode (0x1af4:0x1001) behaves exactly like modern (0x1af4:0x1042). |
| IOPCIFamily's tunnel gate | Its literal pool has `Driver "%s" needs "%s" key in plist` immediately after `IOPCITunnelCompatible`, and AppleUIOPCI - the only driver that ever probes a PCI nub here - is the one personality carrying that key. But the message never prints, and adding `IOPCITunnelCompatible` and `IOPCITunnelled` to the pcie node changed nothing. |
| Kext not loaded | `kextlog=0xff` shows `Loading kext com.apple.driver.AppleVirtIO`, `calling module start function`, and `registered class AppleVirtIOPCITransport`. |

### The one hard fact to reason from

Class matching works on these nubs and vendor matching does not.
`AppleUIOPCI_Ethernet` matched `IOPCIClassMatch 0x02000000&0xffffff00` and
probed ethernet@1, which means `IOPCIBridge::matchNubWithPropertyTable` runs and
reads `savedConfig[2]`. `IOPCIPrimaryMatch` reads `savedConfig[0]` through the
same helper and fails. Both registers were demonstrably read during the scan:
device 0 got the name `pci1b36,8@0`, which is built from vendor and device ID,
and devices 1 and 2 got `ethernet` and `scsi`, which are built from class code.

### Next measurement, not next guess

IOPCIFamily logs both sides of the comparison:

    [PCIe:%u %llu ns] Matching nub %u:%u:%u
    [PCIe:%u %llu ns] Comparing plist value & mask (0x%x & 0x%x)
                      vs. reg 0x%x value & mask (0x%x & 0x%x)

gated by bit 0 of a word at 0xfffffe000acbb740. Writing 7 into that word in the
image did not enable it - the banner still reports `log mode flags 0x4`, so the
variable is initialised at runtime and the static patch is overwritten. Find
where it is written, or find the boot argument that sets it. That log states
what the two values actually are and ends the guessing.

### Stage 6 - measured, not inferred (update)

Boot arguments for IOPCIFamily's own log: `pci_log`, `pci_log_mode`,
`pci_log_rc`. Found by disassembling the initialiser at 0xfffffe00094a85f0.
`pci=` is deprecated and the kernel says so.

With `pci_log=0xffffffff pci_log_mode=0x7`:

* The configurator works. `Found type 0 device class-code 0x010000 at
  [i5]0:2:0(0x1af4:0x1001)`, BARs sized and assigned, `[0x14 MEM] 0x10008000,
  read 0x10008000` and `[0x20 PFM] 0x10000000, read 0x1000000c`.
* The I/O BAR at 0x10 is never assigned, only MEM and PFM, even though the pcie
  ranges advertise an I/O window.
* `AppleVirtIOPCITransport`'s match IS evaluated, once per nub.
* The `reg` value in the comparison log lags one iteration - the first value of
  a list logs the stack poison 0xaaaaaaaa, later values log the real register -
  so it cannot be read as the comparison input. AppleUIOPCI's single-value class
  match logs the same poison and still probes.
* Where the log does show it, the register is right: 0x00081b36 for the host
  bridge, 0x10011af4 for the disk. Masked with 0xffff that equals the plist
  value. On the evidence the match succeeds.
* After a full boot, `info pci` still reports every BAR of 0:2:0 as **not
  mapped**. Memory decode was never enabled. Nothing drove the device.

So the gap is between a successful match and a driver that never enables the
device: probe returns NULL without logging, or start returns false without
logging. Neither is visible at `io=0x3f`.

**Next: prove reachability instead of inferring it.** Put a freeze at
AppleVirtIOPCITransport's entry - cond_trap.py already does this elsewhere in
the project - and see whether the guest stops there. That answers in one boot
which side of the gap the failure is on, and every further step depends on the
answer.

### Reachability test: the VirtIO transport code never executes

Found AppleVirtIOPCITransport's publishing code through its literal pool, the
same way `crypto-hash-method` and `InterruptControllerName` were found. Its
class name sits with the two properties it sets on the nub it publishes:

    0xfffffe0007409f59  AppleVirtIOPCITransport
    0xfffffe0007409fb7  built-in
    0xfffffe0007409fc0  IOVirtIOPrimaryMatch

The only reference to `IOVirtIOPrimaryMatch` is at 0xfffffe0008a2b100, 100 bytes
into a function entered at 0xfffffe0008a2b09c that nothing calls directly - a
virtual method, as expected.

Froze that entry with `b .` and sampled the PC ten times across a full boot.
Four distinct addresses, none of them the freeze. **The function is never
reached, so the driver never runs at all.** That agrees with `info pci`
reporting every BAR of 0:2:0 still unmapped after a complete boot.

Two of the ten samples landed at 0xfffffe0008a74a78, inside
AppleVirtualPlatformPCIE's config-space read accessor:

    lsr x8, x1, #8 ; ldr x9, [x0, #0xc0] ; ... ; add x8, x8, x9
    cmp x9, #0 ; csel x8, xzr, x8, eq ; ldrb w0, [x8]

Twenty percent of samples in a config read on an otherwise idle system is worth
noting. Whether that is ordinary hot-plug polling or a symptom has not been
established, and should not be assumed either way.

So the failure is on the matching side after all, not in probe or start. The
comparison runs, the register holds the right value, and no candidate results.
The next thing to read is IOKit's own side of it - `IOService::probeCandidates`
and what it does with the personality after `matchPropertyTable` returns - since
IOPCIFamily's half has now been exhausted.

### Correction: the 0xaaaaaaaa in the PCI matching log is deliberate

An earlier entry explained the `0xaaaaaaaa` values in IOPCIFamily's comparison
log as a stale local - a variable printed before it was assigned. That
explanation is withdrawn. The code writes the pattern on purpose:

    0xfffffe00094b4a70  mov  x8, #-0x5555555555555556    ; 0xAAAAAAAAAAAAAAAA
    0xfffffe00094b4a74  str  x8, [sp, #0x50]             ; poison the slot
    0xfffffe00094b4a78  bl   ...                         ; then fill it
    0xfffffe00094b4a7c  add  x1, sp, #0x50
    0xfffffe00094b4a80  bl   ...

So a poisoned value in the log means the call that should have filled that slot
did not - it is a real signal, not a printing artefact.

What has **not** been established is which of the format's seven arguments comes
out of that slot. The variadic marshalling at 0xfffffe00094b4a90..ab0 does not
map to the format string in an order that could be read off with confidence, and
guessing at it is how this investigation has gone wrong before. Two candidates
remain open: the register value, in which case the config read genuinely fails
for those comparisons and that is the whole bug; or the timestamp, in which case
the poison says nothing about matching.

**Settle that first, before anything else.** Decode the marshalling properly, or
find the same log call in a case whose outcome is already known - AppleUIOPCI
matches by class and demonstrably probes, so whatever its line shows is what a
*successful* comparison looks like. That single comparison decides which of the
two readings is right, and every next step depends on it.

### Settled: the poison in the match log means nothing either way

Ran the comparison whose outcome is already known. AppleUIOPCI matches by class
and demonstrably probes, and every one of its comparisons prints the poison too:

    Comparing plist value & mask (0x2000000 & 0xffffff00)
        vs. reg 0x8 value & mask (0xaaaaaaaa & 0xffffff00)

A successful comparison and a failing one look identical in this log. The field
is not the register the comparison used. So IOPCIFamily's comparison log cannot
distinguish the two here, and AppleVirtIO's line showing 0xaaaaaaaa is not
evidence of anything. That whole line of inquiry is closed - a negative result,
but it saves the next attempt from repeating it.

**And it corrects the freeze result.** The function at 0xfffffe0008a2b09c is the
one that references `IOVirtIOPrimaryMatch`, which is the property the transport
sets on the child nub it *publishes* - so it runs at the end of a successful
start, not at its entry. That it is never reached means start did not get that
far. It does not mean start was never called, which is what the earlier entry
concluded.

So the live question is back to: what does AppleVirtIOPCITransport::start do
before it publishes, and which step of it fails. The next measurement is to find
the real entry of start - through the class's vtable, via its OSMetaClass - and
freeze *that*, which distinguishes "never called" from "called and gave up"
properly.

### Positive control: the nub is fine, only vendor matching fails

QEMU's virtio-blk-pci takes a `class` property, which gives a lever to change
one variable and nothing else. Presenting the same disk as an ethernet
controller with `class=0x0200`:

    Registering: .../AppleVirtualPlatformPCIE/ethernet@1
    Registering: .../AppleVirtualPlatformPCIE/ethernet@2
    AppleUIOPCI[0x100000156]::probe fails
    AppleUIOPCI[0x100000158]::probe fails

Two probes where there was one. IOKit reaches the disk's nub, selects a driver
for it, and runs probe. The nub is not special and nothing about it blocks
matching.

(The first attempt used `class=0x020000` and produced `pci1af4,1001@2` with no
probe - the property is a 16-bit class code, so the 24-bit value landed as
something IOPCIFamily does not recognise. The name changing at all is what said
the property had taken effect.)

So the failure is isolated to one branch of one function.
`IOPCIBridge::matchNubWithPropertyTable` handles IOPCIClassMatch and
IOPCIPrimaryMatch through the same helper, reading `nub->savedConfig` at offset
0x08 and 0x00 respectively. The class branch works on these nubs. The vendor
branch has never selected anything - not for the disk at 1af4:1042 or 1af4:1001,
and not for the virtio network card at 1af4:1000, which AppleVirtIOPCITransport
should also have claimed in every run so far.

That points at `savedConfig[0]` holding something other than
(device << 16) | vendor by the time matching runs, while `savedConfig[2]` holds
the class correctly. Read what fills that array in IOPCIConfigurator and what,
if anything, overwrites its first entry.

### The comparison itself, and where to read the value

`matchKeys` is at 0xfffffe00094b4998. Its arguments are (x1 = nub, x2 = keys,
w3 = default mask, w4 = regNum), and the comparison is:

    0x94b49d4  mov  w22, #-0x55555556        ; poison the reg variable, ONCE
    0x94b49d0  lsr  w24, w4, #2              ; index = regNum >> 2
    ...                                      ; parse value into x27, mask into x28
    ...                                      ; the log prints here, before the read
    0x94b4b4c  ldr  x8, [x20, #0xb0]         ; the nub's savedConfig pointer
    0x94b4b50  ldr  w22, [x8, w24, uxtw #2]  ; savedConfig[index]
    0x94b4b54  eor  x8, x27, x22             ; plist value XOR register
    0x94b4b5c  tst  x8, x28                  ; and the mask
    0x94b4b60  b.ne <next value>             ; non-zero means no match

Two things follow. The poison is written once before the loop and the log runs
before the read, which is why a successful match prints it too - that closes the
question for good, from the code rather than from a control.

And the value the comparison actually uses is `[[nub + 0xb0] + (regNum & ~3)]`.
For the disk that should be 0x10011af4, and
(0x1af4 ^ 0x10011af4) & 0xffff is zero, so it should match. It does not.

**Next step, and it is a direct read rather than an inference.** Divert
0xfffffe00094b4b50 into a stub that freezes only when x27 is 0x1af4 - cond_trap.py
already does exactly this shape of patch elsewhere in this project - and read w22
and x8 from the monitor. That gives the savedConfig pointer and the word it
holds, which is the last unknown in the chain.

### Read the comparison directly: savedConfig is correct

Patched `eor x8, x27, x22` at 0xfffffe00094b4b54 to `brk #0`. A break panics with
a full register dump and clobbers nothing, so the values the comparison uses can
simply be read off. First hit:

    x27 0x02000000   the plist value
    x22 0x06000000   the register that was read
    x23 0xffffff00   the default mask
    x24 0x00000002   the index, so regNum 0x08
    x20 0xfffffe2bf008ebc0   the nub

That is IOPCIClassMatch against the host bridge, and savedConfig[2] holds
0x06000000 - class code 0x060000, correct for a host bridge. So the array is
populated and indexed correctly, and the read works.

The break fires on the first comparison to reach it, which is this one, so it
does not yet answer the vendor case. To get that, the break has to be conditional
on w24 being zero, or on x27 being 0x1af4. There is no conditional BRK and only
one instruction slot here, so it needs cond_trap.py's approach: divert into
padding, test there, and freeze or return.

What this does establish is that nothing is wrong with savedConfig as such,
which was the leading hypothesis after the positive control. The remaining
possibilities are narrower: either savedConfig[0] specifically differs from
0x10011af4 on our nubs, or the vendor branch is not reached with the values the
log suggests.

### The matcher is provably correct end to end

Built a conditional trap the way cond_trap.py does it - divert into alignment
padding, test there, freeze or return. The padding is at 0xfffffe00093a4140,
nops followed by zeros at the end of a section:

    0xfffffe00093a4140  cbnz w24, +8        ; index != 0, carry on
    0xfffffe00093a4144  brk  #0             ; index == 0, the vendor branch
    0xfffffe00093a4148  eor  x8, x27, x22   ; the displaced instruction
    0xfffffe00093a414c  b    0xfffffe00094b4b58

with 0xfffffe00094b4b54 replaced by a branch to it. The trap fires on a vendor
comparison and nothing else, and the dump reads:

    x24 0x00000000    index 0, so regNum 0 -- the vendor branch
    x27 0x11421b21    the plist value
    x22 0x00081b36    savedConfig[0], device 0x0008 vendor 0x1b36
    x28 0xffffffff    the mask

The register is read correctly, the comparison is performed correctly, and the
mismatch is legitimate - 0x1b36 is the QEMU host bridge and that personality
wants 0x1b21. Reading the array directly through the monitor in the same boot
agrees: savedConfig[0] = 0x00081b36, savedConfig[2] = 0x06000000.

So the whole IOPCIFamily matching path is sound, and for the disk
(0x1af4 ^ 0x10011af4) & 0xffff must be zero. **The match succeeds.** That
eliminates matching entirely, which is where four sessions of suspicion had
pointed.

**What that leaves.** The driver matches, becomes a candidate, and something
after that fails silently. No `probe fails` line ever appears for it, which fits
a class that does not override probe - IOService::probe returns `this` and logs
nothing. So start is called and returns false before it publishes.

The freeze at 0xfffffe0008a2b09c proved only that the code referencing
`IOVirtIOPrimaryMatch` never runs. Find the class's vtable through its
OSMetaClass at 0xfffffe0008a2c69c, take the `start` slot, and freeze that. Then
"never called" and "called and gave up" separate for good, and if it is the
latter, the same padding trick reads out where inside start it turns back.

### Finding start through the vtable: blocked by pointer signing

Located a vtable slot for AppleVirtIOPCITransport by searching the image for the
address of its known virtual method:

    0xfffffe0008a2b09c  appears once, at 0xfffffe000afffd48

and the same for a class whose start is known, to calibrate the slot index.
`AppleARMGICv3::start` is at 0xfffffe0007f9c4e4 - walked back from the call site
in its registration code - and appears at 0xfffffe000ae41948.

Deriving the index from those fails. Scanning backwards for the table base while
the preceding word looks like a kernel address stops immediately for both,
reporting index 0, which cannot be true for either. The reason is that this is an
arm64e collection: vtable entries are signed pointers, and in the file they are
chained-fixup entries whose raw 64-bit value is not an address. Only the odd
entry reads back as a plain pointer, which is why the two searches hit at all.

So the slot index cannot be read off this way. Doing it properly means parsing
LC_DYLD_CHAINED_FIXUPS and walking the chain in __DATA_CONST, which is a real
piece of work but a reusable one - nothing else in this project has needed to
read a vtable yet, and identifying any virtual method by name will need it.

Two alternatives worth weighing first, both cheaper:

* Freeze on the metaclass's `alloc`, reachable from the OSMetaClass constructed
  at 0xfffffe0008a2c69c. If the driver is never allocated, start was never
  called and the question is answered without a vtable at all.
* Trap inside `IOService::probeCandidates` in the kernel proper, where the
  candidate list is walked, and read which personality is in hand. That is
  kernel code, not kext code, and its symbols are easier to pin down.

### The driver was attached all along

`io=0xffff` turns on kIOLogServiceTree, which dumps the registry. It shows:

    pcie@37000000                     <AppleARMIODevice, busy 1>
      AppleVirtualPlatformPCIE        <busy 2>
        pci1b36,8@0                   <IOPCIDevice, busy 0>
        ethernet@1                    <IOPCIDevice, busy 1>
          AppleVirtIOPCITransport     <busy 0>
        scsi@2                        <IOPCIDevice, busy 1>
          AppleVirtIOPCITransport     <busy 0>

**AppleVirtIOPCITransport is attached to both virtio devices, including the
disk.** It matched, was instantiated, and started - a failed start detaches, and
these are attached. Every conclusion in this file about matching failing was
wrong, and the reason it took so long to see is that none of the flags tried
before 0xffff dump the registry; absence of log lines was read as absence of the
driver.

So the gap is one link further on. AppleVirtIOBlock's provider is
`AppleVirtIOTransport`, a nub the PCI transport is supposed to publish beneath
itself. No such nub exists, and the code that would create it - the function at
0xfffffe0008a2b09c that sets `IOVirtIOPrimaryMatch` - is still never reached, as
the freeze showed. The transport starts, gets some way in, and returns without
publishing.

**And there is a strong candidate for why.** `info pci` after a full boot still
reports every BAR of 0:2:0 as "not mapped": memory decode was never enabled.
A transport that had successfully mapped the device's virtio structures would
have turned it on. So it is failing while bringing the device up, before it has
anything to publish.

Next, and now well-posed: find where inside start it turns back. The padding
stub at 0xfffffe00093a4140 is the tool - the same divert-test-return shape,
placed on candidate points inside 0xfffffe0008a102e0..0x8a442fb. Start from the
capability walk: modern virtio keeps its structures behind PCI capabilities, and
if the transport cannot find them it has nothing to map.

### Modern-only virtio changes nothing, and the nubs never stop being busy

Forcing the disk modern-only with `disable-legacy=on,disable-modern=off` gives
the identical registry: the transport attached to scsi@2, publishing nothing. So
the unassigned I/O BAR - which would matter only to a transitional device's
legacy interface - is not the cause. Worth having ruled out, since Apple's ARM
IOPCIFamily allocates no I/O space at all and that looked promising.

The registry shows something else that does matter:

    ethernet@1               <IOPCIDevice, busy 1>
      AppleVirtIOPCITransport <busy 0>
    scsi@2                   <IOPCIDevice, busy 1>
      AppleVirtIOPCITransport <busy 0>

Both nubs sit at busy 1 permanently while the drivers on them are busy 0. In
IOKit a nub is busy while matching is outstanding on it, so matching on these
nubs never completes. The driver that did attach has finished; something else is
still pending.

One of the strings in probeCandidates is `%s(0x%qx): matching deferred by %s%s`,
and deferral is exactly what a permanent busy count looks like. Read that path
next: find what defers, and what it is waiting for. That is a better lead than
bisecting inside start, because a deferred match would also explain why the
transport never publishes - it may be waiting to be told it may.

### A function table for the kext, and why the brk sweep stalls

`__DATA_CONST` carries a sorted table of (function address, metadata) pairs for
each kext - found by accident while looking for a vtable, at 0xfffffe000afffd48:

    0xfffffe000afffd38  fffffe0008a2afdc
    0xfffffe000afffd40  0000031e00386747
    0xfffffe000afffd48  fffffe0008a2b09c     <- the publish helper
    0xfffffe000afffd50  0000031e0068acbd

Walking it outward while the value stays inside the kext's text
(0xfffffe0008a102e0..0x8a442fb) yields **1204 function entry points**. That is a
general tool: it enumerates a kext's functions without symbols, and nothing in
this project had one before.

Used it to sweep for reachable code - `brk #0` at every entry, boot, read the pc:

| skip below | first break | caller |
|---|---|---|
| -            | 0xfffffe0008a105b8 | 0xfffffe000a5f9bc0 |
| 0x8a12000    | 0xfffffe0008a1524c | 0xfffffe000a5f9bc0 |
| 0x8a20000    | 0xfffffe0008a23c7c | 0xfffffe000a5f9bc0 |

Always the same caller. That address is the kernel's kext-load path calling the
kext's OSMetaClass constructors, of which this kext has over a thousand, and they
are scattered throughout rather than grouped - so raising the address threshold
never gets past them. Six functions immediately around the publish helper were
also swept individually and none executes.

Filtering has to be on the **caller**, not the address. A single shared stub in
the padding at 0xfffffe00093a4140 can do it, because every one of these entries
begins with `pacibsp`: compare x30 against the loader's return address, and
either execute the displaced `pacibsp` and continue or trap. The only awkward
part is resuming at site+4, which the stub cannot compute from x30 alone - so
each site needs its own two-word thunk, or the sweep needs to run in batches
small enough to bisect by hand.

That is the next step, and it is mechanical rather than uncertain.

### start is called, and the shim chain is decodable

The sweep reached the driver's own code. Callers moved off the kext loader and
onto IOKit's matching path at 0xfffffe000a651xxx, and three of the hits identify
themselves:

    0xfffffe0008a29cd8   getMetaClass, returns the metaclass at 0xac78020
    0xfffffe0008a29ce8   the metaclass's alloc: operator new of 0x140 bytes
    0xfffffe0008a29d50   start(provider) -- lr 0xfffffe000a651d44, IOKit

So the object is allocated and **start is called**. That is now measured rather
than inferred, and it rules out everything upstream of it for good.

start is a shim. It allocates a helper into [this + 0x138] - the last field of a
0x140-byte class - and tail-calls through a pointer at 0xfffffe0007c11368. That
pointer is a chained fixup, and it decodes:

    0x801143aa01a3a758
      bit 63      auth
      bits 47:32  0x43aa   the diversifier, matching `movk x17, #0x43aa, lsl #48`
      bits 31:0   0x01a3a758  offset from the kernel base

giving 0xfffffe0007004000 + 0x01a3a758 = **0xfffffe0008a3e758**, which is inside
the kext and is another shim of the same shape, storing into [this + 0x88].

Two things follow. The split-shim pattern means each class in the hierarchy
contributes one, so start descends a chain rather than doing work directly - and
the sweep will walk it. And decoding that pointer is the same decoding the vtable
route needed, so the earlier blocker is no longer a blocker: a chained fixup
here is `base + (value & 0xFFFFFFFF)` with the diversifier in bits 47:32.

## Stage 6 - the blocker is found: start spins in the virtio capability walk

`AppleVirtIOPCITransport::start` is at 0xfffffe0008a29e24 and spans 1832 bytes to
0xfffffe0008a2a54c. It has exactly one return instruction, at 0xfffffe0008a2a548.
Trapping that instruction with `brk #0` and watching it never fire proves the
function **never returns**. That is why the nub sits at busy 1 forever, why the
driver shows attached but publishes nothing, and why the boot waits for a root
device that can never appear.

Bisecting the 33 call sites inside it - trapping from index k onward and asking
whether anything fires - put execution past index 20 at 0xfffffe0008a2a1ec and
never at 21. The disassembly says why: 0xfffffe0008a2a28c is
`cbnz w21, #0xfffffe0008a29ff0`, a backward branch, so the later call sites are
simply on paths the loop does not take.

The loop is the virtio PCI capability walk, and it identifies itself:

    cmp  w25, #1 / #2 / #3 / #4
    ...
    str  x22, [x19, #0x100]      cfg_type 1, common configuration
    str  x22, [x19, #0x110]      cfg_type 4, device configuration
    str  x22, [x19, #0x118]      cfg_type 3, ISR
    str  w8,  [x19, #0x124]
    cbnz w21, <back>             w21 is the next-capability offset

`w21` never reaches zero, so the walk never ends. The call at index 20 is
0xfffffe00094c7994 in IOPCIFamily, a config-space read - it takes the device and
an offset below 0x1000 and dispatches through the device's vtable at +0x8a0,
which lands in `AppleVirtualPlatformPCIE::configRead8`. That closes a loop with
an earlier observation that had no explanation at the time: two of ten PC samples
during an idle boot landed inside that accessor. The guest is spinning in config
reads.

So the fault is in what config space reads back through this bridge, not in
matching, not in MSI, not in the device tree's PCI description, and not in the
driver. A capability chain whose `next` pointer never becomes zero is the classic
symptom of reads returning 0xff - follow 0xff and you land on 0xff again forever.

**Next, and it is a direct comparison.** Read the disk's capability list two
ways: from QEMU's monitor, which shows what the hardware presents, and from the
guest's own accessor, by trapping 0xfffffe00094c7994 and reading its argument and
result over several iterations. If the guest sees 0xff where QEMU has a real
chain, the bridge's address arithmetic is wrong for the offsets the walk uses -
and that arithmetic is four instructions long and already disassembled.

### Root cause: the capability search cycles between two offsets

The walk does advance - it is not stuck on one entry - but it only ever visits
two. Measured with conditional traps in the padding stub, each firing on a
different condition:

| trap condition | fired |
|---|---|
| any offset (first iteration) | yes, offset 0x84, word 0x05147009 |
| offset != 0x84 | yes, offset 0x70, word 0x02146009 |
| offset == 0x40 (the last in the chain) | **no** |
| offset not in {0x84, 0x70} | **no** |
| the instruction just past the loop tail | **no** |

So `extendedFindPCICapability(9, &offset)` returns 0x84, then 0x70, then 0x84
again, forever. It never reaches 0x60, 0x50 or 0x40, and the loop never exits.

The chain itself is fine. Read straight out of ECAM at 0x3f010000, which is what
the guest's own config reads see:

    0x34  capability pointer = 0x98
    0x84  id 09  next 0x70  len 0x14  cfg_type 5   PCI config access
    0x70  id 09  next 0x60  len 0x14  cfg_type 2   notify
    0x60  id 09  next 0x50  len 0x10  cfg_type 4   device
    0x50  id 09  next 0x40  len 0x10  cfg_type 3   ISR
    0x40  id 09  next 0x00  len 0x10  cfg_type 1   common

Well formed, five vendor capabilities, terminating. The device's config space is
not the problem and neither is the bridge's address arithmetic, which was checked
instruction by instruction and correctly carries the high nibble of extended
offsets in bits 24..27 of the space word.

**That is the stage 6 blocker, located exactly.** Everything else in the chain
works: the device is on the bus, configured, matched, the driver is allocated,
attached, and its start runs. It simply never returns, because IOPCIFamily's
capability search does not advance past the second entry on this bridge.

Two directions from here, and the first is cheap:

* The two offsets it alternates between are the two `len 0x14` capabilities.
  The three it never reaches are all `len 0x10`. That is unlikely to be a
  coincidence and is the first thing to test - a length field being mistaken for
  a next pointer, or a cursor comparison that only accepts entries of a given
  size.
* Failing that, disassemble the search itself. It is reached through the device
  vtable at +0x988 from 0xfffffe0008a2a01c, and the same padding-stub technique
  reads its arguments and return value per call.

## Stage 6 - PASSED

    scsi@2                            <IOPCIDevice>
      AppleVirtIOPCITransport
        AppleVirtIOBlockStorageDevice

    ethernet@1                        <IOPCIDevice>
      AppleVirtIOPCITransport
        AppleVirtIONetwork
          IOEthernetInterface, IOKernelDebugger, IOKDP

Apple's own drivers, unmodified, running on QEMU's virtio devices.

The blocker was a single infinite loop and the fix is four bytes.
`AppleVirtIOPCITransport::start` walks the PCI capability list for
vendor-specific entries; on this machine it visited 0x84, then 0x70, then 0x84
again, forever, never reaching 0x60, 0x50 or 0x40. The chain in config space is
correct and terminating - the two it cycled between are the two of length 0x14,
the three it never reached are the three of length 0x10.

`IOPCIDevice::extendedFindPCICapability` at 0xfffffe00094c8100 has two paths: a
cached one, taken when the configurator's state at [device+0xa0]+0x1d8 exists,
and a direct config-space walk when it does not. The cached path is what cycles.
Turning the `cbz x9` at 0xfffffe00094c8138 into an unconditional branch forces
the direct walk, the loop ends, and start completes.

**This hides a defect rather than repairing it.** Something in how that cached
state is built on this bridge cannot represent five vendor capabilities, and
finding that is the honest fix. The patch is recorded on the same terms as every
other in this project - a bring-up measure.

Kernel modification total: **81 bytes of 80,871,424**, 0.0001 percent. Userland
untouched.

Stage 7 is what remains before a root volume: the disk is 8 GB of zeros, so
there is no partition map and nothing for IOMedia to publish. The kernel is
waiting for exactly that.

## Stage 7 - PASSED

    Added memory device md0/rmd0 for 000000000CC00000
    BSD root: md0, major 3, minor 0
    apfs_vfsop_mountroot:3156: apfs: mountroot called!
    container_rootmount:2638: boot from ramdisk /dev/md0
    handle_mount:893: md0s1 vol-uuid: 4BCD88B9-5915-4712-B3F7-E21A8DADCD4F
                      block size: 4096 block count: 52224
    apfs_log_op_with_proc: md0s1 mount-complete volume ramdisk
    VM Swap Subsystem is ON
    load_init_program: attempting to load /sbin/launchd

Apple's APFS driver mounting Apple's filesystem image, and the kernel executing
PID 1 out of it.

The image is `AssetData/usr/standalone/update/ramdisk/arm64eSURamDisk.dmg` from
the installer. Despite the extension it is an IM4P of payload type `rdsk`, and
inside is a raw APFS container - NXSB at offset 32, 4096-byte blocks, 52224 of
them, exactly the file size. It is the root Apple boots during software updates,
so it is self-contained and needs no partition map.

What it took, all named by the kernel's own strings:

* `chosen/memory-map/RAMDisk` = <address, length>, reserved at full size like
  DeviceTree and BootArgs so filling it in later cannot move the tree
* `rd=md0` on the command line
* topOfKernelData raised past the image - that field is where the kernel
  believes free memory begins, and anything above it is fair game for the
  allocator

## Stage 8 - begun, and the first obstacle is named

    AMFI: /sbin/launchd: Rejecting signature, binary has platform identifier
          but is not in the trustcache
    proc 1: load code signature error 4 for file "launchd"
    panic: launchd[1] fatal signal 9

launchd is found and executed; AMFI rejects it because the platform binaries on
that ramdisk have to be listed in a trust cache the kernel was given, and none
was. The file exists:

    AssetData/boot/Firmware/arm64eSURamDisk.dmg.trustcache   9,067 bytes

the trust cache for exactly this ramdisk. Handing it over is the next step and
is the same shape of work as the ramdisk itself - a blob, a memory-map entry,
and room reserved for it.

### Stage 8, broken into parts

| part | what is needed | how it is checked |
|---|---|---|
| 8.1 | hand the kernel a trust cache | AMFI stops rejecting launchd |
| 8.2 | launchd passes signing and loads | no fatal signal 9 |
| 8.3 | dyld and the shared cache work | no rejection of /usr/lib/dyld |
| 8.4 | launchd reaches its own main loop | its own messages appear |
| 8.5 | the first services start | notifyd, configd, disk arbitration |

### 8.1 - the material is in hand, the delivery is not

`AssetData/boot/Firmware/arm64eSURamDisk.dmg.trustcache` is an IM4P of payload
type `rtsc` wrapping a version 1 module: uuid 944c0b19-d98d-4d78-839d-7cde0ba77728,
410 cdhash entries - every platform binary on that ramdisk, launchd included.

The kernel names the mechanism itself: `chosen/memory-map`, an entry called
`TrustCache`, "unexpected size for TrustCache property: %u != %zu", "no external
trust caches found (segment length is zero)". The segment layout is readable from
the parser at 0xfffffe000a46eaa8 - a uint32 module count, that many uint32
offsets, then the modules.

**None of it boots.** Each of these gives zero bytes of serial:

* the raw module as the segment
* a correctly wrapped segment, count 1 and offset 8
* an empty segment, count 0
* placed past the ramdisk at 0x58c00000
* placed inside the image at 0x4be09000
* the address written as physical
* the address written as virtual

Not the content, not the placement, not the address space. The presence of a
`TrustCache` entry kills the boot before serial init, which is why there is
nothing to read - trust caches load during bootstrap, before the console exists.
The stopping point was read through the monitor: PC in the `wfe; b .` pair at
0xfffffe0009e921b8, the early-panic spin.

One real defect was found on the way and is fixed. The placeholder was at first
written into **every** tree as sixteen zero bytes, like DeviceTree and BootArgs.
That alone is fatal: the parser converts the address before it checks the
length, so a zero address gets translated and the translation faults. The entry
is now emitted only when a trust cache is supplied, and the working
configuration is untouched - still 25,237 bytes of log, root mounted, PID 1
executed.

**Next, and it avoids the device tree entirely.** "no external trust caches found
(segment length is zero)" is about a Mach-O segment in the kernel collection, not
about the tree. Writing the module into that segment and correcting its size in
the load command hands the kernel its trust cache with no memory-map entry at
all - and unlike a panic with no console, it can be checked statically before
booting.

### 8.1 - the entry itself is fatal, and that is now proven

Eight configurations, all zero bytes of serial: raw module; wrapped segment with
count 1 and offset 8, matching the parser at 0xfffffe000a46eaa8; empty segment;
past the ramdisk at 0x58c00000; inside the image at 0x4be09000 below
topOfKernelData; physical address; virtual address; and finally **the entry
pointed at the device tree itself**, a region the kernel demonstrably maps and
walks.

That last one eliminates content, placement and address space together. The
presence of a `TrustCache` property in chosen/memory-map is fatal whatever it
contains.

The fault is also upstream of the loader. A freeze planted at
0xfffffe000a46eaa8 - the instruction that reads the module count - is never
reached; the PC sits in the early-panic spin at 0xfffffe0009e921b8. The kernel
dies before it looks at the trust cache at all.

Two real defects found on the way, both fixed:

* the placeholder was written into **every** tree as sixteen zero bytes. Fatal
  on its own: the parser converts the address before checking the length, so a
  zero address is translated and the translation faults.
* the trust cache block overwrote topOfKernelData with a value below the
  ramdisk, having run after it and recomputed from its own smaller total - the
  kernel would have believed free memory began inside the root filesystem. The
  blocks are reordered; the ramdisk sets the top.

`kernel-only` is now on memory-map, which Apple's tree carries and this one did
not. It changed nothing, but it was missing and it is true.

Working configuration verified unharmed: 25,237 bytes, root mounted, PID 1
executed.

**Do not try a ninth arrangement of the same entry.** The evidence says the
kernel objects to the entry existing, which points at how memory-map is consumed
rather than at trust caches. Apple's tree has sixteen `MemoryMapReserved-N`
slots that iBoot renames in place - so the kernel may expect entries from that
fixed set, or a particular count, or a particular order. Read the code that
walks memory-map during bootstrap; it can be read statically, and a panic with
no console cannot.

## Stage 8.1 - 8.4 PASSED: launchd runs

    attempting to load 1 external trust cache modules
    loaded external trust cache module: 0
    completed loading external trust cache modules
    AMFI: Booted in a VM
    AMFI: developer mode is force enabled on this platform
    load_init_program: attempting to load /sbin/launchd
    vm: shared_region: [1(launchd)] check_np(0x16d047918)
    Darwin Ignition Sequence Version 1.0.0: root:libignition-64~11775
    libignition: 1:   ignition level    : 0x5

launchd's signature is accepted, dyld loads it, the shared region is created,
and PID 1 reaches its own bootstrap library and prints its own arguments.

**The answer was placement**, and two experiments found it.

Renaming the entry to `MemoryMapReserved-0` - one of the sixteen slots Apple's
tree carries - made the boot complete again with the same blob at the same
address. So an extra memory-map entry is harmless; the name `TrustCache` starts
a loader, and the loader is what died.

The loader's early consumer at 0xfffffe000a009304 then says what it wants:

    ldr x0, [x22]          ; address from the entry
    bl  0xfffffe000a008bb4 ; convert
    ldr x8, [x20, #0x200]  ; a boundary
    cmp x0, x8
    b.hs <failure>         ; at or above it is fatal

**The trust cache must sit below the kernel image.** All eight earlier attempts
put it after the image, and failed for that one reason. iBoot places it before
the kernel; here there is 112 MiB between the start of RAM and the load address,
and 0x46000000 works.

Eight configurations of the same wrong idea produced zero bytes each and no
information. One look at the branch produced the answer. When the failure is
before serial init, read the code - there is nothing else to read.

### 8.5 - open

launchd stops after printing its ignition arguments. Userland now, not firmware.

### 8.5 - launchd is alive and idle, and the ramdisk is why

launchd does not crash: PID 1 dying panics the kernel and no panic occurs. The
CPU sits at 0xfffffe0009ecce8c in EL1t, the scheduler's deadline wait, so the
kernel is idle and launchd is blocked rather than spinning.

What it is blocked on is a property of this root, not a fault. The image is
Apple's software-update ramdisk, and its contents say what it is for:

    restored          2        SoftwareUpdate    17
    notifyd           0        configd            0
    diskarbitrationd  0        softwareupdated    0

No general-purpose daemons at all. `restored` is the restore daemon, and a
restore environment waits to be driven by an external host over USB - it is
built to sit still until something talks to it. There is nothing here for
launchd to start on its own.

So 8.5 is not blocked by a defect in this project. It is blocked by the choice
of root, which was made because this image is unencrypted, self-contained and
needs no partition map - exactly the right choice for proving 7 and 8, and the
wrong one for 9 onward.

**For stages 9 to 11 the root has to change.** The installer carries the real
system as `AssetData/boot/094-19975-168.dmg.aea`, 285 MB, and `.aea` is Apple
Encrypted Archive. That, or the system volume inside the installer application,
is what carries notifyd, configd, WindowServer and the rest. Getting one of them
onto a disk the kernel can mount is the next piece of work, and it is
placement - the same shape as the ramdisk, at a larger size.

### What the installer actually contains, and where stages 9-11 stand

Looked for a full system to boot instead of the restore ramdisk. The largest
members are:

    4,294,967,295  payloadv2/image_patches/cryptex-system-rosetta   (zip64 marker)
    1,525,685,858  payloadv2/image_patches/cryptex-system-arm64e
    1,186,686,256  payloadv2/basesystem_patches/arm64eBaseSystem.dmg
      285,212,672  boot/094-19975-168.dmg.aea
      213,909,531  usr/standalone/update/ramdisk/arm64eSURamDisk.dmg

`arm64eBaseSystem.dmg` is not an image. Its first bytes are `BXDIFF50` - a
binary patch against an existing BaseSystem, which this machine does not have.
The `.aea` is an Apple Encrypted Archive. So there is no ready-made bootable
system in the package.

The system itself is there, as 52 chunks in `payloadv2/`, 7.9 GB compressed,
which the installer assembles. Their container is decodable: magic `pbzm`, an
8 MiB chunk size, then repeating (uint64 uncompressed, uint64 compressed,
block) - written down in pbzx.py, and the framing parses correctly.

**The blocks do not.** Each begins `2b 00 ca ec`, which read little-endian is
0xECCA002B - LZBITMAP, Apple's own compression. Not XZ, not LZFSE, not in any
standard library, and not something to guess at.

So stages 9 to 11 need one of three things, and none of them is more device tree
work:

* an implementation of LZBITMAP, to assemble the system from the payload
* a full arm64e BaseSystem or recovery image obtained separately
* the AEA payload's key, which is not in the package

That is a supply problem, not a boot problem. Everything the kernel side needed
is now proven: the machine boots, mounts a real APFS root, and runs PID 1 out of
it.

### The IPSW, and why launchd stops in the same place regardless of the root

`UniversalMac_27.0_26A5388g_Restore.ipsw`, 22.7 GB. Its BuildManifest gives the
whole set for `vma2macosap`, variant "Customer Erase Install":

| role | file | encrypted |
|---|---|---|
| RestoreRamDisk | 094-20137-168.dmg, 220 MB | no |
| RestoreTrustCache | Firmware/094-20137-168.dmg.trustcache | no |
| KernelCache | kernelcache.release.vma2 | no |
| DeviceTree | Firmware/all_flash/DeviceTree.vma2macosap.im4p | no |
| BaseSystem | 022-20879-148.dmg.aea, 1.3 GB | **yes** |
| OS | 094-19942-102.dmg.aea, 10.2 GB | **yes** |
| Cryptex1,SystemOS | 094-19967-108.dmg.aea, 2.4 GB | **yes** |
| Cryptex1,RosettaOS | 094-86300-103.dmg, 7.7 GB | no |
| Cryptex1,AppOS | 094-20071-170.dmg, 52 MB | no |

The restore ramdisk is a real one - IM4P of type `rdsk` wrapping APFS, NXSB at
offset 32, trust cache of 528 entries against the software-update ramdisk's 410,
carrying `restored`, `configd` and `WindowServer`.

**It boots exactly as far as the other one and no further**: 17,910 bytes, 265
lines, stopping at `libignition: 1: ignition level : 0x5`. The same figures to
the byte. `-s` for single user changes nothing; libignition runs before that.

That is the finding worth having. Two roots, built for different jobs, with
different trust caches and different contents, stop at the same instruction in
the same library. **The obstacle is not on the disk.** It is something launchd
asks of the machine.

Candidates are already in the log from earlier stages:

    AppleImage4: magazine[pdmg]: failed to read nonce slot data: 2  (and eleven more)
    ACMTRM: isSEPAvailable: isSEPAvailable = NO
    AppleImage4: root power domain not yet available: 19
    Couldn't alloc class "AFKResource"

libignition brings up the sealed system - it mounts and verifies cryptexes - and
verification wants the keystore, which wants the SEP, which this machine does
not have and has said so twice.

### 8.5 - launchd is genuinely blocked, and the ramdisk is now readable

**launchd is blocked, not quietly working.** The distinction matters: PID 1's own
logging goes to the system log, not the kernel console, so a working launchd and
a stuck one look identical from the serial line. Twenty PSTATE samples through
the monitor across a boot: **EL0 zero times, EL1 twenty**, ten distinct kernel
PCs. User code never runs. Fifteen minutes of patience changes nothing - the log
is byte-identical at 320 seconds and at 900.

**It is not the ignition stages.** 7-Zip reads APFS, so the ramdisk is directly
inspectable, and libignition turns out to be built into `usr/lib/dyld` rather
than shipped separately. Its strings give the sequence:

    __stage_hello  __stage_preboot  __stage_cryptex1_sniff
    __stage_graft  __stage_graft_fetch  __stage_graft_select
    __stage_dylib_cache  __stage_rosetta  __stage_goodbye

and the boot arguments: `ignition_level`, `ignition_halt_after`,
`ignition_force_dylib_root`, `ignition_live_app_graft`,
`ignition_prereboot_graft`.

`ignition_level=0` is read - the guest prints `ignition level : 0x0` instead of
`0x5` - and the boot stops in exactly the same place. **Cryptex grafting is
eliminated**; it was the leading hypothesis.

Three roots, two ignition levels, single-user mode and fifteen minutes: the same
result every time. Both ramdisks carry only restore daemons -
`restored_external`, `diskimagesiod`, `kernelmanagerd`, `syslogd`, `vsdbutil` -
and no general-purpose services, which is another guess ruled out by reading
rather than booting.

**Next:** the ten kernel PCs seen while launchd is blocked say what the kernel is
doing during the block. No new tooling needed.

### 8.5 - the block is characterised; five hypotheses eliminated

launchd is executed, runs dyld, prints the ignition arguments, and then no user
code runs again. The kernel PCs during the block are the scheduler's deadline
wait at 0xfffffe0009ecce8c - ten of sixteen samples - and a timer read at
0xfffffe000a01bd08, `mrs x11, cntvct_el0` inside a delay loop, three more. The
machine is idle and waiting, not spinning and not faulting.

Eliminated, each by measurement:

| hypothesis | how it died |
|---|---|
| the root's contents | three roots, including both Apple ramdisks with 410 and 528 entry trust caches, stop identically |
| cryptex grafting | `ignition_level=0` is accepted - the guest prints `0x0` instead of `0x5` - and nothing changes |
| single user mode | `-s` changes nothing; libignition runs before that decision |
| slowness | fifteen minutes gives a log byte-identical to five |
| launchd working silently | needed ruling out properly, since PID 1 logs to the system log not the console. EL0 never executes in sixteen samples |

Also checked and absent: **the kernel has no override for the init program**.
Four occurrences of `/sbin/launchd`, no `init_path`, no `launchdsuffix`, no
`/bin/sh`. A shell cannot be substituted to prove userland another way.

Both ramdisks carry only restore daemons - `restored_external`, `diskimagesiod`,
`kernelmanagerd`, `syslogd`, `vsdbutil`. Even unblocked, neither produces a
desktop; they are built to be driven by a host over USB.

**Stage 9 needs the real system volume**, and that stays a supply problem: OS and
BaseSystem in the IPSW are Apple Encrypted Archives.

New capability, reusable: **7-Zip reads APFS**, so both ramdisks are directly
inspectable. That is how libignition was found inside `usr/lib/dyld` rather than
as a library, giving the whole stage list and its five boot arguments.

### Stage 9 groundwork: the AEA header is open, the key is not offline

The encrypted images in the IPSW are Apple Encrypted Archives, and their headers
parse cleanly. `022-20879-148.dmg.aea` - BaseSystem, 1.3 GB - has profile 1 and
five auth-data entries:

    com.apple.wkms.url            https://wkms.sd.apple.com
    com.apple.wkms.auth-data      1040 bytes
    saksKey                       1119 bytes
    com.apple.wkms.fcs-response   190 bytes
    com.apple.wkms.fcs-key-url    83 bytes

The key URL is public and serves a PEM EC P-256 **private** key, 241 bytes,
which fetches with a plain GET. The fcs-response is JSON:

    {"enc-request": <base64>, "wrapped-key": <base64>}

`enc-request` decodes to exactly 65 bytes - an uncompressed P-256 point - and
`wrapped-key` to 48, which is 32 bytes of ciphertext and a 16-byte tag. The
served public key is *not* that point, so ECDH between them is well formed and
the shared secret computes.

**It does not unwrap.** 118 combinations were tried and none verified:
X9.63-SHA256 and HKDF-SHA256, shared info of the ephemeral point, the point
without its 0x04 prefix, empty, and the auth-data; key lengths 16 and 32; IVs
derived, all-zero, 12 and 16 bytes; and AES-GCM with five choices of additional
authenticated data.

The field name is the likely explanation. `enc-request` reads as an encrypted
*request*, not as a bare ephemeral key, and `com.apple.wkms.url` names a service
to send it to. If so the content key is issued by Apple's key service rather than
derived locally, and getting it means posting that request - an outward
interaction with an Apple service, which is a different kind of step from
fetching a public file and is left for the user to decide on.

Adds aea_key.py, which parses the header, fetches the served key and implements
the ECIES unwrap. Everything in it is verified except the final derivation.

### AEA, further: the service route is closed, so the unwrap is offline

`com.apple.wkms.url` is `https://wkms.sd.apple.com`, and that host **does not
resolve** - `.sd.` is an Apple-internal domain, unreachable from outside. So the
content key cannot be requested from a service; it has to come out of the
material already in hand. Which is consistent with why the private key is served
publicly at all: a Mac has to read these images with no credential.

`com.apple.wkms.auth-data` and `saksKey` decode to protobuf - first byte 0x0a,
field 1, wire type 2 - carrying a key identifier `0010-0001-0002` and a 32-byte
hex digest `d3fdc97fa0f316d8...`. They describe the key rather than contain it.

So the wrapping of `wrapped-key` is the whole problem, and 133 combinations have
now failed:

* KDFs: X9.63-SHA256, HKDF-SHA256
* shared info: the ephemeral point, the point without its 0x04 prefix, empty,
  the auth-data
* key lengths 16 and 32; IVs derived, all-zero, 12 and 16 bytes
* AES-GCM with five choices of AAD
* AES-CBC, checked by PKCS7 padding validity rather than by a tag

The 48-byte length reads either way - 32 of ciphertext plus a 16-byte GCM tag,
or 32 padded to a block under CBC - and neither verifies, so the length is not
the discriminator it looked like.

What is verified and reusable regardless: the header parser, the auth-data
walker, the served-key fetch, and the ECDH, whose shared secret computes because
the served public key is demonstrably not the ephemeral point.

### AEA: Apple's own implementation is on the ramdisk, and readable

7-Zip's APFS support made the restore ramdisk extractable - 1900 files - and it
carries the code that reads these archives:

    usr/lib/libAppleArchive.dylib                                847,040
    System/Library/PrivateFrameworks/DiskImages2.framework      5,371,872
    usr/libexec/diskimagesiod                                   3,102,384
    usr/local/bin/restored_external                             2,731,024

diskimagesiod names the mechanism in its symbols: `AEAHelper::wkms_t`,
`AEAHelper::kms_t`, `AEAHelper::saks_metadata_t`,
`getAEAKeyFromSAKSWithMetadata:key:error:`, and the messages "attempting to
authenticate with wkms", "crypto_format: Can't decrypt wrapped key", "Convert
AEA key from hex failed".

Three facts change the picture:

* **The crypto is CryptoKit, not Security.** The imported SecKey algorithm
  constants are RSA only; the P-256 work goes through Swift
  `P256.KeyAgreement` in x963 representation, with
  `convertPrivateKeyTox963WithPemPrivateKey:` turning the served PEM into that
  form. The derivation after ECDH is Apple's own code, not the system's ECIES -
  which is exactly why none of the standard combinations verify.
* **There are three key sources.** wkms, kms and SAKS. wkms needs
  `wkms.sd.apple.com`, which does not resolve. SAKS reads the `saksKey` auth
  entry. Which one a customer IPSW takes is the open question, and the answer is
  in this binary.
* **The key is handled as hex.** "Convert AEA key from hex failed" sits beside a
  64-character hex string in the auth-data protobuf,
  `d3fdc97f...70b8e13`, with a key identifier `0010-0001-0002`. Thirty-two bytes,
  the right size - though a public field is likelier its digest than the key.

So the 133 failed combinations now have a reason rather than a mystery. Reading
the real derivation means disassembling diskimagesiod around the wrapped-key
handling. The Mach-O groundwork is done - machobase.py gives the __TEXT slide,
0x100000000 here, and locates the strings at 0x100260de4, 0x100260ebf and
0x100271f3c - but the kernel's adrp+add scan does not find their callers, so
userland addressing needs its own pass.

### AEA, narrowed: the C++ path is not it, the Swift path is

Chased "crypto_format: Can't decrypt wrapped key" into diskimagesiod. uxrefs.py -
which scans for the ADRP page and then looks a short way ahead for the matching
ADD, finding what the kernel scanner misses in userland - puts its only
reference at 0x1001eb160, and the call before it, 0x10020fb40, is a PLT stub
through the GOT at 0x1002c87d0.

**That is the wrong path, and the imports say so.** The whole binary imports only
these corecrypto and CommonCrypto primitives:

    _CCCrypt  _CCKeyDerivationPBKDF  _ccsha1_di
    _ccaes_cbc_decrypt_mode  _ccaes_cbc_encrypt_mode
    _ccaes_xts_decrypt_mode  _ccaes_xts_encrypt_mode

No GCM anywhere, and PBKDF2 alongside CBC and XTS is the signature of encrypted
*disk image* handling, not AEA. So `crypto_format` refers to the DMG's own
crypto, and the AEA key never goes through this code.

The AEA path is the Swift one, and its symbols are the evidence:
`P256.KeyAgreement.PrivateKey` and `PublicKey` in `x963Representation`, with
`convertPrivateKeyTox963WithPemPrivateKey:` converting the served PEM. CryptoKit
inlines its derivation, so the salt and shared-info are not string literals and
do not appear near the wkms strings - which were checked, 3 KiB either side, and
carry only unrelated diagnostics.

So the unwrap is HKDF or X9.63 inside CryptoKit with parameters that have to be
read out of compiled Swift rather than found as data. That is a different kind of
reading from everything this project has done so far, and it is where stage 9
now sits.

New tools, all reusable for any userland binary: machobase.py for the __TEXT
slide and string addresses, uxrefs.py for references, and `--virt-base` on
dis_range.py so the disassembler works outside the kernel.

## The AEA content key is recovered

    aa1f972bfa7116a8247b576c66d420ce8e4a37aa9fdda0dd9113a0979a565c97

for `022-20879-148.dmg.aea`, the BaseSystem of macOS 27.0 26A5388g.

The scheme is **HPKE**, RFC 9180, and Apple's binary names it outright.
`usr/libexec/diskimagesiod` imports:

    CryptoKit.HPKE.Ciphersuite.P256_SHA256_AES_GCM_256
    CryptoKit.HPKE.Recipient(privateKey:ciphersuite:info:encapsulatedKey:)
    CryptoKit.HPKE.Recipient.open(_:)

So the archive's `enc-request` is the encapsulated key, `wrapped-key` is the
sealed ciphertext, the key served at `com.apple.wkms.fcs-key-url` is the
recipient key, the mode is base and the info is empty.

**Why 133 sweeps failed.** HPKE is not ECIES, and no amount of sweeping over
ECIES would have found it. Its KEM hashes the encapsulated key *and* the
recipient's public key into the shared secret; the key schedule then mixes a mode
byte, a PSK-id hash and an info hash before deriving the AEAD key and nonce.
Neither of those steps exists in X9.63 or plain HKDF. The answer came from
reading the imports, not from trying harder.

hpke.py implements it standalone: DHKEM(P-256, HKDF-SHA256), HKDF-SHA256,
AES-256-GCM, labelled extract and expand, base-mode key schedule.

### Still to do for stage 9

The container itself. libAppleArchive names the parts - `aeaDeriveMainKeyExisting`,
`aeaRootHeaderInit`, `aeaContainerParamsInitWithRootHeader`, "derivating RHEK",
"Cluster header encryption", "generating last cluster random MAC" - so the layout
is a root header, then clusters, each with its own header and segments. The HKDF
labels `RHEK` and `SK` appear as strings; the rest are inline constants and will
have to be read from code.

With that, BaseSystem decrypts to an APFS image and goes to the kernel exactly
the way the two restore ramdisks already do - that path is built and proven.

### AEA container: the root header's shape, read from libAppleArchive

`aeaContainerParamsInitWithRootHeader` at 0xf1e8 validates the decrypted root
header, and its field offsets are plain:

    +0x18  compression algorithm, an ASCII character
           '-' none, '4' lz4 (block 0x100), 'a' and 'e' further cases
    +0x19  checksum mode: 0 none, 1 gives 8 bytes, 2 gives 32

and the raw container after the auth data - at offset 0xa24 here, which is
12 + 2584 - is high-entropy from the first byte, so the root header is encrypted
from the start rather than having a plaintext prologue.

What remains for stage 9 is the derivation of RHEK from the content key and the
cluster walk. libAppleArchive names every part - `aeaDeriveMainKeyExisting`,
"derivating RHEK", "Cluster header encryption", "generating last cluster random
MAC" - and it is now readable: dis_range works on userland Mach-O with
--virt-base, machobase.py gives the slide, uxrefs.py finds the references. The
same three tools that carried stages 6, 7 and 8.


## Stage 9 done, and stage 8's block found

The AEA container is decrypted and macOS 27's own Base System boots from it.
`aea.py` walks the container, `udif.py` flattens the UDIF map, `gpt.py` reads the
partition. All 1,730 segments verify against their recorded SHA-256. The volume
is macOS 27.0 build 26A5388g, 42,484 files, carrying Install macOS 27 Golden
Gate Beta.app, and the kernel mounts it as root and runs its `/sbin/launchd`.

Three boot faults were fixed to get there and one kernel patch:

    boot_args needs a framebuffer   without --fb the kernel stops at IOKit, and
                                    that - not ramdisk size - explains every
                                    stalled boot that was blamed on size
    the trust cache is a segment    eight bytes of header before the module; the
                                    panic arithmetic proves the layout exactly
    an empty RAMDisk entry panics   phystokv(0); made conditional, as TrustCache
                                    already was
    one NOP at 0x9b48d14            a sealed volume with no snapshot cannot take
                                    the snapshot path; the live path works and
                                    keeps NOHEADER honoured because the volume
                                    stays sealed

Kernel modification is 85 bytes of 80,871,424.

Stage 8's block is now traced end to end rather than guessed:

    launchd's single thread   state WAIT
    blocks in                 lck_mtx_gate_wait - the only gate wait the guest
                              performs in the whole boot
    reached from              the sole caller, a static VM routine beside
                              upl_phys_page, entered through a pager operation
    the gate's first word     names a thread of the kernel task, itself
                              WAIT|UNINT, whose continuation lands in the VM
                              pressure monitor

So a page fault in launchd waits on a paging gate held by a kernel thread that
is itself asleep. Whether that first word is really the owner is the one link
not independently confirmed, and it is the next thing to check.

Getting there needed three fixes to the instrument itself, each of which had
produced a confident wrong answer first: thread_block is a three-instruction
wrapper around thread_block_reason; assert_wait is a wrapper that hashes the
event and tail-calls waitq_assert_wait64, which is where every other wait path
enters; and the trace ring lived in a zero run inside __DATA, which is BSS, so
it was overwriting the kernel data it was meant to observe.

Excluded by measurement, not argument: the sealed volume, the trust cache, the
ignition sysctls (sysctl_handle_string is never called), ignition_level, the
cryptex graft options, /product/util, QEMU's default NIC, a second CPU, the
timer frequency, the debug boot-arg, swap (vm_compressor=2 takes effect and
changes nothing), scheduler starvation, and a quiet death - panic and
panic_with_options are instrumented and never called.

New tools: symbols.py (212,222 names out of the collection's 216 nested
Mach-Os), trace_wait.py, guest.py, syscalls.py, constscan.py, findlabel.py,
tcseg.py, apfs_seal.py, apfs_omap.py.

### The gate finding, confirmed and narrowed

Two things that were provisional are now settled.

The owner field is real. `lck_mtx_gate_close` does

    casa x8, x19, [x1]        ; x19 is tpidr_el1, the current thread
    ands x8, x8, #-4          ; the low two bits are flags
    orr  x8, x19, #1          ; and get set when there are waiters

so the gate's first word holds the owning thread with two flag bits, and reading
it masked was correct.

It is not the sealed volume. Running the same instrumentation against the
unsealed restore ramdisk produces the identical single gate wait, from the same
caller, so the deadlock belongs to the machine rather than to the decrypted
Base System or to the NOP that lets a sealed volume mount live.

The holder is in vm_pageout.c. The strings reachable from its continuation name
it: VM_pageout_scan, VM_pageout_external_iothread, vm_pressure_thread. So a page
fault in launchd waits on a paging gate held by a pageout thread that is itself
asleep.

Three fixes suggested by that reading were tried and none of them moves it:
8 GB of guest memory rather than 4 - the earlier 8 GB test predated the
framebuffer fix and measured nothing; vm_compressor=2, which takes effect (the
kernel logs mode 2) and disables swap; and vm_compressor=1, which disables the
compressor outright.

One measurement of this stretch was invalid and is worth recording as such: the
first attempt to test the restore ramdisk reused a scratch address computed for
the 1.85 GB ramdisk. With a 210 MB ramdisk that address is not mapped, the
instrument took a data abort on its first store, and the "zero gate waits" it
reported was the instrument dying rather than the guest behaving differently.

### Stage 8's block, closed as a diagnosis

Three counts, each from its own instrumented boot, and together they are
conclusive:

    gate acquisitions   1     from AppleImage4's _darwin_el2_boot
    gate releases       0     lck_mtx_gate_open is never called, ever
    gate waits          1     launchd, and it never returns

So one gate is taken once during the entire boot and never given back, and
launchd's page fault is the single thing waiting on it.

The acquirer is named by its own strings - boot-type, boot-command,
osenvironment, darwinos-ramdisk, image4-allow-magazine-updates, entangle-nonce,
BATS_NVRAM_REINITIALIZED - and immediately under the gate it calls
activator_init_images, whose strings are "failed to parse manifest", "failed to
impose manifest for activation", "failed to execute object". This is Image4
secure-boot activation, and it matches the complaint the kernel already prints
early on: "AppleImage4: magazine[pdmg]: failed to read nonce slot data: 2".

The holder does not return from under the gate. Its saved continuation lands in
vm_pageout.c, so it is asleep in the VM while holding an Image4 gate, and
launchd is behind it.

Stubbing activator_init_images to return success immediately does not move the
boot, so the holder blocks either before that call or in the loop after it. That
is the remaining question, and it is now a question about one function rather
than about the system.

Also settled here: 8 GB of guest memory, vm_compressor=2 and vm_compressor=1 all
take effect and change nothing, so it is neither page exhaustion, nor swap, nor
the compressor.

### Memory is not the constraint

The 8 GB run was checked rather than assumed this time. The kernel reports

    vm_page_bootstrap: 397526 free pages, 126762 wired pages

which is 6.4 GB free against 2.0 GB wired for the ramdisk, and the block is
unchanged. So the thread holding the gate is not waiting for free pages.

Its continuation is a compare-and-swap loop over two globals, keyed on a
per-thread word at +0x4e8 - a one-at-a-time admission gate rather than an I/O
wait. Neither global carries a symbol.

One correction to the earlier note: lck_mtx_gate_close and lck_mtx_gate_wait
take the mutex in x0 and the gate in x1, so the address recorded by the
instrument was the mutex, not the gate. The three counts are unaffected - they
count calls - and the acquirer's state was read from the acquiring thread
itself, which is what matters: WAIT | UNINT, asleep under its own gate.

### What parks the gate holder: a single-processor VM restriction

The thread that closes the Image4 gate blocks a few instructions later, and the
branch that sends it to sleep is guarded by a global:

    ldr  w8, [x8, #0xba8]
    cmp  w8, #1
    b.ne skip
    bl   <block>

and that global is written from a value the kernel derives itself:

    vm_restricted_to_single_processor
    "Overriding vm_restricted_to_single_processor to %d"
    vm: osenvironment == "diagnostics or device-recovery". Setting "vm_compre...
    osenvironment from /chosen: %u

So the VM restricts itself to a single processor when it believes it is running
in a diagnostics or device-recovery environment, and in that mode the pageout
thread parks - while holding the gate that launchd's first page fault needs.
The comparison is `cmp w19, #4; cset w8, lo`, so anything below four selects the
restricted mode, and an absent property reads as zero.

build_image now has --os-environment, and devicetree sets /chosen/os-environment
from it. Setting it to 4 does not move the boot and the kernel does not print
"osenvironment from /chosen", so either the property is spelled differently in
the tree or the value is taken from somewhere else. The boot-arg
vm_restricted_to_single_processor=0 is likewise not picked up - no override line
appears - so the argument is parsed by something other than the usual boot-arg
reader.

The mechanism is identified; which input feeds it is not.

### The nonce blob is a dead end, and the code says so

The three "magazine[...]: failed to read nonce slot data: 2" lines trace to
nonce_blob_read, which reads an NVRAM variable named

    40A0DDD2-77F8-4392-B4A3-1E7304206516:nonce-seeds

into a 0x253-byte buffer and requires at least 0x16f bytes back. Our NVRAM proxy
is emitted empty, so the read returns 2.

That is not the blocker. The reader tests for exactly that code and branches to
its own message:

    bl   <read variable>
    cmp  w0, #2
    b.eq -> "no legacy blob present"

so an absent blob is a state the kernel expects from a machine that has never
been booted, prints about, and continues past. Fabricating a blob would be
inventing cryptographic material to satisfy a path that is already satisfied.

Recorded because the trail looked promising and the negative is worth keeping:
it removes the last obvious candidate reachable from the gate holder's strings.
