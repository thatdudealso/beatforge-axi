# ACE-Step 1.5 Phase 1 adapter spike

## Verified upstream boundary

Research and the hardware smoke were performed on 2026-07-16 against official ACE-Step
sources at commit
[`6d467e4b5081ccb0abf1ec1bf4fdf9051a2d34b0`](https://github.com/ace-step/ACE-Step-1.5/commit/6d467e4b5081ccb0abf1ec1bf4fdf9051a2d34b0).
The adapter pins that full commit and rejects a different configured commit.

Primary sources examined:

- The pinned [`pyproject.toml`](https://github.com/ace-step/ACE-Step-1.5/blob/6d467e4b5081ccb0abf1ec1bf4fdf9051a2d34b0/pyproject.toml)
  requires Python 3.11 or 3.12, declares the code MIT, and selects PyTorch, torchvision,
  torchaudio, MLX, and MLX-LM dependencies for Apple Silicon.
- The pinned [installation guide](https://github.com/ace-step/ACE-Step-1.5/blob/6d467e4b5081ccb0abf1ec1bf4fdf9051a2d34b0/docs/en/INSTALL.md)
  documents `uv sync`, CUDA, MPS, ROCm, Intel XPU, and CPU support. It gives 4 GB VRAM as
  the DiT-only minimum, 6 GB for LM plus DiT, and about 10 GB of disk for core models. Its
  macOS launcher uses MLX on Apple Silicon.
- The pinned [Python inference guide](https://github.com/ace-step/ACE-Step-1.5/blob/6d467e4b5081ccb0abf1ec1bf4fdf9051a2d34b0/docs/en/INFERENCE.md)
  documents `AceStepHandler`, `GenerationParams`, `GenerationConfig`, and `generate_music`.
  The Phase 1 boundary follows that API with one instrumental sample, turbo's eight steps,
  no LM thinking, and a caller-selected seed.
- The pinned [code license](https://github.com/ace-step/ACE-Step-1.5/blob/6d467e4b5081ccb0abf1ec1bf4fdf9051a2d34b0/LICENSE)
  is MIT.
- The official [model card at the immutable model revision](https://huggingface.co/ACE-Step/Ace-Step1.5/blob/19671f406d603126926c1b7e2adc169acbcade22/README.md)
  explicitly declares the model license MIT. The adapter does not infer this from a
  filename or repository name.
- The official [Hugging Face revision API with blob metadata](https://huggingface.co/api/models/ACE-Step/Ace-Step1.5/revision/19671f406d603126926c1b7e2adc169acbcade22?blobs=true)
  reports immutable revision `19671f406d603126926c1b7e2adc169acbcade22`, `license:mit`,
  file sizes, and LFS SHA-256 digests.

ACE-Step is installed from its source checkout with `uv sync --frozen`. It is not imported
when `engine.acestep` is imported, when configuration is created, or when an unsupported
operation is called. The first supported operation loads the pinned Python API lazily.

## Checkpoint provenance and activation gate

The verified checkpoint identity is
`ACE-Step/Ace-Step1.5@19671f406d603126926c1b7e2adc169acbcade22/acestep-v15-turbo/model.safetensors`.
The local bundle required by upstream for DiT-only generation contains these verified files:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `acestep-v15-turbo/model.safetensors` | 4,787,825,604 | `3f6e0797fad420a39bd33979eb6e840e30989e34a3794e843d23b60ec6e422d7` |
| `acestep-v15-turbo/silence_latent.pt` | 3,841,215 | `a778e9dd942f5e8b2c09c55370782d318834432b03dabbcdf70e6ed49ad6358b` |
| `vae/diffusion_pytorch_model.safetensors` | 337,431,388 | `da17edb604c40deaf09e9b24974e590d1ca83a374070e5d0884cfa4bed9a99b0` |
| `Qwen3-Embedding-0.6B/model.safetensors` | 1,191,586,416 | `0437e45c94563b09e13cb7a64478fc406947a93cb34a7e05870fc8dcd48e23fd` |
| `acestep-5Hz-lm-1.7B/model.safetensors` | 3,708,521,528 | `f161689da73e5ecefa28ff780d51c2d92a00f056d021d7933c779ed5c6cd7db8` |

The LM is disabled by this adapter, but the pinned upstream loader still requires its weight
file to regard the main snapshot as installed. The adapter therefore verifies it too. This
also prevents upstream's model-presence check from initiating an unpinned automatic download.

Activation fails closed unless all of the following are true:

- the configured license matches the official model card's explicit MIT declaration (the
  project policy permits MIT or Apache-2.0 generally, but this pinned checkpoint is MIT);
- checkpoint identity includes an immutable 40-character revision;
- the requested model variant is the allowlisted `acestep-v15-turbo` variant;
- the authoritative provenance URL is HTTPS;
- the configured upstream commit matches the adapter pin;
- `project_root` is a git checkout whose actual `HEAD` matches that pin, and the imported
  package resolves inside that checkout, with no local source changes;
- every configured weight digest matches the adapter's published allowlist, the complete
  required weight manifest is present, and every local digest matches; and
- the optional `acestep` package is discoverable.

Readiness issues use stable codes and actionable messages. Native imports occur only after
the readiness gate. Native load and generation failures are translated to stable shared
engine errors without exposing upstream exception text.

## Phase 1 capabilities

Only `generate` is declared. `repaint`, `remix`, `stems`, and `analyze` remain real protocol
methods and return stable unsupported-operation errors without loading ACE-Step. Upstream has
editing and extraction modes, but their model variants and engine-neutral semantics need a
separate verified adapter phase before those capabilities can be declared honestly.

Supported generation output suffixes are WAV, FLAC, MP3, Opus, and AAC. Generation is
serialized per adapter instance because the runtime owns a large mutable accelerator model.

## Apple MPS smoke generation

Result: successful. A real artifact was produced through `AceStepEngine` and inspected.

| Field | Recorded value |
| --- | --- |
| Machine | Apple M4 Pro, 14 CPU cores, 48 GB unified memory |
| Upstream commit | `6d467e4b5081ccb0abf1ec1bf4fdf9051a2d34b0` |
| Checkpoint revision | `19671f406d603126926c1b7e2adc169acbcade22` |
| Primary checkpoint digest | `3f6e0797fad420a39bd33979eb6e840e30989e34a3794e843d23b60ec6e422d7` |
| Verified license | MIT, from the immutable official model card and revision API linked above |
| Download size | 10,079,024,720 unique repository bytes reported by the API; 10,092,102,593 locally materialized snapshot bytes excluding cache metadata |
| Device | PyTorch DiT on `mps`; upstream log: `DiT backend: PyTorch (mps)` |
| Precision | DiT and text conditioning `float32`; upstream native MLX VAE decode `float32` |
| MLX DiT | Disabled for this smoke so diffusion genuinely exercised MPS |
| Prompt | `instrumental glassy synth arpeggio, warm bass pulse, crisp electronic drums` |
| Seed | `20260716` |
| Requested duration | 10 seconds |
| Adapter `generate` wall time | 52.671 seconds, including readiness recheck, cold model load, and generation |
| Whole-process wall time | 152.24 seconds, including initial full bundle verification |
| Peak resident memory | 14,970,191,872 bytes from `/usr/bin/time -l`; separate MPS allocation was not available |
| Artifact | PCM WAV, 16-bit stereo, 48,000 Hz, 1,920,044 bytes |
| Artifact SHA-256 | `434411c0d496d248882b0be5f6309e7eda201546b3dabc5fb19b19bf5896459e` |

Inspection with SoundFile and NumPy found exactly 480,000 frames, two channels, all finite
samples, peak amplitude `0.8912353515625`, RMS `0.11297813716923631`, and 959,772 nonzero
samples. The produced duration is exactly 10.0 seconds. The VAE decode used upstream's native
MLX path even though DiT diffusion ran on MPS, so this report identifies both boundaries.
