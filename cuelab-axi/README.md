# CueLab-axi

CueLab-axi is the planned human interface for BeatForge. It will be a local web
app styled as a turntable/deck and backed by the same BeatForge operations that
agents use through `beatforge-axi`.

The UI is not scaffolded yet. This README defines the intended product surface,
integration boundary, and contribution expectations before implementation
begins.

## Product shape

CueLab should open directly into the usable music workspace. It is not a landing
page and should not explain itself on screen. The first screen should make the
track, prompt, deck state, and export path visible immediately.

Primary modes:

- Easy mode: prompt box, duration, preset style controls, engine selector,
  generate button, recent takes, and export.
- Advanced mode: waveform-on-platter view, section repaint tool, remix controls,
  stem mixer, loop-point editor, analysis panel, and job history.

The interface must gate controls by engine capability. If the active engine does
not support repaint, remix, stems, or analysis, the related controls should be
disabled with a concise reason from the engine descriptor.

## Integration boundary

CueLab does not shell out from the browser. It talks to the local BeatForge
runtime served by `beatforge-axi serve`.

Target routes are versioned under `/v1` and mirror the operation manifest:

| CueLab control | Operation | Route |
| --- | --- | --- |
| Prompt deck | `generate` | `/v1/jobs/generate` |
| Waveform repaint region | `repaint` | `/v1/jobs/repaint` |
| Remix style controls | `remix` | `/v1/jobs/remix` |
| Stem mixer | `stems` | `/v1/jobs/stems` |
| Track analysis panel | `analyze` | `/v1/jobs/analyze` |

Long-running operations should create jobs and stream progress through server
sent events. The same operation service must back the CLI and the UI so the two
surfaces cannot drift.

## Expected workflows

Easy generation:

1. Choose an engine or keep the configured default.
2. Enter a prompt and duration.
3. Generate a take.
4. Preview, keep, retry, or export MP3.

Advanced editing:

1. Load a generated or imported track.
2. Select a section on the platter waveform.
3. Repaint the section when the engine supports it.
4. Adjust loop points and crossfade boundaries.
5. Split stems or remix when available.
6. Export the final MP3 and operation metadata.

## Design principles

- Build the actual deck as the app, not a marketing wrapper.
- Keep layout dense, calm, and useful for repeated editing.
- Use engine capability data to drive visible states.
- Keep controls stable so generated labels, progress, and errors do not resize
  the workspace.
- Use icons for deck tools where available and include hover tooltips.
- Verify desktop and mobile layouts with screenshots before merging UI changes.
- Do not hide missing engine support behind fake controls.

## Planned implementation

Expected stack:

- React and TypeScript
- Vite
- pnpm
- local BeatForge API client generated or derived from the operation manifest
- Playwright for end-to-end UI workflows
- screenshot checks for desktop and mobile deck layouts

The scaffold should live under `cuelab-axi/` and avoid duplicating BeatForge
engine rules. Engine support, warnings, artifact metadata, and job progress come
from the local API.

## Testing expectations

CueLab changes should include:

- Playwright coverage for easy generation with the fake engine;
- capability-gating tests for repaint, remix, stems, and analysis;
- cancellation and progress behavior;
- export flow coverage;
- desktop and mobile screenshots reviewed for overlap, clipping, blank canvas
  states, and text overflow.

Hardware model inference is not required for ordinary UI CI. The fake engine
should exercise the same API contracts.

## Current status

CueLab is in the planning stage. The operation manifest already names the UI
controls and routes that CueLab must implement. The React app, local API server,
and API client will be added after the BeatForge CLI and job runtime land.
