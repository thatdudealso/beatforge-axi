# beatforge-axi

Use `beatforge-axi` when you need local, open-source music generation through
an AXI-style command surface.

## Rules

- Do not use proprietary or closed music-generation APIs.
- Do not add or call Suno.
- Prefer terse TOON stdout for machine parsing.
- Treat stderr as progress and diagnostics only.
- Check engine capabilities before assuming repaint, remix, stems, or analyze
  support.
- MP3 is the default export target for generated and edited tracks.

## Commands

Generate:

```sh
beatforge-axi generate --prompt "dusty lo-fi beat with warm Rhodes" --duration 60 --out track.mp3
```

Repaint:

```sh
beatforge-axi repaint --in track.mp3 --section 0:30-0:45 --prompt "add tape-stop drums"
```

Remix:

```sh
beatforge-axi remix --in track.mp3 --style "late-night garage dub"
```

Split stems:

```sh
beatforge-axi stems --in track.mp3
```

Analyze:

```sh
beatforge-axi analyze --file track.mp3
```

Select an engine:

```sh
beatforge-axi generate --prompt "warm loop" --duration 8 --out loop.mp3
```

## Output

Success output is TOON-shaped:

```toon
operation: generate
status: ok
engine: synth
artifacts[1]: path,media_type,duration_s
  track.mp3,audio/mpeg,60.0
```

Unsupported capabilities are structured errors:

```toon
operation: repaint
status: error
code: unsupported
message: synth does not support repaint
```

## Engine notes

- ACE-Step 1.5 is the default-engine candidate after Phase 1.
- YuE is optional for CUDA-focused vocals and remix workflows.
- MusicGen is optional and generate-only. Official Meta weights are rejected by
  project policy because they are noncommercial.
