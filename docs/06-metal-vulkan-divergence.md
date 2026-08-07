# Where Metal and Vulkan actually diverge

> **Status: [literature].** Synthesised from published sources - Apple's Metal
> documentation, MoltenVK's issue tracker and user guide, and a 2026
> cross-vendor study. Nothing measured here. The numbers quoted are other
> people's measurements, attributed.

[docs/05-metal-surface.md](05-metal-surface.md) counted the Metal API at 218
classes and 2 558 methods, and flagged behavioural divergence from Vulkan as
"entirely uncounted and the real risk". This is that inventory, as far as
public sources support it.

It turns up one finding that changes the estimate, and it is not the one people
usually name.

## 1. Hazard tracking: the asymmetry that matters

Metal resources are created in `MTLHazardTrackingMode.tracked` by default. Metal
applies runtime safeguards that prevent memory hazards when commands access a
resource - the application does not declare dependencies, and the framework
works them out.

Vulkan does the opposite. Barriers and layout transitions are explicit, and the
application must supply not only which resources transition but the source and
destination pipeline stages for each.

**This makes the two translation directions structurally unequal, and the
existence of MoltenVK does not imply the reverse is comparable work.**

| Direction | What the app supplies | What the layer must do |
|---|---|---|
| Vulkan → Metal (MoltenVK) | explicit barriers | may simplify or discard them; Metal tracks anyway |
| Metal → Vulkan | **nothing** | must synthesise every barrier from scratch |

A Metal application relies on Metal to notice that a texture written in one pass
is read in the next. Running that application on Vulkan means the layer has to
derive that dependency itself - which is per-resource hazard tracking, in full.

### What that costs, measured by someone else

A 2026 cross-vendor study (six GPUs, four vendors) comparing per-resource
tracking against global pass-boundary barriers reports:

- wgpu's resource trackers are *"some of the hottest code in its codebase"*
- host-side cost of per-resource tracking: **5.59 µs per compute pass**, against
  0.74 µs for coarse pass-boundary barriers - a 7.5× difference
- for graphics passes, 3.75 µs against 0.58 µs

Crucially, the same study's Metal backend *"tracks hazards for resources created
in the default `MTLHazardTrackingModeTracked` mode"* and simply relies on it -
their manual-barrier option has no effect on Metal at all. The authors describe
Metal's tracking as moved *"into the framework, not disappeared"*.

For a Metal-on-Vulkan layer, that framework is the thing being written. The
tracker is not an optimisation to add later; it is a load-bearing component, and
it is independently known to be the hottest code in a comparable project.

This does not appear in the 2 558-method count at all.

## 2. Tile memory, imageblocks and programmable blending

Metal exposes Apple's tile-based deferred renderer directly. Memoryless textures
are tile memory - never read from or written to system memory, existing only for
the duration of a render pass. Imageblocks give fine-grained control over on-chip
memory, though they are available only on some hardware.

Vulkan's nearest equivalents are weaker in a specific way:

- `VK_IMAGE_USAGE_TRANSIENT_ATTACHMENT_BIT` is a **hint**. There is no guarantee
  about when an implementation will or will not spill to memory.
- Tile-local reads use input attachments within subpasses, or
  `VK_KHR_dynamic_rendering_local_read`.

The structural mismatch is documented in MoltenVK's tracker: Metal does not
handle memoryless reads from a previous subpass the way Vulkan does. Vulkan
removes a colour attachment from the outputs and reads it as a texture; Metal
requires all colour attachments to stay mapped across subpasses and be read and
written in the fragment shader through `color()`.

So a Metal application doing programmable blending is relying on a guarantee
Vulkan does not make. Translating it means either an extension-dependent path or
a correctness/performance compromise.

## 3. What MoltenVK's own limitations list tells us

Worth recording precisely because it is short. The documented "Known MoltenVK
Limitations" amount to: PVRTC images must be loaded through host-visible memory
rather than a staging buffer; `VK_QUERY_TYPE_PIPELINE_STATISTICS` is
unsupported; `VkAllocationCallbacks` are ignored; and MoltenVK does not load
Vulkan layers itself.

Four bullets, all narrow. The Vulkan-on-Metal direction is, for practical
purposes, solved. That is genuinely encouraging about the shared substrate - and
it is also why quoting MoltenVK as evidence that the reverse is tractable is a
mistake. It is evidence that the *easy* direction is tractable.

## 4. Not established

Marked honestly rather than glossed:

- **Argument buffers.** Metal's argument buffer tiers and their mapping onto
  Vulkan descriptor sets, descriptor indexing and buffer device address were
  searched for and no solid public analysis was found. **[open].**
- **Residency.** One MoltenVK discussion notes that the way Metal combines
  automatic barrier tracking with residency is a problem, but no detailed
  treatment was located. **[open].**
- **Heap aliasing rules**, `MTLHeap` sub-allocation semantics, and their Vulkan
  equivalents. **[open].**
- **Indirect command buffers** versus Vulkan device-generated commands.
  **[open].**
- Nothing here was measured in this repository. Establishing any of it firsthand
  needs a Metal implementation to test against.

## Revised picture

Adding this to the surface count:

- ~480 methods of load-bearing API behaviour, ~1 100 of mechanical plumbing
- shader translation between two LLVM-adjacent formats
- **plus a per-resource hazard tracker** that the method count does not show,
  which is a known performance-critical subsystem
- plus at least one feature class (tile-local reads, programmable blending) where
  Vulkan makes a weaker guarantee than Metal

Still bounded. Still userspace. Meaningfully larger than
[docs/05-metal-surface.md](05-metal-surface.md) alone implies, and the honest
version of that document's estimate should be read with this attached.

## Sources

- [MTLHazardTrackingMode - Apple Developer Documentation](https://developer.apple.com/documentation/metal/mtlhazardtrackingmode)
- [Global Pass Barriers Without Per-Resource RHI Tracking: A Cross-Vendor Study with Blade - arXiv 2607.26506](https://arxiv.org/html/2607.26506)
- [MoltenVK Runtime User Guide - Known Limitations](https://github.com/KhronosGroup/MoltenVK/blob/main/Docs/MoltenVK_Runtime_UserGuide.md)
- [Subpasses with transient attachments not working correctly - MoltenVK #490](https://github.com/KhronosGroup/MoltenVK/issues/490)
- [VK_MEMORY_PROPERTY_LAZILY_ALLOCATED_BIT - MoltenVK #2454](https://github.com/KhronosGroup/MoltenVK/issues/2454)
- [Vulkan Barriers Explained - AMD GPUOpen](https://gpuopen.com/learn/vulkan-barriers-explained/)
