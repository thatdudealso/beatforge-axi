# Daily Mac setup for AuraFlow / BeatForge generate

This is the exact engine and environment setup for agent orchestrators that call
`beatforge-axi generate` and expect TOON `status: ok` plus a playable MP3.

## Prerequisites

1. Python 3.11 or 3.12
2. [`uv`](https://docs.astral.sh/uv/)
3. `ffmpeg` on `PATH` (MP3 encode/probe)

```sh
brew install ffmpeg
cd /path/to/beatforge-axi
uv sync --extra dev
# put the console script on PATH for AuraFlow:
uv run beatforge-axi --help
# or: uv pip install -e .  &&  which beatforge-axi
```

Confirm tools:

```sh
command -v ffmpeg && command -v ffprobe
uv run beatforge-axi --help
```

## Engine: `synth` (always works)

No model weights. Uses a local stdlib drone rendered through FFmpeg to MP3.

```sh
beatforge-axi --engine synth generate \
  --prompt "soft focus drone" \
  --duration 15 \
  --out /tmp/auraflow-bf-synth.mp3
```

Expected stdout (TOON):

```toon
operation: generate
status: ok
engine: synth
artifacts[1]: path,media_type,duration_s
  /tmp/auraflow-bf-synth.mp3,audio/mpeg,15.0
```

If `ffmpeg` is missing, the same command fails closed with
`status: error` / `code: engine_unavailable` and a message that `ffmpeg` is not
on `PATH`.

## Engine: `acestep` (product path, MIT)

Engine name: **`acestep`**.

### Checkpoint / checkout

1. Clone ACE-Step 1.5 and check out the pinned commit
   `6d467e4b5081ccb0abf1ec1bf4fdf9051a2d34b0`.
2. Install that checkout with `uv sync --frozen` so the `acestep` package is
   importable in the environment that runs `beatforge-axi`.
3. Install the official turbo bundle under `<checkout>/checkpoints/` for revision
   `19671f406d603126926c1b7e2adc169acbcade22` (files and digests are listed in
   [spikes/acestep.md](spikes/acestep.md)).

### Environment

| Variable | Required | Purpose |
| --- | --- | --- |
| `BEATFORGE_ACESTEP_PROJECT_ROOT` | yes | Absolute path to the pinned ACE-Step-1.5 checkout |
| `BEATFORGE_ACESTEP_DEVICE` | no | `auto` (default), `cpu`, `cuda`, `mps`, or `xpu` |

When `BEATFORGE_ACESTEP_PROJECT_ROOT` is set, BeatForge fills the official MIT
checkpoint identity, provenance URL, and weight digest allowlist. Activation
still fails closed until every readiness check passes (license, digests, clean
pinned checkout, importable `acestep` package).

```sh
export BEATFORGE_ACESTEP_PROJECT_ROOT="$HOME/src/ACE-Step-1.5"
export BEATFORGE_ACESTEP_DEVICE=mps   # Apple Silicon example

beatforge-axi --engine acestep generate \
  --prompt "dusty lo-fi beat with warm Rhodes" \
  --duration 60 \
  --out /tmp/auraflow-bf-daily.mp3
```

Without a ready checkpoint, the command returns TOON
`status: error` / `code: engine_unavailable` (never a silent fallback to Meta
NC MusicGen weights).

## Orchestrator contract

AuraFlow (or any agent) should call:

```sh
beatforge-axi --engine <ready-engine> generate \
  --prompt "…" \
  --duration 60 \
  --out /path/to/out.mp3
```

Use `--engine synth` to unblock plumbing; use `--engine acestep` on the daily
Mac once the MIT turbo bundle is installed. Do not rely on the default `fake`
engine for playable audio.
