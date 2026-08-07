# How big is Metal, actually

> **Status: [measured].** Produced by `tools/metal_surface.py` from Apple's own
> `metal-cpp` headers (github.com/apple/metal-cpp). Raw output in
> `data/metal-surface.json`. Reproducible on any OS with stock Python.

Every discussion of reimplementing Metal is conducted in adjectives. "Huge."
"Impossible." Nobody appears to have published a number, so here is one.

## The census

```
framework       hdrs  classes  methods  enums  enum val  consts
---------------------------------------------------------------
Metal             97      207     2385    128       918      27
MetalFX           11        9      150      0         0       0
QuartzCore         5        2       23      0         0       0
Foundation        23       22      229      0         0       0
---------------------------------------------------------------
TOTAL            136      240     2787    128       918      27
```

The graphics surface proper — Metal plus MetalFX plus QuartzCore — is
**218 classes and 2 558 methods**, over 128 enumerations carrying 918 values.
Foundation is counted separately because `NS::` is a different problem, already
addressed by GNUstep and Darling.

## Why 2 385 is the wrong number to be frightened of

Method counts are only useful decomposed, because the methods are not the same
kind of work. Splitting Metal's surface by what a class *is*:

| Kind | Classes | Methods | Share |
|---|---|---|---|
| `*Descriptor` | 81 | 1 110 | **46.5%** |
| `*Encoder` | 9 | 267 | 11.2% |
| `*State` | 6 | 56 | 2.3% |
| Device, CommandQueue, CommandBuffer | 3 | 212 | 8.9% |
| everything else | 108 | 740 | 31.0% |

Nearly half the API by method count is descriptors. A descriptor is a property
bag — `RenderPipelineDescriptor` has 72 methods because it has 36 settable
properties with a getter and a setter each. Implementing one is mechanical: hold
a struct, validate on use. It is bulk, not difficulty.

The load-bearing surface is the encoders (267 methods) and the device and
command queue (212), which is where real driver behaviour lives — roughly
**480 methods, about a fifth of the total** — plus some fraction of the 740 in
"everything else" (textures, buffers, libraries, functions).

The single largest classes are `Device` at 155 methods and
`RenderCommandEncoder` at 131. Those two are the project.

## What this means for a Metal-on-Vulkan layer

Combined with [docs/03-air-format.md](03-air-format.md), the shape of the job
becomes concrete rather than mythical:

- **Shaders**: AIR is LLVM bitcode with reverse-engineered metadata; SPIR-V has
  an established LLVM translator. Compiler work with a known input format.
- **API**: roughly 480 methods of genuine behaviour, ~1 100 methods of
  mechanical property plumbing, 918 enum values to map.
- **Everything runs in userspace**: no kernel, no signing, no boot chain,
  ordinary stack traces.

That is a large project. It is not an unbounded one, and for the first time it
has a denominator.

For comparison of ambition rather than scope: MoltenVK implements Vulkan on top
of Metal and is a maintained, shipping, Valve-backed project. The reverse
direction has a comparable surface and, unlike MoltenVK, no vendor behind it.

## Limits of this measurement

Stated plainly, because a number with hidden assumptions is worse than no
number:

- **Surface is not semantics.** A declared method is a lower bound. Some are one
  line; `RenderCommandEncoder::drawIndexedPrimitives` correctly implemented over
  Vulkan is not.
- **`metal-cpp` may lag the Objective-C API.** It is Apple's own binding, but
  whether it covers the Objective-C surface exhaustively is **[open]** — not
  verified here.
- **The "everything else" bucket is heterogeneous**, mixing trivial value types
  with load-bearing objects like `Texture` and `Library`. The 480-method figure
  for load-bearing work is therefore an underestimate.
- **Behavioural compatibility is uncounted and is the real risk.** Argument
  buffers, heap aliasing rules, residency, tile shaders and Metal's memory model
  have no line in this table, and divergence from Vulkan there is where such
  projects actually stall. Nobody has published that inventory; it is queued.
- The headers include `MTL4FX*` types, indicating a Metal 4 surface that this
  count does not analyse separately.

## Reproducing

```bash
git clone --depth 1 https://github.com/apple/metal-cpp.git _work/metal-cpp
python tools/metal_surface.py _work/metal-cpp --json data/metal-surface.json
```

## A note on the tool

The first run reported MetalFX as 0 classes across 11 headers. That was a
parser bug, not an empty framework: MetalFX declares its classes indented inside
a `namespace MTLFX` block, and the regex was anchored at column 0. Recorded here
because a measurement tool that silently returns zero is worse than one that
crashes, and because the same class of error is why this repository tags every
claim with how it was obtained.
