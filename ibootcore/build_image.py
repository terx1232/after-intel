#!/usr/bin/env python3
"""
build_image.py -- assemble a flat memory image for an arm64e kernel collection:
kernel, device tree and boot_args placed at fixed physical addresses.

Step six of IbootCore. Given a decompressed kernel collection, this lays out
what a machine's RAM must contain at the moment control is handed over, and
writes it as one flat file that an emulator can load at `--phys-base`.

Layout produced:

    phys_base + 0x00000000   kernel collection (77 MiB for vma2)
    <aligned up to 1 MiB>    flattened device tree
    <aligned up to 4 KiB>    boot_args (1152 bytes)

At entry the CPU should have PC = the kernel's entry point and x0 = the
physical address of the boot_args block. Both are printed.

This ships no Apple code. It reads a kernel you already have and writes an
image locally; nothing is redistributed.

Usage:
    python build_image.py vma2.kernel --out image.bin
    python build_image.py vma2.kernel --out image.bin --fb 1024x768 --cmdline "-v"
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootargs
import devicetree
import loadmap


def align(n: int, a: int) -> int:
    return (n + a - 1) & ~(a - 1)


def parse_fb(s: str):
    if not s:
        return None
    w, _, h = s.lower().partition("x")
    return int(w), int(h)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel", help="decompressed kernel collection")
    ap.add_argument("--out", required=True)
    ap.add_argument("--phys-base", default="0x800000000",
                    help="where the image is loaded")
    ap.add_argument("--ram-base", default=None,
                    help="where physical RAM starts, if that is not the load "
                         "address; boot_args.physBase gets this and virtBase "
                         "shifts to match")
    ap.add_argument("--mem-size", default="4G")
    ap.add_argument("--cmdline", default="-v debug=0x8 serial=3")
    ap.add_argument("--fb", default="", metavar="WxH",
                    help="framebuffer geometry for the boot console, e.g. 1024x768")
    ap.add_argument("--fb-addr", default="0x900000000")
    ap.add_argument("--ncpus", type=int, default=1)
    ap.add_argument("--trampoline", metavar="PATH",
                    help="also emit the entry stub, with x0 and the entry point "
                         "taken from this image rather than typed in again")
    ap.add_argument("--fb-init", action="store_true",
                    help="have the trampoline program a bochs-display card "
                         "before entering the kernel, so the framebuffer named "
                         "in boot_args actually exists")
    ap.add_argument("--fb-device", type=lambda s: int(s, 0), default=3,
                    help="PCI device number the display card sits at")
    ap.add_argument("--fb-mmio", default="0x32000000",
                    help="where to map the card's register BAR")
    ap.add_argument("--fb-fill", default="0",
                    help="colour the stub paints the screen before entry. 0 is "
                         "black, which is what a Mac shows. Any other value "
                         "turns the fill into a visible self-test: a screen that "
                         "comes up in that colour proves the BARs, the mode and "
                         "memory decode are all right, which black cannot prove "
                         "because it looks the same as nothing working.")
    ap.add_argument("--boot-logo", metavar="PATH",
                    help="a decoded iBootIm payload; the stub composites it "
                         "over the fill colour and copies the result into the "
                         "framebuffer before entering the kernel, which is what "
                         "iBoot does on a real Mac")
    ap.add_argument("--fg", default="0xffffff",
                    help="colour the logo mask is composited in")
    ap.add_argument("--ecam", default="0x3f000000")
    ap.add_argument("--trampoline-at", default="0x41000000",
                    help="where the stub will be loaded, for the printed command")
    args = ap.parse_args(argv)

    phys_base = int(args.phys_base, 0)
    mem_size = bootargs.human_size(args.mem_size)

    kern = open(args.kernel, "rb").read()
    m = loadmap.parse(args.kernel)
    virt_base = m["vm_low"]
    entry = m.get("entry")

    # The collection maps one to one, which build_image relies on. Verify it
    # rather than assume it -- a collection that does not would need per-segment
    # placement and this layout would be silently wrong.
    if m["vm_span"] != len(kern):
        print(f"error: virtual span {m['vm_span']} != file size {len(kern)};\n"
              f"       this collection does not map 1:1 and needs per-segment "
              f"placement.", file=sys.stderr)
        return 2

    fb = parse_fb(args.fb)
    fb_addr = int(args.fb_addr, 0)

    # The device tree must agree with boot_args about where RAM starts. Passing
    # the load address here while boot_args carried the true RAM base left the
    # two describing different machines, with the tree claiming DRAM ran from
    # the image for the full memory size and so past the real end of RAM.
    ram_base = int(args.ram_base, 0) if args.ram_base else phys_base
    if ram_base > phys_base:
        ap.error("--ram-base cannot be above the load address")

    tree = devicetree.minimal_vmapple_tree(ram_base=ram_base,
                                           ram_size=mem_size,
                                           ncpus=args.ncpus)
    if fb:
        w, h = fb
        node = devicetree.Node("framebuffer")
        node.set_str("device_type", "display")
        node.set_u64("address", fb_addr)
        node.set_u32("width", w)
        node.set_u32("height", h)
        node.set_u32("depth", 32)
        node.set_u32("stride", w * 4)
        tree.children.append(node)
    dt_blob = tree.serialise()

    kern_end = align(len(kern), 1 << 20)
    dt_off = kern_end
    ba_off = align(dt_off + len(dt_blob), 1 << 12)
    total = align(ba_off + bootargs.SIZEOF_BOOT_ARGS, 1 << 20)

    dt_addr = phys_base + dt_off
    ba_addr = phys_base + ba_off

    # Now that the placements are known, write them into chosen/memory-map and
    # serialise again. The entries were reserved at their final size, so this
    # cannot move anything -- which is asserted rather than assumed, because if
    # it did move, dt_addr and ba_addr would already be stale.
    memmap = next((n for _, n in tree.walk() if n.name == "memory-map"), None)
    if memmap is not None:
        memmap.props["DeviceTree"] = struct.pack("<QQ", dt_addr, len(dt_blob))
        memmap.props["BootArgs"] = struct.pack("<QQ", ba_addr,
                                               bootargs.SIZEOF_BOOT_ARGS)
        again = tree.serialise()
        if len(again) != len(dt_blob):
            raise SystemExit("device tree changed size when the memory map was "
                             "filled in; the addresses above are now wrong")
        dt_blob = again
        print(f"  chosen/memory-map: DeviceTree {dt_addr:#x} +{len(dt_blob)}, "
              f"BootArgs {ba_addr:#x} +{bootargs.SIZEOF_BOOT_ARGS}")

    video = (fb_addr, 1, w * 4, w, h, 32) if fb else (0, 0, 0, 0, 0, 0)

    # physBase and the load address are not the same thing, and conflating them
    # was a real defect. physBase describes where physical RAM *starts*; the
    # load address is wherever the loader could find room. On QEMU's `virt`
    # the machine puts its own generated dtb at the base of RAM, so the image
    # has to sit above it -- and passing that higher address as physBase told
    # the kernel that RAM began at the image, hiding every byte below it and
    # claiming the same number of bytes past the true end of RAM. The panic
    # says so out loud: "phys base 0x49004000, size 0x100000000" runs to
    # 0x149004000 while RAM stops at 0x140000000.
    #
    # virtBase shifts by the same amount so that the kernel still lands on its
    # own link address: phystokv(load) == the kernel's vm_low.
    ba_virt_base = virt_base - (phys_base - ram_base)

    # deviceTreeP is a **virtual** address, not physical. XNU copies it into
    # PE_state.deviceTreeHead, and arm_vm_init assigns
    #     segEXTRADATA = (vm_offset_t)PE_state.deviceTreeHead
    # letting it become segLOWEST, after which arm_vm_physmap_slide computes
    # `segLOWEST - gVirtBase` as a length. Passing a physical address there makes
    # that subtraction wrap: 0x4be04000 - 0xfffffe0000000000 is 0x2004be04000,
    # two terabytes, and the granular walk then steps up through level 1 entries
    # until it reaches one that was never built and panics in phystokv with
    # "illegal PA: 0x0". That was this port's stage-5 failure, and the 0x200 that
    # kept turning up in the high bits of unrelated-looking values was the top of
    # `2 << 40` surviving the wrap.
    dt_virt = ba_virt_base + (dt_addr - ram_base)
    print(f"  deviceTreeP                 {dt_virt:#018x}   (virtual, not "
          f"{dt_addr:#x})")

    ba = bootargs.build(
        virt_base=ba_virt_base,
        phys_base=ram_base,
        mem_size=mem_size,
        top_of_kernel_data=phys_base + total,
        device_tree_p=dt_virt,
        device_tree_length=len(dt_blob),
        cmdline=args.cmdline,
        video=video,
    )

    image = bytearray(total)
    image[0:len(kern)] = kern
    image[dt_off:dt_off + len(dt_blob)] = dt_blob
    image[ba_off:ba_off + len(ba)] = ba
    open(args.out, "wb").write(image)

    print(f"\n=== memory image ===\n")
    print(f"{'region':<18}{'phys addr':>20}{'offset':>14}{'size':>14}")
    print("-" * 66)
    print(f"{'kernel':<18}{phys_base:>#20x}{0:>14}{len(kern):>14,}")
    print(f"{'device tree':<18}{dt_addr:>#20x}{dt_off:>14,}{len(dt_blob):>14,}")
    print(f"{'boot_args':<18}{ba_addr:>#20x}{ba_off:>14,}"
          f"{bootargs.SIZEOF_BOOT_ARGS:>14,}")
    if fb:
        print(f"{'framebuffer':<18}{fb_addr:>#20x}{'(separate)':>14}"
              f"{w * h * 4:>14,}")
    print("-" * 66)
    print(f"{'image total':<18}{'':>20}{'':>14}{total:>14,}")

    print(f"\nwrote {args.out} ({total / 2**20:.1f} MiB)")
    print(f"\nCPU state required at handoff:")
    print(f"  PC = {entry:#018x}   (kernel entry, virtual)")
    print(f"  x0 = {ba_addr:#018x}   (physical address of boot_args)")

    # Emit the entry stub here, from the addresses this build just computed.
    #
    # Building it with a separate command means the two can disagree, and they
    # did, twice. Anything that changes the device tree's size moves boot_args,
    # and a stub built before that hands the kernel a pointer into the middle of
    # the tree. The symptoms were spectacular and misleading: a machine that
    # reset into an exception vector, 2 452 392 logged exceptions, and a
    # page-table store that appeared to be overwriting the kernel's own text.
    # None of it had anything to do with the code being investigated.
    if args.trampoline:
        import trampoline
        entry_phys = phys_base + (entry - virt_base)
        tramp_at_early = int(args.trampoline_at, 0)
        fb_words = None
        if args.fb_init and fb:
            # Program the display before jumping, the way iBoot would. Without
            # this the geometry in boot_args describes a framebuffer at an
            # address nothing is mapped at, and every pixel the kernel draws is
            # discarded -- which is why this project has only ever produced text
            # on a serial line.
            import bochs_fb
            screen = None
            if args.boot_logo:
                # The picture iBoot would have left behind. It rides in the
                # trampoline itself, after the code, and the stub copies it into
                # the framebuffer before entering the kernel -- which is the
                # order a Mac does it in, and why the kernel's progress bar ends
                # up drawn on top of the logo rather than instead of it.
                import bootscreen
                screen = bootscreen.render(open(args.boot_logo, "rb").read(),
                                           w, h, int(args.fg, 0),
                                           int(args.fb_fill, 0))
                # Size the code first. Every address load is a fixed four
                # instructions, so the probe and the real build are the same
                # length and the data offset computed here cannot go stale.
                probe = bochs_fb.build(int(args.ecam, 0), args.fb_device,
                                       fb_addr, int(args.fb_mmio, 0), w, h,
                                       at=tramp_at_early, blit_from=0)
                code_len = len(trampoline.build(ba_addr, entry_phys,
                                                fb_init=probe))
                data_at = (tramp_at_early + code_len + 15) & ~15
                fb_words = bochs_fb.build(int(args.ecam, 0), args.fb_device,
                                          fb_addr, int(args.fb_mmio, 0),
                                          w, h, at=tramp_at_early,
                                          blit_from=data_at)
            else:
                fb_words = bochs_fb.build(int(args.ecam, 0), args.fb_device,
                                          fb_addr, int(args.fb_mmio, 0),
                                          w, h, at=tramp_at_early,
                                          fill=int(args.fb_fill, 0))
            print(f"\n  display bring-up: bochs-display at ECAM device "
                  f"{args.fb_device}, framebuffer {fb_addr:#x}, "
                  f"{len(fb_words)} instructions")
        blob = trampoline.build(ba_addr, entry_phys, fb_init=fb_words)
        if args.fb_init and fb and args.boot_logo:
            pad = (data_at - tramp_at_early) - len(blob)
            blob = blob + b"\x00" * pad + screen
            print(f"    boot screen at {data_at:#x}, {len(screen):,} bytes")
        open(args.trampoline, "wb").write(blob)
        tramp_at = int(args.trampoline_at, 0)
        print(f"\n  trampoline  {args.trampoline}  ({len(blob)} bytes)")
        print(f"    x0    = {ba_addr:#x}")
        print(f"    entry = {entry_phys:#x}   (virtual {entry:#x})")
        print(f"\n  qemu-system-aarch64 -M virt,gic-version=3 -cpu max -accel tcg \\")
        print(f"    -m 4G -display none -no-reboot -serial file:serial.txt \\")
        print(f"    -device loader,file={args.out},addr={phys_base:#x},force-raw=on \\")
        print(f"    -device loader,file={args.trampoline},addr={tramp_at:#x},force-raw=on \\")
        print(f"    -device loader,addr={tramp_at:#x},cpu-num=0")
    print(f"\n  virtBase {virt_base:#018x} -> physBase {phys_base:#018x}")
    print(f"  so the loader must map that range before jumping.")

    print("\nWhat this does NOT do, stated plainly:")
    print("  - no page tables are built; the kernel is entered with whatever")
    print("    MMU state the emulator provides")
    print("  - device tree property values are placeholders, not a spec")
    print("  - no Image4 chain, no trustcache, no signature handling")
    print("  - this has never been executed; it is a correctly formatted")
    print("    memory image, which is not the same as a bootable one")
    return 0


if __name__ == "__main__":
    sys.exit(main())







