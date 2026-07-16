# MusicGen Phase 1 spike

## Decision

BeatForge ships an optional AudioCraft MusicGen adapter that advertises text generation only.
It remains inactive until the operator supplies a local, self-contained MusicGen checkpoint and
independently attests its identity, SHA-256 digest, provenance, and MIT or Apache-2.0 weights
license. Repaint, remix, stems, and analysis return stable unsupported-operation errors without
importing AudioCraft.

Meta's official MusicGen weights are not eligible. The adapter does not select, download, cache,
activate, or smoke-test them. It passes only the configured local directory to AudioCraft and
rejects a compression package containing a `pretrained` reference before model construction. It
also rejects conditioner configurations that can resolve auxiliary models remotely. Text
conditioners must be self-contained LUTs or T5 assets stored inside the checkpoint directory.

## Upstream source examined

Research was performed on 2026-07-16 against AudioCraft `main` commit
[`896ec7c47f5e5d1e5aa1e4b260c4405328bf009d`](https://github.com/facebookresearch/audiocraft/commit/896ec7c47f5e5d1e5aa1e4b260c4405328bf009d),
committed 2025-03-13. All source links below are pinned to that commit.

- Installation: the upstream README specifies Python 3.9, PyTorch 2.1.0, and recommends FFmpeg.
  See [README installation](https://github.com/facebookresearch/audiocraft/blob/896ec7c47f5e5d1e5aa1e4b260c4405328bf009d/README.md#L10-L30)
  and the [pinned requirements](https://github.com/facebookresearch/audiocraft/blob/896ec7c47f5e5d1e5aa1e4b260c4405328bf009d/requirements.txt).
- Hardware: upstream says medium 1.5B inference needs at least 16 GB of GPU memory, recommends a
  16 GB GPU generally, and notes that short sequences or the small model can use less. See
  [MusicGen installation and API](https://github.com/facebookresearch/audiocraft/blob/896ec7c47f5e5d1e5aa1e4b260c4405328bf009d/docs/MUSICGEN.md#L29-L87).
  `MusicGen.get_pretrained` auto-selects CUDA when available and otherwise CPU, but upstream's
  user documentation says a GPU is required for local use. CPU and MPS are therefore not claimed
  as validated hardware targets by this spike.
- Generation API: `MusicGen.get_pretrained(local_path, device=...)`,
  `set_generation_params(duration=...)`, and `generate([prompt], progress=False)` return audio
  shaped as batch, channels, frames. See
  [`MusicGen`](https://github.com/facebookresearch/audiocraft/blob/896ec7c47f5e5d1e5aa1e4b260c4405328bf009d/audiocraft/models/musicgen.py#L28-L105)
  and
  [`BaseGenModel.generate`](https://github.com/facebookresearch/audiocraft/blob/896ec7c47f5e5d1e5aa1e4b260c4405328bf009d/audiocraft/models/genmodel.py#L135-L164).
  Audio is written with `audio_write`, as shown in the
  [official example](https://github.com/facebookresearch/audiocraft/blob/896ec7c47f5e5d1e5aa1e4b260c4405328bf009d/docs/MUSICGEN.md#L69-L87).
- Local checkpoint loading: a directory is loaded from `state_dict.bin` for the language model
  and `compression_state_dict.bin` for the tokenizer. Exported packages contain `xp.cfg` and
  `best_state`. See the
  [checkpoint loaders](https://github.com/facebookresearch/audiocraft/blob/896ec7c47f5e5d1e5aa1e4b260c4405328bf009d/audiocraft/models/loaders.py#L7-L126)
  and
  [export utilities](https://github.com/facebookresearch/audiocraft/blob/896ec7c47f5e5d1e5aa1e4b260c4405328bf009d/audiocraft/utils/export.py#L20-L79).
  A compression package with a `pretrained` field delegates to another model loader, so BeatForge
  rejects that shape. A compatible checkpoint must bundle its compression model instead.
- Licenses: AudioCraft code is MIT under the
  [repository LICENSE](https://github.com/facebookresearch/audiocraft/blob/896ec7c47f5e5d1e5aa1e4b260c4405328bf009d/LICENSE),
  while Meta's released weights are CC-BY-NC-4.0 under
  [LICENSE_weights](https://github.com/facebookresearch/audiocraft/blob/896ec7c47f5e5d1e5aa1e4b260c4405328bf009d/LICENSE_weights)
  and the
  [MusicGen model card](https://github.com/facebookresearch/audiocraft/blob/896ec7c47f5e5d1e5aa1e4b260c4405328bf009d/model_cards/MUSICGEN_MODEL_CARD.md#model-details).
  The official identifiers listed by upstream all refer to those noncommercial weights. BeatForge
  rejects `facebook/musicgen*` identities and AudioCraft's official short aliases.

## Supplying an eligible checkpoint

Provision AudioCraft only inside the worktree-local uv environment. Do not use global Python or
global `pip`. The pinned upstream stack can be staged in a Python 3.11 BeatForge environment with
uv, subject to platform wheel availability:

```sh
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python 'torch==2.1.0'
uv pip install --python .venv/bin/python \
  'audiocraft @ git+https://github.com/facebookresearch/audiocraft.git@896ec7c47f5e5d1e5aa1e4b260c4405328bf009d'
```

This installs code only. Do not pass an official model name to AudioCraft and do not download
official MusicGen weights. Put the independently obtained permissive checkpoint in a local
directory with this shape:

```text
/absolute/path/to/checkpoint/
  state_dict.bin
  compression_state_dict.bin
  aux/
    t5-base/
      config.json
      ...
```

`compression_state_dict.bin` must contain its own `xp.cfg` and `best_state`; it must not contain a
`pretrained` reference. The language model file must contain the compatible exported `xp.cfg` and
`best_state` expected by the pinned loaders. A T5 conditioner must name a relative directory such
as `aux/t5-base` with a `config.json` declaring `d_model` or `hidden_size`; absolute paths,
missing paths, and ordinary Hugging Face identifiers are rejected. LUT conditioners must use the
self-contained `noop` tokenizer. Other upstream conditioner types are rejected because the
reviewed constructors can resolve hard-coded or configured remote models. The checkpoint digest
and provenance evidence must cover every bundled auxiliary file and its MIT or Apache-2.0 weights
license. Symbolic links and non-regular filesystem entries are rejected.

The directory digest is deterministic. Files are sorted by relative POSIX path. For each file,
the hash stream receives the path byte length as an unsigned 8-byte big-endian integer, the path
bytes, the file size in the same integer format, and the file bytes. All files under the directory
are included. Use the adapter helper rather than reproducing this algorithm:

```python
from pathlib import Path

from engine.models import LicenseId
from engine.musicgen import MusicGenConfig, MusicGenEngine, checkpoint_sha256

checkpoint = Path("/absolute/path/to/checkpoint")
config = MusicGenConfig(
    checkpoint=checkpoint,
    checkpoint_id="publisher/musicgen-compatible-v1",
    checkpoint_sha256=checkpoint_sha256(checkpoint),
    model_license=LicenseId.APACHE_2_0,
    provenance_url="https://publisher.example/model-card/musicgen-compatible-v1",
    provenance_verified=True,
    device="cuda",
)
engine = MusicGenEngine(config)
report = engine.readiness()
```

The provenance page must independently identify the exact checkpoint, publisher or training
origin, digest, and weights license. Set `provenance_verified=True` only after reviewing that
evidence outside BeatForge. The adapter intentionally does not infer a license from the local
filename, checkpoint identity, repository name, or checkpoint contents. It also does not fetch a
provenance URL at runtime. The explicit verification flag is an operator attestation, not an
automatic legal conclusion. Required string evidence is stripped for validation, and the
provenance location must be an absolute HTTP or HTTPS URL.

Readiness diagnostics are stable codes and explain missing identity, digest, license, provenance,
invalid provenance URL, verification, dependency, local files, digest mismatch, invalid checkpoint
shape, and forbidden official checkpoints. Availability accepts only AudioCraft version `1.4.0a2`
installed from the reviewed Git commit recorded in PEP 610 `direct_url.json` metadata, with the
imported package origin resolving inside that distribution. A wheel, version-only installation,
different commit, shadowed import, or missing provenance metadata fails closed. Every gate runs
before AudioCraft imports or model loading.

## Runtime behavior

For a ready checkpoint, `generate` rechecks readiness off the event-loop thread, copies the entire
checkpoint into a private temporary snapshot, and verifies the configured directory digest against
that snapshot before loading checkpoint packages with `torch.load(weights_only=True)`. AudioCraft
package inspection, conditioner preflight, and construction use only the snapshot. The runtime
seeds PyTorch when requested, sets the requested duration, generates one prompt, and writes the
requested `.wav`, `.flac`, `.mp3`, or `.ogg` file through AudioCraft. A process-wide lock
serializes snapshot creation, model construction, seeding, inference, and export because PyTorch
seeding changes process-global RNG state and queued requests must not duplicate multi-gigabyte
snapshots. The result contains the artifact media type and duration plus sample rate, channels,
frame count, seed, checkpoint identity, digest, model license, provenance URL, and verification
status. Output setup and native failures are translated to `EngineUnavailableError` with a stable
adapter message and the original exception retained as the cause.

## Validation record

Validated in this worktree:

- The pinned upstream source, documentation, checkpoint loaders, export shape, generation calls,
  installation constraints, hardware guidance, code license, and weight license were reviewed
  from the primary URLs above.
- Adapter tests exercised configuration, protocol conformance, capabilities, all readiness gates,
  MIT and Apache-2.0 acceptance, missing optional dependency behavior, CC-BY-NC and official
  checkpoint rejection before load, deterministic digest matching, stable unsupported operations,
  native error translation, and artifact metadata.
- The AudioCraft boundary was exercised with a complete fake matching the pinned API, including
  exact build metadata and import origin, safe checkpoint package loading, immutable snapshot
  loading, local conditioner preflight, concurrent snapshot and seed serialization, device and
  seed forwarding, duration configuration, prompt generation, waveform shape, and audio export.
- Project pytest, Ruff formatting, Ruff lint, and basedpyright checks were run in the uv-managed
  worktree environment.

Not runtime-validated:

- AudioCraft was not installed or imported, because no eligible permissively licensed checkpoint
  was supplied and ordinary CI must not acquire model dependencies or weights.
- No real checkpoint was loaded. No Meta official checkpoint was downloaded, cached, activated,
  or smoke-tested.
- No CPU, CUDA, or MPS inference, audio quality, duration accuracy after decoding, wall time, peak
  memory, or hardware compatibility measurement was performed.
- The operator's future provenance evidence and checkpoint license were not independently
  reviewed as part of this code-only spike.
