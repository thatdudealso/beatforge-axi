# Project agent instructions

- Keep BeatForge local-first. Do not add proprietary or closed music services, SDKs, APIs, feature flags, or optional backends.
- Runtime model weights must have verified MIT or Apache-2.0 provenance. Adapter code may ship unconfigured, but activation must fail closed when model license or provenance is missing.
- Keep engine-specific types and dependency imports inside `engine/<adapter>/`. The CLI, API, core, and CueLab consume only shared contracts.
- Every operation must retain CLI, API, and CueLab parity through `core/manifest.py` and its tests.
- Follow AXI conventions: TOON on stdout, progress on stderr, no prompts, structured errors, minimal default fields, and early unknown-flag rejection.
- Develop behavior test-first. Run formatting, lint, strict typing, and the relevant end-to-end tests before submitting work.
- Do not edit generated skills or generated onboarding manifests directly. Change their source and run the generator.
- Do not manually edit any `CHANGELOG.md` if one is added by release automation.
