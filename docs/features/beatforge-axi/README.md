# BeatForge AXI Core Feature Track

## Current Status

Active. BeatForge has a merged Phase 0 through Phase 4 scaffold, but it is not a complete music-generation product yet. The current implementation is suitable for contract validation, fake-engine CLI flows, adapter readiness gates, and CueLab/API integration development.

It is not complete until real local engine execution, artifact serving, FFmpeg post-processing, MP3 playback/export, and hardware validation are implemented and verified.

## Source of Truth

- Architecture: `../../architecture.md`
- Testing strategy: `../../testing.md`
- ACE-Step spike: `../../spikes/acestep.md`
- MusicGen spike: `../../spikes/musicgen.md`
- YuE spike: `../../spikes/yue.md`
- Agent usage skill: `../../../skill/SKILL.md`
- Onboarding page: `../../../index.html`

## Current Behavior

- CLI commands exist for `generate`, `repaint`, `remix`, `stems`, `analyze`, and `serve`.
- CLI success and error output is TOON-shaped.
- Unknown engines, unsupported capabilities, and request validation errors return structured errors.
- The default runtime engine is a real local synthesis engine ("synth") that produces actual playable PCM audio (WAV or MP3). Heavy model adapters (ACE-Step, etc.) remain behind readiness gates.
- The loopback API exposes `/v1/manifest` and accepts `/v1/jobs/{operation}` only after engine, capability, and request-schema validation.
- Phase 1 adapters for ACE-Step, MusicGen, and YuE are present behind readiness and provenance gates.
- No proprietary music service is integrated.

## Not Complete Yet

- Real job execution is not wired through the `/v1/jobs/{operation}` API.
- Generated artifacts are not served by URL.
- CueLab cannot play a generated artifact yet because the API does not return playable artifact URLs.
- FFmpeg normalize, duration trim, loop-boundary processing, and MP3 export pipeline are not implemented.
- Hardware-backed inference was not run for ACE-Step, YuE, or MusicGen.
- `--full` metadata expansion and production job progress/SSE are not implemented.
- The AXI catalog submission is not prepared.

## Decisions

- Keep all engines behind the shared adapter contract and capability metadata.
- Keep MusicGen inactive unless an MIT or Apache-2.0 compatible checkpoint is explicitly configured and verified.
- Use ACE-Step 1.5 as the default-engine candidate, not as a verified fully running default until local weights and runtime validation are complete.
- Treat the fake engine as a CI and UI development tool, not as real music generation.
- Reject Suno and all proprietary music services completely.

## Known Risks

- Documentation can overstate completion if it does not distinguish scaffolding from playable generated music.
- The current local API queues jobs but does not execute them.
- Hardware and model-weight requirements can be substantial and are not covered by ordinary CI.
- The current adapters protect readiness and provenance, but real runtime behavior still needs machine-specific validation.

## Verified Evidence

- Python validation passed before merge: `uv run ruff format --check .`, `uv run ruff check .`, `uv run basedpyright`, and `uv run pytest`.
- Test suite at merge time: 116 passed.
- GitHub CI passed for PR #5 before merge.
- API smoke verified complete generate payloads queue and incomplete payloads return `validation_error`.

## Changelog

- 2026-07-16: Added feature track and recorded that BeatForge is active but not product-complete.
- 2026-07-16: Merged Phase 1 engine adapters and Phase 2 through Phase 4 scaffold.
