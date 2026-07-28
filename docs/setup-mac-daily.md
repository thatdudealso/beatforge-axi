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

Engine name: **`acestep`**. Already registered in `runtime_registry()`.

### One-shot setup script

```sh
# clones pinned commit, uv sync, downloads verified revision into checkpoints/
./scripts/setup-acestep.sh "$HOME/src/ACE-Step-1.5"
```

Then install BeatForge into that ACE-Step environment (keeps torch/MLX with upstream):

```sh
cd "$HOME/src/ACE-Step-1.5"
uv pip install -e /path/to/beatforge-axi
```

BeatForge's console entrypoint demotes ACE-Step's top-level `cli.py` so
`beatforge-axi` keeps resolving BeatForge's `cli` package.

### Manual checkpoint / checkout

1. Clone ACE-Step 1.5 and check out the pinned commit
   `6d467e4b5081ccb0abf1ec1bf4fdf9051a2d34b0`.
2. Install that checkout with `uv sync` / `uv sync --frozen`.
3. Download the official turbo bundle under `<checkout>/checkpoints/` for revision
   `19671f406d603126926c1b7e2adc169acbcade22`:

```sh
hf download ACE-Step/Ace-Step1.5 \
  --revision 19671f406d603126926c1b7e2adc169acbcade22 \
  --local-dir "$HOME/src/ACE-Step-1.5/checkpoints"
```

Required files and digests are listed in [spikes/acestep.md](spikes/acestep.md).

4. Make the `acestep` package importable without shadowing BeatForge's `cli`
   package. BeatForge appends `BEATFORGE_ACESTEP_PROJECT_ROOT` onto `sys.path`
   when configured. Prefer installing BeatForge into the ACE-Step venv (heavy
   stack stays isolated) rather than editable-installing ACE-Step into BeatForge:

```sh
cd "$HOME/src/ACE-Step-1.5"
uv pip install -e /path/to/beatforge-axi
# beatforge-axi entrypoint demotes ACE-Step's cli.py so imports stay correct
```

### Environment

| Variable | Required | Purpose |
| --- | --- | --- |
| `BEATFORGE_ACESTEP_PROJECT_ROOT` | yes | Absolute path to the pinned ACE-Step-1.5 checkout |
| `BEATFORGE_ACESTEP_DEVICE` | no | `auto` (default), `cpu`, `cuda`, `mps`, or `xpu` |
| `BEATFORGE_ACESTEP_USE_MLX_DIT` | no | Default on for `auto`/`mps`; set `0` on Linux CPU/CUDA |
| `BEATFORGE_ACESTEP_OFFLOAD_TO_CPU` | no | Pass-through to upstream for low-memory hosts |
| `BEATFORGE_ACESTEP_OFFLOAD_DIT_TO_CPU` | no | Pass-through to upstream DiT offload |
| `ACESTEP_INIT_LLM` | no | Upstream env; use `false` for DiT-only / low RAM |

When `BEATFORGE_ACESTEP_PROJECT_ROOT` is set, BeatForge fills the official MIT
checkpoint identity, provenance URL, and weight digest allowlist. Activation
still fails closed until every readiness check passes (license, digests, clean
pinned checkout, importable `acestep` package).

```sh
export BEATFORGE_ACESTEP_PROJECT_ROOT="$HOME/src/ACE-Step-1.5"
export BEATFORGE_ACESTEP_DEVICE=mps   # Apple Silicon daily Mac
# Linux CPU (works; frees DiT before VAE decode for ≤16GB hosts):
# export BEATFORGE_ACESTEP_DEVICE=cpu
# export BEATFORGE_ACESTEP_USE_MLX_DIT=0
# export BEATFORGE_ACESTEP_OFFLOAD_TO_CPU=1
# export ACESTEP_INIT_LLM=false

"$HOME/src/ACE-Step-1.5/.venv/bin/beatforge-axi" --engine acestep generate \
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
