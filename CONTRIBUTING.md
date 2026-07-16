# Contributing

BeatForge welcomes focused fixes, engine adapters, CLI improvements, audio pipeline work, and CueLab interface improvements.

## Local setup

Requirements:

- Python 3.11 or 3.12
- [uv](https://docs.astral.sh/uv/)
- Node.js 22 and pnpm for CueLab work
- FFmpeg for MP3 integration tests and local exports

Install Python dependencies:

```sh
uv sync --extra dev
```

Run the current checks:

```sh
uv run ruff format --check .
uv run ruff check .
uv run basedpyright
uv run pytest
```

CueLab setup commands will live in `cuelab-axi/README.md` after the UI scaffold lands.

## Development workflow

1. Open or reference an issue for changes that affect architecture, model support, command behavior, or user workflows.
2. Write an end-to-end or contract test that demonstrates the behavior before implementing it.
3. Keep engine dependencies behind their adapter. Do not import an engine package from the CLI, API, core, or UI.
4. Update `core/manifest.py` when adding or renaming an operation. The same pull request must provide its CLI, API, and CueLab surface.
5. Run all applicable checks locally and describe hardware-only validation separately.

## AXI and TOON conventions

- Serialize structured data to TOON only at stdout.
- Send progress and diagnostics to stderr.
- Exit `0` for success and idempotent no-ops, `1` for runtime failures, and `2` for usage errors.
- Reject unknown flags before loading a model or changing files.
- Keep default schemas terse. Use `--fields` for extra fields and `--full` only for untruncated detail.
- Return structured, actionable errors without raw backend stack traces.
- Never require an interactive prompt.

## Engine and license policy

Only locally runnable, openly licensed engines and model weights are accepted. Runtime model weights must be MIT or Apache-2.0 with verifiable provenance and an immutable checkpoint digest.

The MusicGen adapter is intentionally included but unconfigured. Meta's released MusicGen weights are CC BY-NC 4.0 and do not satisfy this repository's runtime policy. A MusicGen-compatible checkpoint may be activated only when its full inherited weight provenance is verified as MIT or Apache-2.0.

Pull requests adding proprietary or closed music-generation services are rejected. This includes Suno as a backend, fallback, optional dependency, example integration, or future hook.

## Pull requests

- Keep the change scoped and explain user-visible behavior.
- Include tests at the lowest useful layer and an end-to-end path for workflows.
- Include screenshots for CueLab changes at desktop and mobile widths.
- Document engine name, exact version or commit, device, model, weight license, and benchmark method for adapter work.
- Do not commit model weights, generated audio, credentials, or private datasets.
- CI must pass before merge.
