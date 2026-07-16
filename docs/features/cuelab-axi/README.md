# CueLab AXI UI Feature Track

## Current Status

Active. CueLab has a merged React/Vite deck UI scaffold that can be opened in a browser, submit complete local job payloads to BeatForge's `/v1` API, and play/export returned audio artifacts. It is not a finished music workstation yet.

CueLab is not complete until it can render real waveform data from returned audio, handle long-running job progress, and provide tested edit workflows against real artifacts.

## Source of Truth

- CueLab README: `../../../cuelab-axi/README.md`
- CueLab source: `../../../cuelab-axi/src/main.jsx`
- CueLab styles: `../../../cuelab-axi/src/styles.css`
- API boundary: `../../../core/server.py`
- Operation manifest: `../../../core/manifest.py`
- Architecture: `../../architecture.md`
- Testing strategy: `../../testing.md`

## Current Behavior

- The UI opens as a deck-style workspace with easy and advanced modes.
- Easy mode includes engine selection, prompt, duration, preset, Generate, and job status.
- Advanced mode includes Repaint, Remix, Stems, Analyze, Loop, and Export controls.
- Capability gating disables unsupported advanced operations for generate-only engines.
- Generate submits a complete payload to `/v1/jobs/generate` through the Vite proxy, polls job status, and captures returned artifact URLs.
- Play and export controls consume the returned artifact URLs.
- Desktop and mobile browser smoke checks were performed with `chrome-devtools-axi`.

## Not Complete Yet

- CueLab does not render real waveform data from audio.
- Repaint, remix, stems, analyze, and loop controls are UI/API scaffold only.
- No Playwright suite is committed yet.
- No screenshot regression suite is committed yet.
- No production static-serving path from `beatforge-axi serve` is implemented.

## Decisions

- CueLab must call the same BeatForge operations as the CLI.
- The browser must not shell out.
- The UI should gate controls from engine capabilities, not hardcoded assumptions.
- CueLab should be a usable workspace first, not a landing page.

## Known Risks

- Users may assume Generate is the only finished workflow; play and export already work, but edit workflows remain scaffolded.
- Placeholder file paths are development defaults and need artifact-service replacement.
- Without real waveform rendering and edit workflow coverage, deck controls remain partially scaffolded.
- Browser tests must cover desktop/mobile layout before CueLab is treated as stable.

## Verified Evidence

- `corepack pnpm run build` passed before merge.
- Browser smoke with `chrome-devtools-axi` verified load, responsive layout, capability gating, and Generate job submission.
- API smoke verified `/v1/jobs/generate` accepts a payload and the real synth engine returns playable artifact URLs.

## Changelog

- 2026-07-16: Added feature track and recorded CueLab as active but not product-complete.
- 2026-07-16: Merged React/Vite deck scaffold and local `/v1` API integration.
