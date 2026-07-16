# Architecture

## Status

Accepted for Phase 0 on 2026-07-16. The visual review artifact is `.lavish/phase-0-architecture.html`.

## Goals

- Provide one engine-neutral music operation core with an AXI CLI for agents and CueLab for humans.
- Support text generation, section repaint, remix or cover, stem extraction, deterministic analysis, and loop-safe MP3 export.
- Keep engines replaceable through configuration and capability metadata.
- Run locally without proprietary music services.
- Guarantee CLI, local API, and UI symmetry through a shared operation manifest.

## System design

BeatForge is a modular monolith. Python owns the engine contracts, operation orchestration, durable jobs, artifact metadata, audio post-processing, the Typer CLI, and a loopback FastAPI server. CueLab is a React application served by the local server in production.

Both front doors call the same application operations:

```text
agent -> beatforge-axi CLI -----------+
                                      +-> operation service -> engine registry -> adapter
human -> CueLab -> loopback HTTP/SSE -+                    -> shared audio pipeline
```

The browser never shells out. `beatforge-axi serve` owns the long-lived model process and serializes accelerator work by default. CLI commands may execute directly or submit to the same local job runtime when the server is active.

## Engine contract

Every adapter implements `generate`, `repaint`, `remix`, `stems`, and `analyze`. An unsupported operation remains a real method and returns a stable unsupported error after the capability gate. This keeps the call surface uniform without pretending all models have equal features.

All request and result types are engine-neutral. Adapter dependencies and native types stay inside their adapter package. Shared results contain artifacts, normalized metadata, warnings, timing, and provenance.

Capabilities are declared per loaded model variant. For example, ACE-Step stem extraction depends on a base model rather than a turbo model, so `stems` cannot be inferred from the engine name alone.

## CLI to UI boundary

`core/manifest.py` maps every operation to its CLI command, local API route, CueLab control, and required capability. Contract tests fail if any operation loses one of these surfaces.

The local API uses versioned routes under `/v1`. Long operations return job identifiers and stream progress through server-sent events. The production server binds to loopback and only exposes explicit import and export paths.

## Audio pipeline

Adapters return lossless or engine-native audio into a shared post-processing pipeline. The pipeline normalizes loudness, trims or pads to exact requested duration, applies loop-boundary processing, and exports MP3 as a first-class artifact. BPM and key analysis remain deterministic and portable rather than depending on an engine's semantic captioning API.

## Engine comparison

### ACE-Step 1.5

- License: repository and official weights are MIT.
- Fit: native text-to-music, cover, repaint, MP3, and model-dependent stem extraction.
- Runtime: Python 3.11 to 3.12 with CUDA, MPS, ROCm, XPU, and CPU paths.
- Decision: default engine family. The Phase 1 adapter pins one upstream commit, verifies the
  official `acestep-v15-turbo` checkpoint bundle, and declares only text generation until the
  editing and extraction modes receive separate engine-neutral verification.

### YuE

- License: code and weights are Apache-2.0.
- Fit: full songs with vocals and reference-audio style transfer.
- Runtime: CUDA-first, substantially heavier and slower, with 80 GB recommended for longer songs.
- Decision: optional vocals adapter. Contract and installation can be validated on Apple hardware, but quality and performance benchmarks require NVIDIA hardware.

### AudioCraft MusicGen

- License: code is MIT, while Meta's released model weights are CC BY-NC 4.0.
- Fit: text generation, melody conditioning, and continuation. No native bounded repaint or stems.
- Decision: include the adapter, configuration schema, tests, and documentation. Keep it inactive until a MusicGen-compatible checkpoint has verified MIT or Apache-2.0 weight provenance. Never auto-download or silently select Meta's released weights.

## ADR-001: Choose ACE-Step 1.5 as the default engine

### Context

CueLab requires humans to repaint sections and remix agent output. The default must work locally, export MP3, and use permissively licensed code and weights.

### Decision

Use ACE-Step 1.5 as the default. Keep YuE optional for vocals and MusicGen configurable behind the model license gate.

### Consequences

- Repaint and remix should stay native rather than being simulated by regenerating an entire
  track, but each capability is declared only after its model variant and request semantics are
  verified.
- Model-variant capabilities must be represented explicitly.
- The adapter must pin and isolate a fast-moving upstream API.
- Apple MPS can be used for the first local spike, while CUDA benchmarks remain separate.

### Revisit triggers

- ACE-Step changes its code or weight license.
- Repaint quality fails the accepted local benchmark.
- Another MIT or Apache model provides materially better editing with comparable local hardware support.

## ADR-002: Use a loopback job API between CueLab and the core

### Context

Model startup and inference are long-lived and expensive. A browser cannot safely invoke arbitrary local commands, and spawning a fresh model process for every control would create unacceptable latency.

### Decision

Expose versioned loopback HTTP endpoints and SSE progress from `beatforge-axi serve`. The server and CLI call the same application service.

### Consequences

- The engine process can stay warm.
- Jobs can be canceled and observed consistently.
- The API is a local transport boundary, not a second implementation.
- Loopback binding, origin checks, and explicit file endpoints become security requirements.

## Sources

- [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5)
- [YuE](https://github.com/multimodal-art-projection/YuE)
- [AudioCraft MusicGen model card](https://raw.githubusercontent.com/facebookresearch/audiocraft/main/model_cards/MUSICGEN_MODEL_CARD.md)
- [TOON specification](https://toonformat.dev/reference/spec.html)
