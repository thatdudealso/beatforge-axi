# beatforge-axi

Local-first, open-source music generation for agents and humans.

`beatforge-axi` is the AXI-style command surface and local runtime. `cuelab-axi`
is the turntable UI that uses the same `/v1` API. The project has one engine,
one manifest, and two front doors: terse commands for agents and a deck for
people.

## What this project is

BeatForge is a local-first wrapper around openly licensed music generation
engines. It is designed for:

- text-to-music generation;
- section-level repaint when the active engine supports it;
- remix or cover workflows;
- stem splitting where model support is available;
- deterministic audio analysis;
- MP3 export as a first-class output;
- loop-friendly post-processing; and
- TOON-terse output for agent workflows.

Every operation is represented once in the core manifest and then exposed
through the CLI, local API, and CueLab UI. A feature should not exist only for
agents or only for humans.

## Non-goals

No proprietary or closed music-generation services are accepted. Suno is
explicitly out of scope as a backend, fallback, optional dependency, example, or
future integration. Model weights must be locally runnable and have verified MIT
or Apache-2.0 provenance before activation.

## Current status

Implemented and wired together:

- Python package scaffold with `uv`.
- Engine-neutral request, result, capability, and descriptor models.
- Pluggable `MusicEngine` protocol covering `generate`, `repaint`, `remix`,
  `stems`, and `analyze`.
- Operation manifest tying CLI commands, `/v1` routes, UI controls, and required
  capabilities together.
- Real local synth runtime, artifact serving, and job orchestration.
- AXI CLI command surface for generate, repaint, remix, stems, analyze, and
  serve.
- Loopback `/v1/manifest` and `/v1/jobs/{operation}` server boundary.
- CueLab React/Vite deck with generate, play, and export controls.
- Open-source project files, issue templates, PR template, and CI.

Supported current runtime behaviors:

- Generate real local audio from prompts.
- Repaint, remix, stems, and analyze through the shared job API when the active
  engine supports the capability.
- Play generated audio from CueLab.
- Export generated audio as MP3 or WAV.
- Keep agent output TOON-terse by default.

Engine candidates remain pluggable behind the same contract:

- MusicGen adapter: generate-only, inactive until a permissively licensed local
  checkpoint is explicitly configured and verified.
- ACE-Step 1.5 adapter: local generation plus repaint/remix direction with
  permissive provenance.
- YuE adapter: optional CUDA-focused vocals and remix path with Apache-2.0
  provenance and fail-closed readiness.

See [docs/architecture.md](docs/architecture.md) for the accepted design and
[docs/testing.md](docs/testing.md) for the validation strategy. Phase 1 adapter
validation records live under `docs/spikes/`.

## Architecture

BeatForge is a modular monolith. Python owns the engine contracts, operation
orchestration, jobs, artifact metadata, audio post-processing, CLI, and local
loopback server. CueLab is a React app served by that local runtime.

```text
agent -> beatforge-axi CLI -----------+
                                      +-> operation service -> engine registry -> adapter
human -> CueLab -> loopback HTTP/SSE -+                    -> shared audio pipeline
```

Adapters keep their native imports and dependencies inside their own packages.
Unsupported operations are still real methods and return stable unsupported
errors after capability checks. That keeps the CLI and UI consistent even when
engines have different strengths.

## Target CLI

The current CLI implements this command surface with the configured engine:

```sh
beatforge-axi generate --prompt "dusty lo-fi beat with warm Rhodes" --duration 60 --out track.mp3
beatforge-axi repaint --in track.mp3 --section 0:30-0:45 --prompt "add tape-stop drums"
beatforge-axi remix --in track.mp3 --style "late-night garage dub"
beatforge-axi stems --in track.mp3
beatforge-axi analyze --file track.mp3
```

Default stdout is TOON-formatted and terse. Progress and diagnostics belong on
stderr. `--full` expands metadata for humans and debugging.

The default runtime engine is `synth`, a real local synthesis engine that
produces playable PCM audio and can export WAV or MP3. The `fake` engine is
retained only for isolated contract tests. Hardware engines require their
documented local checkpoints and readiness gates.

## Engine policy

Engines are interchangeable through the shared adapter contract and capability
metadata. Selection must be a configuration decision, not a rewrite.

| Engine | Phase 1 role | Strength | Important caveat |
| --- | --- | --- | --- |
| ACE-Step 1.5 | Default candidate | Local generation, repaint/remix direction, permissive provenance | Heavy runtime and verified weights are required for real inference |
| YuE | Optional vocals adapter | Full-song vocals and reference-audio style transfer | CUDA-first and substantially heavier |
| MusicGen | Optional generate-only adapter | Mature text-to-music baseline | Official Meta weights are CC-BY-NC and are rejected by project policy |

Activation must fail closed when a model, checkpoint, digest, license, device,
or dependency is not verified.

## Local setup

Requirements:

- Python 3.11 or 3.12
- `uv`
- FFmpeg for future MP3 integration tests and exports
- Node.js 22 and pnpm for future CueLab work

Install development dependencies:

```sh
uv sync --extra dev
```

Run validation:

```sh
uv run ruff format --check .
uv run ruff check .
uv run basedpyright
uv run pytest
```

## Repository layout

```text
engine/          Pluggable engine contract and adapters
cli/             AXI command entry point
core/            Operation manifest and shared orchestration surface
cuelab-axi/      CueLab human UI docs and future React app
docs/            Architecture, testing strategy, and spike records
tests/           Contract and smoke tests
```

## CueLab

CueLab is the planned web UI for the same operations. It should feel like a
usable deck, not a marketing page: prompt deck, presets, waveform-on-platter,
repaint region selection, stem mixer, loop editor, and export controls.

See [cuelab-axi/README.md](cuelab-axi/README.md) for the live UI surface.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR. The short version:

- keep engine dependencies behind their adapter package;
- add tests at the contract or end-to-end layer before changing behavior;
- update the operation manifest when adding or renaming operations;
- preserve CLI, API, and CueLab symmetry;
- do not commit model weights, generated audio, credentials, or private data;
- never add proprietary music APIs.

The project is MIT licensed.
