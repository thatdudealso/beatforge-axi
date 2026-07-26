# ACE-Step 1.5 Phase 1 adapter spike

## Verified upstream boundary

Research was performed on 2026-07-16 against official ACE-Step sources at commit
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

## CLI / environment activation

The CLI registers `acestep` through `runtime_registry()`. Set:

```sh
export BEATFORGE_ACESTEP_PROJECT_ROOT=/path/to/ACE-Step-1.5   # pinned commit required
export BEATFORGE_ACESTEP_DEVICE=mps                           # optional; default auto
```

`config_from_environ()` fills the official MIT checkpoint identity, provenance URL, and
weight digest allowlist when the project root is set. Without
`BEATFORGE_ACESTEP_PROJECT_ROOT`, the engine stays registered but activation fails closed
with TOON `engine_unavailable`. Daily Mac steps and smoke commands live in
[../setup-mac-daily.md](../setup-mac-daily.md).

## Adapter configuration surface

`AceStepConfig` is adapter-local. `project_root` points at the pinned ACE-Step git checkout,
and local weights are read from `project_root/checkpoints`. Activation also requires the
verified checkpoint identity, primary checkpoint SHA-256, complete `verified_weights`
manifest, MIT `model_license`, official `provenance_url`, and pinned `upstream_commit`.

The only verified `config_path` is `acestep-v15-turbo`. Supported `device` values are `auto`,
`cpu`, `cuda`, `mps`, and `xpu`. Runtime toggles `use_mlx_dit`, `offload_to_cpu`, and
`offload_dit_to_cpu` are passed through to upstream only after the readiness gate succeeds.

## Phase 1 capabilities

Only `generate` is declared. `repaint`, `remix`, `stems`, and `analyze` remain real protocol
methods and return stable unsupported-operation errors without loading ACE-Step. Upstream has
editing and extraction modes, but their model variants and engine-neutral semantics need a
separate verified adapter phase before those capabilities can be declared honestly.

Supported generation output suffixes are WAV, FLAC, MP3, Opus, and AAC. Generation is
serialized per adapter instance because the runtime owns a large mutable accelerator model.

## Apple MPS smoke generation

Result: not reproduced in this validation environment. No real Apple MPS generation artifact
was produced or inspected here because the optional `acestep` package was not discoverable
and the verified checkpoint bundle was not present. Per validation direction, this pass did
not download ACE-Step weights or require the heavy upstream runtime.

The executable evidence for this pass is mocked adapter E2E coverage through `AceStepEngine`.
That evidence verifies the adapter's public behavior: ready configuration, generate-only
capabilities, request mapping, copied WAV output, metadata, and stable unsupported repaint
behavior. It does not prove real ACE-Step runtime execution, real Apple MPS diffusion, model
load behavior, wall time, memory use, or audio quality.
