# Bring-up log

What actually happened when the macOS 27 `vma2` kernel was run under
`qemu-system-aarch64 -M virt -accel tcg` on an x86 host. Each entry is a real
failure, its diagnosis, and the fix. Nothing here is predicted; it is what the
machine reported.

> **Status: [measured].** QEMU 10.x on Windows, `-M virt,gic-version=3 -cpu max
> -accel tcg -m 4G`. Kernel is `kernelcache.release.vma2` from
> `InstallAssistant_27.0_26A5388g.pkg`.

## 1. ROM regions overlapping

```
vma2-image-virt.bin (0x40000000 - 0x44f00000)
dtb                 (0x40000000 - 0x40100000)
```

The `virt` machine generates its own device tree blob and places it at the base
of RAM, which is where the image was loaded. **Fix:** move the image up, out of
the way.

## 2. Prefetch abort at the trampoline

```
Taking exception 3 [Prefetch Abort]
...with FAR 0x3f000000
```

The trampoline had been placed at `0x3f000000`, which is *below* the `virt`
machine's RAM base of `0x40000000`. Nothing to fetch. The CPU then vectored to
`PC 0x200` with VBAR still zero, found nothing there either, and looped on
undefined instructions forever. **Fix:** place the trampoline inside RAM.

## 3. Prefetch abort at the kernel entry

```
...with FAR 0xfffffe0009e3c480
```

The trampoline executed - that address is the kernel's entry point, taken from
its own `LC_UNIXTHREAD`. But the MMU is off at reset, so a virtual address is
treated as physical and there is nothing there. XNU on arm64 expects to be
entered with the MMU off and to bring it up itself. **Fix:** branch to the
physical address of the entry point instead.

## 4. First real stop: an unimplemented hypercall

The kernel ran, and stopped cleanly:

```
movz x0, #0xc100, lsl #16     ; 0xC1000000
hvc  #0
cbnz x0, .                    ; parks here
```

`0xC1000000` is the SMCCC CPU Service Calls range. QEMU's `virt` returns
NOT_SUPPORTED, `x0` becomes -1, and the kernel deliberately hangs. This is the
paravirtualised interface `VMAPPLE.h` declares with `HAS_PARAVIRTUALIZED_PAC` -
predicted from the header before the run, and hit exactly.

Only one exception in the whole log, the PSCI call QEMU handled. The kernel was
running, not crashing.

## 5. Wrong physical placement, found by asking the guest

Stubbing that one call moved things forward: the kernel **enabled the MMU**, PC
became virtual, PSTATE went from `EL1t` to `EL1h`, the FPU came up. Then
undefined instructions in a loop.

The file offset the fault pointed at looked like a valid function prologue, so
the disassembly was checked against what the guest actually saw:

```
(qemu) x/6i 0xfffffe000a7abb78
0xfffffe000a7abb78:  45324373  .byte 0x73, 0x43, 0x32, 0x45
0xfffffe000a7abb7c:  5f5f0076  .byte 0x76, 0x00, 0x5f, 0x5f
0xfffffe000a7abb80:  37324e5a  tbnz ...
```

`_ZN27`, `AUAOutputTer` - C++ mangled symbol strings, not code. The kernel had
branched into its own string table.

```
(qemu) gva2gpa 0xfffffe000a7abb78
gpa: 0x4c7abb78
```

Expected `0x4b7a7b78` for an image based at `0x48000000`. Off by exactly
`0x1004000`. The register dump confirmed `boot_args` had been read correctly -
`X14`/`X22` held our `virtBase`, `X15`/`X23` our `physBase` - so the kernel's
own mapping simply put the image `0x1004000` higher than we did. **Fix:** load
the image at `0x49004000`.

## 6. The hypercalls are a series, not a single site

With placement corrected the kernel ran deeper, set up a proper frame pointer,
and stopped again - on the identical pattern with the next function id:

```
movz x11, #0x1
movk w11, #0xc100, lsl #16    ; 0xC1000001
hvc  #0
cbnz x0, .
```

Scanning for the pattern found **19 such sites**, all in `__TEXT_EXEC`, with
two recoverable function ids: `0xC1000000` and `0xC1000001`. Patching them one
at a time only reveals the next, so all 19 were stubbed together
(`tools/stub_hypercalls.py`).

## 7. Where it stands: a null dereference in the kernel's own fault path

```
Taking exception 4 [Data Abort]
...with ESR 0x25/0x96000006      ; translation fault, level 2
...with FAR 0x0
...with ELR 0xfffffe0009e41eb0
```

Then a second abort at `FAR 0x148`, and the kernel settles into its own handler
with `X01 = 0x96000006` - it is holding the ESR, so this is XNU's fault path
running.

The cause follows from the stub. `movz x0, #0` makes the check fall through,
but it also makes the *return value* zero, and some of these calls hand back
pointers. The kernel got NULL and dereferenced it.

### What the two faults were reaching for

Disassembling both sites says the same thing twice:

```
0xfffffe000a0129c0  f940a530   ldr x16, [x9, #0x148]     ; x9 = 0, FAR 0x148
0xfffffe0009e41eb0  3dc00020   ldr q0, [x1]              ; x1 = 0, FAR 0x0
```

The first appears twice within four instructions with a branch between, which
is the shape of a dispatch-pointer fetch from a structure. Both are loads
through pointers that a paravirtual call was supposed to hand back.

Tracing `x9` back forty instructions does not find an assignment - it arrives
from further out or from a callee, `0xfffffe000a00e87c`, which is invoked twice
just before.

That is where stubbing runs out. Returning `0` produces `FAR 0x148`. Returning
`-1` would produce a fault at `0xffffffffffffff48` instead, no better. Any
third value is another guess. Going further needs the actual contract - what
structure these calls return, how large it is, and what lives at offset
`0x148` - and that is not in the kernel, not in the XNU headers, and not
recoverable from either. It is in `AVPBooter.vmapple2.bin` and in QEMU's
`vmapple` machine.

## What this establishes

- The macOS 27 kernel executes on non-Apple hardware, brings up its own page
  tables, enables the MMU and the FPU, establishes a call stack, and reaches
  its own exception handling.
- It stops on paravirtualised services that only Apple's hypervisor provides,
  in a well-defined place, with a recoverable function id.
- Nothing is on screen and nothing on the serial console, because early boot
  never reaches either. A screendump is 99.7% black with QEMU's own
  "display not initialised" text.

## What would move it further

Not more stubs. The 19 sites need **plausible return values**, and what each
call should return is unknown - that information is inside
`AVPBooter.vmapple2.bin` and QEMU's `vmapple` machine, neither of which is
available here. Guessing at return values for calls that hand back pointers is
how the current null dereference happened.

The honest next step is the `vmapple` machine with a TCG path, which is where
this pointed from the beginning.
