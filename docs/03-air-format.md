# AIR: what is actually known about Metal's shader format

> **Status: [literature].** Everything below is published third-party reverse
> engineering. None of it has been reproduced in this repository - there is no
> Mac and no Metal toolchain in this environment. Treat it as a survey of what
> others have established, not as an independent result.

[docs/02-hardware-targets.md](02-hardware-targets.md) concluded that Metal is
the real wall and that a Metal implementation on top of Vulkan is the
highest-leverage unclaimed work in the area. The obvious objection is that a
shader compiler for an undocumented format is the hardest part of that job.

That objection appears to be wrong, and it is worth setting out why, because it
inverts where the difficulty sits.

## The container: `.metallib`

Metal ships compiled shaders in `.metallib` archives - a custom Apple container
format, undocumented, reverse engineered by hex inspection. It uses FourCC tags:

```
NAME    function name
MDSZ    metadata / bitcode size
OFFT    offset to the embedded bitcode blob
```

Zhuowei Zhang extracted individual functions from a metallib with a Python
script. Caveat recorded by the author: a single metallib file was examined, so
generality is not established.

## The payload: standard LLVM bitcode

This is the load-bearing finding. `.air` files are **not** a bespoke binary
format. They are LLVM bitcode carrying the standard wrapper magic `0x0B17C0DE`,
and ordinary LLVM tooling reads them:

- `llvm-dis` disassembles an AIR module into readable `.ll` with the usual
  header / body / metadata layout
- `llc` compiled Metal shader bitcode down to both x86-64 and ARM64 assembly

Metal-specific conventions inside the IR:

| Element | Meaning |
|---|---|
| target triple | `air64-apple-macosx14.0.0` |
| address space 1 | device memory |
| address space 2 | constant memory |
| `air.*` functions | Metal standard library intrinsics |

The metadata section carries what a translator needs: entry point definitions
with their inputs and outputs, vertex and fragment attributes (position, texture
coordinates, render targets), resource bindings for textures and samplers with
location indices, compile options, AIR version and language version.

## Why this changes the shape of the problem

A Metal-on-Vulkan layer needs to turn shaders into SPIR-V. Both ends of that
translation are LLVM-adjacent: AIR *is* LLVM bitcode, and SPIR-V has an
established, maintained LLVM translator in the Khronos ecosystem. The bindings,
attributes and entry point information a SPIR-V module requires are precisely
what AIR metadata already records.

That does not make it easy. But it makes it *ordinary compiler work with a known
input format*, rather than black-box reverse engineering. The part everyone
assumes is impossible is the part with the most existing groundwork.

## What is genuinely unresolved

Recorded honestly, because these are the things that would actually cost time:

- **The target triple is not registered upstream.** `air64-apple-macosx*` is not
  a recognised LLVM target, which blocks the standard optimizer pipeline from
  operating on these modules directly.
- **Undocumented metadata.** Unexplained `i1` boolean flags appear in texture
  sampling functions, and some metadata references have no established meaning.
- **Semantic gaps, unmeasured.** Nobody has published an inventory of where
  Metal's execution model diverges from Vulkan's - argument buffers, heaps,
  residency, tile shaders, the `MTLHeap` aliasing rules. Translating the
  *shader* is not translating the *API*, and the API is where the divergence
  lives.
- **Generality.** The container work rests on a small sample.

## Where the difficulty actually sits

If the shader path is tractable, the cost moves to the API surface - the `MTL*`
object model that applications call at runtime. That is the next queue item, and
it deserves a number rather than an adjective: nobody appears to have published
how large the Metal surface actually is.

## Sources

- [Compile Metal shader Bitcode to x86 and ARM assembly - Zhuowei Zhang](https://worthdoingbadly.com/metalbitcode/)
- [MetalShaderTools](https://github.com/zhuowei/MetalShaderTools)
- [Breaking down Metal's intermediate representation format - SamoZ256](https://medium.com/@samuliak/breaking-down-metals-intermediate-representation-format-41827022489c)
