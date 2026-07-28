# Project agent instructions

- Keep BeatForge local-first. Do not add proprietary or closed music services, SDKs, APIs, feature flags, or optional backends.
- Runtime model weights must have verified MIT or Apache-2.0 provenance. Adapter code may ship unconfigured, but activation must fail closed when model license or provenance is missing.
- Keep engine-specific types and dependency imports inside `engine/<adapter>/`. The CLI, API, core, and CueLab consume only shared contracts.
- Every operation must retain CLI, API, and CueLab parity through `core/manifest.py` and its tests.
- Follow AXI conventions: TOON on stdout, progress on stderr, no prompts, structured errors, minimal default fields, and early unknown-flag rejection.
- Develop behavior test-first. Run formatting, lint, strict typing, and the relevant end-to-end tests before submitting work.
- Do not edit generated skills or generated onboarding manifests directly. Change their source and run the generator.
- Do not manually edit any `CHANGELOG.md` if one is added by release automation.

## Cursor Cloud specific instructions

Two services make up the product. The update script already refreshes both
dependency sets (`uv sync --extra dev` and `pnpm --dir cuelab-axi install`), so
you only need to start them.

- Backend (Python AXI CLI + loopback API): `uv run beatforge-axi serve --host 127.0.0.1 --port 8765`. Standard checks/commands live in `README.md`, `pyproject.toml`, and `docs/testing.md` (ruff format/check, basedpyright, pytest); prefer those over duplicating.
- CueLab UI (`cuelab-axi/`): `pnpm --dir cuelab-axi dev` serves Vite on `127.0.0.1:5173`. Its `vite.config.js` proxies `/v1` to `127.0.0.1:8765`, so the backend must be running on 8765 for any UI generate/repaint/remix/stems/analyze call to succeed; otherwise the job panel shows `offline`.
- Only the `fake` (and `fake-generate-only`) engine reports `ready: true`. `acestep`, `yue`, and `musicgen` intentionally fail closed (`ready: false`) until verified local MIT/Apache-2.0 weights are configured, so CLI/UI/API calls against them returning `engine_unavailable`/`unsupported` is expected, not a bug. Use `--engine fake` (the default) for local end-to-end runs.
- `uv` is installed under `~/.local/bin` (already on `PATH` via `~/.profile`).
