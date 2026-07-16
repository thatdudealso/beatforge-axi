# Testing strategy

## Required layers

### Contract tests

Every adapter runs the same tests for descriptors, capability gates, progress, cancellation, request immutability, result shape, and error translation. License activation is tested independently from adapter registration so an unconfigured adapter can still ship.

Adapter-local tests cover configuration, readiness diagnostics, optional dependency absence,
license and checkpoint provenance rejection, upstream error translation, and mocked generation
through the adapter's native runtime boundary. For ACE-Step Phase 1, unsupported repaint,
remix, stems, and analyze calls must fail before the upstream runtime is loaded. YuE Phase 1
tests mock the upstream subprocess boundary and cover configuration gates, license and
provenance rejection, optional dependency probing, no-CUDA readiness, capability declarations,
stable unsupported operations, and upstream error translation without installing the CUDA-only
stack.

### CLI end-to-end tests

Tests spawn the installed `beatforge-axi` executable in a temporary working directory with the real local synth engine (the only runtime engine in the finished state). They assert exit codes, stdout TOON shape, clean stderr on completion, progress on stderr while running, collision behavior, and output artifacts that contain real PCM audio data.

Unknown flags and missing required values must fail before an engine is loaded. Unsupported capabilities must return a stable error and actionable help.

### Audio tests

Generated fixtures pass through the real FFmpeg boundary. Tests decode the MP3, verify requested duration within one frame, inspect loop edges, and assert that output is non-silent and finite. Hardware engines are not required in ordinary CI.

### API and CueLab tests

The real synth engine (local PCM synthesis) runs behind the HTTP server. The server returns real artifact URLs at `/v1/artifacts/{token}`. CueLab in its standalone repo polls jobs, receives playable URLs, and supports Web Audio playback + export download. Desktop and mobile manual verification plus future Playwright cover generate → play → export.

## Test commands

```sh
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run basedpyright
```

CueLab currently has a React/Vite deck in its own repo. Its Playwright suite
will be added with the first browser-backed workflow.

## Hardware suites

Hardware tests are opt-in and labeled by adapter and device. Every report records the upstream
commit, checkpoint identifier, immutable digest or revision, verified license and provenance URL,
downloaded byte size when weights are fetched, device, precision, prompt, requested duration,
wall time, peak memory when measurable, produced artifact hash, and any failure reason.

- ACE-Step: MPS and CUDA
- YuE: CUDA with the exact configured checkpoint identities and digests
- MusicGen: only a checkpoint that passes the model license and provenance gate

Hardware failures never get hidden as ordinary CI skips. The report must state that the suite was not run and why.
