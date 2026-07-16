# YuE Phase 1 adapter spike

## Scope and decision

Research and contract validation were performed on 2026-07-16 against upstream commit
[`9f1394bae1d8d218fea750c1413c2d9d731c7310`](https://github.com/multimodal-art-projection/YuE/tree/9f1394bae1d8d218fea750c1413c2d9d731c7310).
That exact commit is pinned by the adapter. The upstream `main` branch had the same HEAD when
checked.

Phase 1 uses YuE as a safe optional NVIDIA-only adapter. It advertises:

- `generate`: the official CoT lyrics-to-song path.
- `remix`: the official single-track in-context-learning path, using the input audio as the style
  reference. YuE has no equivalent to BeatForge's remix-strength control, so the adapter returns an
  explicit warning that the requested strength was ignored.

It does not advertise repaint, arbitrary stem extraction, or deterministic analysis. Upstream
lists stem generation as unfinished, and its inference outputs vocal and instrumental tracks for
its own generated song rather than extracting stems from an arbitrary BeatForge input. Unsupported
methods return a stable error without probing dependencies or loading the runtime. The official
[pinned README](https://github.com/multimodal-art-projection/YuE/blob/9f1394bae1d8d218fea750c1413c2d9d731c7310/README.md)
documents CoT lyrics-to-song, single-track ICL, and dual-track ICL and identifies stem generation as
a TODO.

## Installation and inference surface

The official installation is Linux/WSL and CUDA oriented. Its pinned instructions recommend Python
3.8 or newer, CUDA 11.8 or newer, PyTorch with CUDA, the repository
[`requirements.txt`](https://github.com/multimodal-art-projection/YuE/blob/9f1394bae1d8d218fea750c1413c2d9d731c7310/requirements.txt),
and FlashAttention 2. Upstream calls FlashAttention 2 mandatory for reducing VRAM use. The
requirements are not version pinned.

The official inference API is the top-level
[`inference/infer.py`](https://github.com/multimodal-art-projection/YuE/blob/9f1394bae1d8d218fea750c1413c2d9d731c7310/inference/infer.py)
script. It parses command-line arguments and initializes model state at module scope, so it is not
an import-safe Python library boundary. Important arguments are `--stage1_model`,
`--stage2_model`, `--genre_txt`, `--lyrics_txt`, `--run_n_segments`, `--output_dir`,
`--cuda_idx`, and `--seed`. Single-track ICL additionally uses `--use_audio_prompt` and
`--audio_prompt_path`. The script loads Transformers models with bfloat16 and
`flash_attention_2`, moves them to a CUDA device, runs stage 1 and stage 2, decodes codec tokens,
and writes a final MP3.

The adapter therefore invokes the pinned script in an isolated subprocess. No YuE, Torch,
Transformers, or codec imports occur when `engine.yue` is imported. Dependency and CUDA probing is
lazy. The adapter passes explicit codec paths rather than relying on mutable upstream defaults.

The adapter requires separate checkpoint evidence for:

1. the stage-1 CoT model used by `generate`;
2. the stage-1 ICL model used by `remix`;
3. the shared stage-2 model; and
4. the XCodec decoder bundle.

Each component needs an immutable identity, an explicit local or immutable location, a
64-character SHA-256 digest, an explicit MIT or Apache-2.0 license, and an authoritative HTTPS
provenance URL. A repository name or filename is never interpreted as license evidence. The
descriptor exposes a deterministic digest of the configured evidence manifest. Missing, malformed,
mixed-license, or non-permissive evidence leaves the descriptor unready and fails before runtime
probing.

Adapter-local configuration is represented by `YueConfig`: `upstream_root` must point at the pinned
YuE checkout, `upstream_commit` must match the audited commit, `checkpoints` must contain exactly
one `stage1`, `stage1_icl`, `stage2`, and `codec` evidence record, `cuda_index` selects the NVIDIA
device, `minimum_vram_gb` and `full_song_vram_gb` define readiness policy, and `default_genre` is
used only for BeatForge `generate` requests. `remix` uses the request style as both style guidance
and the lyric seed for single-track ICL. Supported calls reject non-MP3 output before probing or
starting the upstream runtime.

## License and provenance

The pinned source repository contains the
[Apache-2.0 license](https://github.com/multimodal-art-projection/YuE/blob/9f1394bae1d8d218fea750c1413c2d9d731c7310/LICENSE).
The official README also states that the YuE model, including its weights, is Apache-2.0. The
official model publisher is `m-a-p`, linked directly by that README.

The following official immutable revisions and LFS SHA-256 values were checked through the
Hugging Face model API. They are recorded as provenance facts, not bundled defaults. A deployment
must verify every file it actually stages and configure its own component manifest digest.

### Stage 1 CoT, English

- Identity: `m-a-p/YuE-s1-7B-anneal-en-cot@454c20e1748888800f8e4b3da45125f55482d967`
- License metadata: Apache-2.0
- `model-00001-of-00003.safetensors`:
  `93c6f48ec95c0e36e681fb1c200754b9e39b9d7603ebdee88580429b526a86b2`
- `model-00002-of-00003.safetensors`:
  `d9a7c7adf0142010ea7fb2d6d60b2698b86f36847d00d0afa4170c3a9fb66a9c`
- `model-00003-of-00003.safetensors`:
  `c4c9f1d21524ad189e63230a62a62997c52205f9ce3099948c7fc3d27385d0dc`
- [Official immutable tree](https://huggingface.co/m-a-p/YuE-s1-7B-anneal-en-cot/tree/454c20e1748888800f8e4b3da45125f55482d967)
- [Official metadata with blobs](https://huggingface.co/api/models/m-a-p/YuE-s1-7B-anneal-en-cot?blobs=true)

### Stage 1 ICL, English

- Identity: `m-a-p/YuE-s1-7B-anneal-en-icl@024ea105533fdd99f8a67ee75abce61c7b813938`
- License metadata: Apache-2.0
- `model-00001-of-00003.safetensors`:
  `ebd58560f2fcaf0b805775ae86580b56cad381cde6c30e6a0a85f13dd8d265b6`
- `model-00002-of-00003.safetensors`:
  `47599ce66b20ea26ce0155bebd207bc083178534e19b4adfa34eb775fdecb725`
- `model-00003-of-00003.safetensors`:
  `7b09d57129feeb2e434f1ac64070ae0db57571b556f39778348239ec69687141`
- [Official immutable tree](https://huggingface.co/m-a-p/YuE-s1-7B-anneal-en-icl/tree/024ea105533fdd99f8a67ee75abce61c7b813938)
- [Official metadata with blobs](https://huggingface.co/api/models/m-a-p/YuE-s1-7B-anneal-en-icl?blobs=true)

### Stage 2

- Identity: `m-a-p/YuE-s2-1B-general@9dfa90b7013f6b5e7eb5eb2991620dca33058a0e`
- License metadata: Apache-2.0
- `model.safetensors`:
  `87839fa9693a15d84c6bc96df2ac270063d4d87598b0fd0555996fe934fdf42f`
- [Official immutable tree](https://huggingface.co/m-a-p/YuE-s2-1B-general/tree/9dfa90b7013f6b5e7eb5eb2991620dca33058a0e)
- [Official metadata with blobs](https://huggingface.co/api/models/m-a-p/YuE-s2-1B-general?blobs=true)

### XCodec decoder bundle

- Identity: `m-a-p/xcodec_mini_infer@fe781a67815ab47b4a3a5fce1e8d0a692da7e4e5`
- License metadata: Apache-2.0
- `final_ckpt/ckpt_00360000.pth`:
  `c8c379ea2d3cbde1c8ba1b9717975220e79ba3f556bb161766fd5e4585dcd59c`
- `decoders/decoder_131000.pth`:
  `b99f0be84eeef3a32f29cd55beb89727fd0b2fd0df3dbad3023508f4c7185c37`
- `decoders/decoder_151000.pth`:
  `8af97a29d3483f9d4a3755992837501bd7d6caa1a69382ed16e64039e0ea0998`
- `semantic_ckpts/hf_1_325000/pytorch_model.bin`:
  `c5ddbd7fa2468483cb9b2aa53117813471543dd278e65870333a56c54305f527`
- [Official immutable tree](https://huggingface.co/m-a-p/xcodec_mini_infer/tree/fe781a67815ab47b4a3a5fce1e8d0a692da7e4e5)
- [Official metadata with blobs](https://huggingface.co/api/models/m-a-p/xcodec_mini_infer?blobs=true)

## Hardware policy and diagnostics

Upstream says GPUs with 24 GB or less should use at most two sessions. It recommends at least 80 GB
for full songs of four or more sessions. Its published timing claims are 150 seconds for 30 seconds
of audio on H800 and about 360 seconds on RTX 4090. None of those performance claims were reproduced
in this spike.

The Phase 1 adapter intentionally supports only NVIDIA CUDA. MPS and CPU fail with
`YUE_CUDA_REQUIRED`. The conservative standard profile requires 24 GiB of measurable CUDA VRAM,
while requests mapping to four or more 30-second sessions require 80 GiB. Lower-memory community
quantized forks are outside this adapter because they were not the official pinned runtime examined
here. Missing packages fail with `YUE_DEPENDENCY_MISSING`; unmeasurable or insufficient memory fails
with `YUE_VRAM_UNKNOWN` or `YUE_VRAM_INSUFFICIENT`.

## Validation record

Validated on an Apple Silicon Mac in a worktree-local uv environment using CPython 3.12.12:

- Project and adapter imports without optional YuE dependencies.
- Configuration, protocol conformance, capability declarations, checkpoint license and provenance
  rejection, missing dependencies, no-CUDA diagnostics, insufficient-VRAM diagnostics, stable
  unsupported operations, request immutability, normalized results, mocked supported calls, and
  upstream error translation.
- The pinned official source shape, CLI arguments, installation guidance, repository licenses,
  model-card licenses, immutable model revisions, and published LFS weight digests from primary
  upstream sources.
- `uv run pytest`: 30 passed.
- `uv run ruff format --check .`: 20 files already formatted.
- `uv run ruff check .`: passed.
- `uv run basedpyright`: 0 errors, 0 warnings, 0 notes.

Not validated:

- YuE dependencies were not installed because the official stack requires CUDA and the test machine
  has no NVIDIA device.
- No model weights were downloaded.
- No CUDA model load, inference, audio-quality review, wall-time measurement, or memory measurement
  was run.
- No generation benchmark ran, and the upstream H800 and RTX 4090 numbers remain unverified here.
- Actual NVIDIA runtime validation remains required on a CUDA 11.8-or-newer host with the exact
  checkpoint identities and digests recorded in its hardware report.
