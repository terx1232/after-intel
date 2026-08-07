# First launch: what to do

This is the operating instruction. Read the state section first - one of the
two paths is ready to run today and the other is not, and mixing them up wastes
an evening.

---

## State of the two paths

| Path | Ready? | What it gets you |
|---|---|---|
| **A. ARM guest under QEMU/TCG** | **yes, now** | kernel instructions execute; a fault with a diagnosable address |
| B. Statically translated x86 kernel | **no** | would eventually reach the same milestone, at far greater cost |

Path B is honest work in progress and its state is set out at the bottom. Path A
is what you can launch tonight, and it reaches the milestone that was actually
asked for: **the kernel starts.**

---

# Path A: run it

## 0. Install QEMU

Not present on this machine, so this step is yours. Windows builds:
<https://qemu.weilnetz.de/w64/>. Install, then confirm:

```powershell
qemu-system-aarch64 --version
```

If it is not on PATH, use the full path to the exe in the commands below.

## 1. Build the artefacts

Already done - they are in `D:\macos\ibootcore-build`:

```
vma2-image-virt.bin   82,837,504   kernel + device tree + boot_args, based at 0x40000000
trampoline-virt.bin           36   sets x0, branches to the kernel entry
vma2.kernel           80,871,424   the decompressed collection on its own
```

To rebuild from scratch at any point:

```powershell
python D:\macos\gg-x86-recon\ibootcore\build_all.py `
    D:\macos\InstallAssistant_27.0_26A5388g.pkg `
    --out D:\macos\ibootcore-build --kernel vma2

python D:\macos\gg-x86-recon\ibootcore\build_image.py `
    D:\macos\ibootcore-build\vma2.kernel `
    --out D:\macos\ibootcore-build\vma2-image-virt.bin `
    --phys-base 0x40000000 --mem-size 4G --fb 1024x768 `
    --cmdline "-v debug=0x8 serial=3"
```

The addresses that matter, printed by that second command:

```
kernel        0x40000000
device tree   0x44e00000
boot_args     0x44e01000
entry (PC)    0xfffffe0009e3c480
x0            0x44e01000
```

## 2. Run

```powershell
qemu-system-aarch64 `
  -M virt,gic-version=3 -cpu max -accel tcg -m 4G `
  -nographic -no-reboot `
  -d int,mmu,guest_errors,unimp -D D:\macos\ibootcore-build\qemu.log `
  -device loader,file=D:\macos\ibootcore-build\vma2-image-virt.bin,addr=0x40000000,force-raw=on `
  -device loader,file=D:\macos\ibootcore-build\trampoline-virt.bin,addr=0x3f000000,force-raw=on `
  -device loader,addr=0x3f000000,cpu-num=0
```

Line by line:

- `-M virt,gic-version=3` - the closest generic machine to what the kernel wants
- `-cpu max` - enables every feature QEMU can offer, including PAC
- `-accel tcg` - software translation; do not use `whpx` or `hax`, they need a
  matching host architecture
- `-no-reboot` - stops on a triple fault instead of looping, so the log ends
  where the failure is
- `-d int,mmu,guest_errors,unimp` - **the point of the exercise.** Logs
  exceptions, translation faults, guest errors and unimplemented behaviour.
- the three `-device loader` lines - place the image, place the trampoline, and
  start CPU 0 at the trampoline

Expect it to exit within seconds.

## 3. What to send back

```powershell
Get-Content D:\macos\ibootcore-build\qemu.log -TotalCount 200
```

Send that. What matters in it:

- **Exception lines** such as `Taking exception 4 [Data Abort]` with an ELR and
  FAR. The FAR is the address the kernel tried to touch and could not.
- **`unimp` lines** naming a system register or feature QEMU does not model.
- **How far it got.** Any exception at all means the kernel executed real
  instructions, which is the milestone.

## 4. What will happen, stated in advance

**It will not boot.** So the log is the result, not a disappointment.

`virt` is not `vmapple`. Concretely:

- the device tree carries the right node *names* but invented `reg` addresses,
  so drivers will look for GICv3 and PL011 where QEMU has not put them
- no page tables are set up; the kernel is entered with whatever MMU state
  QEMU's reset gives it
- there is no Image4 chain and no trustcache
- `AppleVirtualPlatformARMPE` will not find the platform it expects

A data abort at a known address is a *result*: it says which structure the
kernel read and disagreed with. That is the only way this improves - one fault
at a time, each one a small fix to the device tree or the layout.

If the log shows nothing executed at all, the fault is upstream, in image
placement or the trampoline, and that is worth knowing immediately.

---

# Path B: the x86 translation, honestly

You asked for this finished. It is not, and I am not going to describe it as if
it were.

## What is done

`a64_to_x64.py` is a working static translator. It decodes arm64, emits x86-64,
maps thirteen guest registers to host registers with `rbp` reserved as scratch
and `r15` holding the register file, and self-tests against known encodings.

Coverage over the 10,559,488 instructions of `__TEXT_EXEC`:

```
translated by the current subset   6,099,443   57.76%
not yet decoded by it              4,449,802   42.14%
genuinely not substitutable           10,243    0.10%
```

Two defects were found by running it and are fixed: memory-to-memory moves in
the spill paths (x86 cannot encode those; now staged through `rbp` or the
stack, verified zero across 721,398 translated instructions), and the
authenticated-branch path clobbering `rdi`, which holds guest `x5`.

## What is not done, and what each piece costs

1. **The remaining 42%** - NEON, atomics, bitfield and extended-register forms.
   Mechanical and bounded: every one of these has a direct x86 equivalent. This
   is volume, not difficulty.
2. **A code emitter.** The translator currently produces assembly text. Turning
   that into bytes is routine but unwritten.
3. **Shadow page tables.** The kernel writes ARM page tables with ordinary
   stores, so intercepting `msr ttbr0_el1` is not enough - the tables must be
   write-protected and rebuilt in x86 format on fault. Known technique, real
   component.
4. **The 16K page fiction.** `VMAPPLE.h` sets `__ARM_16K_PG__`; x86 has 4K, 2M
   and 1G. Every guest page becomes four host pages and the shim must keep that
   consistent against a kernel whose page-size constants are compiled in.
5. **LL/SC to CAS.** `ldxr`/`stxr` pairs against x86 `cmpxchg`, with the ABA
   problem. Established approaches exist; none are free.
6. **The 10,243 machine-model instructions** themselves, once 3 to 5 are in
   place.

## And the thing that does not go away

Even finished, a translated kernel running under QEMU's x86 machine will panic
at platform init, because the 216 translated kexts look for hardware that is
not there:

| the kernel looks for | an x86 machine offers |
|---|---|
| `ARM,gicv3` | APIC / IOAPIC |
| `ARM,pl011` | 16550 UART |
| `ARM,psci` | ACPI |
| `arm-io,vmapple1`, `pcie,vmapple1` | PIIX3 / ICH9 |
| `AppleVirtIOStorage` | IDE / AHCI / NVMe |
| `AppleParavirtGPU` | VGA / VMSVGA |

The intersection is empty. Path B reaches the same milestone as Path A -
instructions executing, then a platform fault - after months of work instead of
an evening.

---

# Ready

Path A is ready. Everything it needs is built and verified: the image parses
back correctly, `deviceTreeP` points at the device tree, the trampoline's
immediates reassemble to the right addresses, and the entry point comes from
the kernel's own load command.

Install QEMU, run the command in section 2, send the log.
