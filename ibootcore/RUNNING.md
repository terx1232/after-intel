# Running the build

## VirtualBox cannot do this

Not "is difficult" - cannot, by construction.

VirtualBox is a type-2 hypervisor. Guest instructions execute **directly on the
host CPU** through VT-x or AMD-V. There is no CPU emulator inside it and no ARM
front end, so an ARM64 guest on an x86 host has nothing to run its instructions.

Two ways to confirm this without taking anyone's word for it:

- On an x86 host, VirtualBox's guest-OS type list contains no ARM entry at all.
- VirtualBox for Apple silicon runs ARM guests happily - on an ARM host. The
  rule is the same in both directions: guest ISA must equal host ISA.

The same applies to VMware Workstation, Hyper-V and Parallels on x86. They are
virtualisers, not emulators.

## QEMU with TCG can

TCG is QEMU's dynamic binary translator. It genuinely executes ARM64 guest code
on an x86 host - slowly, but it executes.

### 1. Build the image for the machine you will run

QEMU's `virt` machine places RAM at `0x40000000`, so the image has to be built
for that base rather than the default:

```bash
python ibootcore/build_all.py InstallAssistant_27.0_26A5388g.pkg --out build
python ibootcore/build_image.py build/vma2.kernel \
    --out build/vma2-image-virt.bin \
    --phys-base 0x40000000 --mem-size 4G --fb 1024x768 \
    --cmdline "-v debug=0x8 serial=3"
```

That prints the layout and the handoff state:

```
kernel        0x40000000            0    80,871,424
device tree   0x44e00000   81,788,928         2,288
boot_args     0x44e01000   81,793,024         1,152

PC = 0xfffffe0009e3c480   (kernel entry, virtual)
x0 = 0x0000000044e01000   (physical address of boot_args)
```

### 2. Build the trampoline

QEMU's image loader can set the program counter but has no way to preload a
general-purpose register, and XNU wants the `boot_args` pointer in `x0`. Nine
instructions bridge that gap:

```bash
python ibootcore/trampoline.py \
    --x0 0x44e01000 --entry 0xfffffe0009e3c480 \
    --out build/trampoline-virt.bin
```

```
  0: d2820000   movz  x0, #0x1000
  4: f2a09c00   movk  x0, #0x04e0, lsl #16
  ...
 32: d61f0020   br    x1
```

### 3. Run it

```bash
qemu-system-aarch64 \
  -M virt,gic-version=3 -cpu max -accel tcg -m 4G \
  -nographic -d int,mmu,guest_errors -D qemu.log \
  -device loader,file=build/vma2-image-virt.bin,addr=0x40000000,force-raw=on \
  -device loader,file=build/trampoline-virt.bin,addr=0x3f000000,force-raw=on \
  -device loader,addr=0x3f000000,cpu-num=0
```

The last `-device loader` sets the CPU's start address to the trampoline, which
sets `x0` and branches to the kernel entry.

`-d int,mmu,guest_errors` is the point of the exercise: it logs exceptions,
translation faults and guest errors to `qemu.log`, which is how you find out
where the kernel died rather than merely that it did.

## What to expect

**It will not boot.** Stating that plainly so the log does not come as a
surprise.

`virt` is not `vmapple`. The device tree this repository emits carries the right
node *names* but invented property values, the peripherals sit at QEMU's
addresses rather than Apple's, there is no Image4 chain, no trustcache, and no
page tables are set up. The kernel should fault early.

That is still the milestone that was aimed at: **instructions retiring inside
the kernel image, and a fault with an address you can look up.** A translation
fault at a known virtual address is a diagnosable result. It tells you which
structure the kernel read and disagreed with, and that is the only way this gets
incrementally better.

If `qemu.log` shows nothing executing at all, the problem is upstream of any of
this - image placement or the trampoline - and that is worth knowing too.

## The honest ceiling on this route

Even with every fault chased down, `virt` will not become `vmapple`. Getting
further needs QEMU's own `vmapple` machine, which is currently `hvf`-only and so
requires an Apple silicon host, plus `AVPBooter.vmapple2.bin` which only exists
on a Mac. Writing a TCG path for that machine is ordinary engineering, and it is
unwritten.

Nothing in this document has been executed. QEMU is not installed in the
environment this was developed in.
