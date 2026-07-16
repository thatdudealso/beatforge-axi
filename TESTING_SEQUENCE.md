# beatforge-axi + cuelab-axi Pre-PR Testing Sequence

**Strict rule**: Do **not** approve the PR until you have personally run this sequence and every step returns the expected result.

**Non-negotiable requirement**: The fake engine must not be present in any production/runtime/default path.

## Current known-good snapshot (reference)

- BeatForge API: http://127.0.0.1:8765
- CueLab UI: http://127.0.0.1:5173
- Live manifest: synth ready, no fake engine anywhere
- All automated checks: green (ruff, basedpyright, pytest 116 passed, cuelab build clean)
- Known-good real audio file: `/tmp/USER-TEST-real.wav` (5s, real non-silent PCM WAV)

## 0. Start / confirm the servers

If they are not already running:

```bash
# Terminal 1
cd /Users/thatdudealso/beatforge-axi
uv run beatforge-axi serve --host 127.0.0.1 --port 8765

# Terminal 2
cd /Users/thatdudealso/beatforge-axi/cuelab-axi
corepack pnpm run dev
```

Verify they are up:
```bash
curl -sS http://127.0.0.1:8765/v1/manifest | python3 -c '
import sys, json
d = json.load(sys.stdin)
print("Engines:", sorted(d["engines"].keys()))
print("synth ready:", d["engines"]["synth"]["ready"])
print("fake present?:", any("fake" in k.lower() for k in d["engines"]))
'
```

## 1. Automated validation (run exactly these)

```bash
cd /Users/thatdudealso/beatforge-axi

uv run ruff format --check .
uv run ruff check .
uv run basedpyright
uv run pytest -q
(cd cuelab-axi && corepack pnpm run build)
```

**Expected results**:
- `42 files already formatted`
- `All checks passed!`
- `0 errors, 0 warnings, 0 notes`
- `116 passed`
- `✓ built in ...`

## 2. CLI: real audio, default engine must be synth

```bash
cd /Users/thatdudealso/beatforge-axi
rm -f /tmp/test-*.wav /tmp/test-*.mp3

uv run beatforge-axi generate \
  --prompt "upbeat garage loop" \
  --duration 6 \
  --out /tmp/test-garage.wav
```

**Expected exact output**:
```
operation: generate
status: ok
engine: synth
artifacts[1]: path,media_type,duration_s
  /tmp/test-garage.wav,audio/wav,6.0
```

**Verify it is real playable audio**:
```bash
ls -lh /tmp/test-garage.wav
file /tmp/test-garage.wav

python3 -c '
import wave
with wave.open("/tmp/test-garage.wav") as w:
    dur = w.getnframes() / w.getframerate()
    data = w.readframes(4000)
    nz = sum(1 for b in data if b != 0)
    print(f"Duration: {dur:.2f}s")
    print(f"Non-zero sample bytes: {nz}")
    print("REAL NON-SILENT PCM" if nz > 800 else "BAD - NOT REAL AUDIO")
'
```

Also play the pre-made one:
```bash
open /tmp/USER-TEST-real.wav   # or: afplay /tmp/USER-TEST-real.wav
```

**Pass criteria**:
- `engine: synth` (not fake)
- Real WAV file
- Correct duration
- Clearly audible / non-silent PCM data

## 3. Prove fake engine is absent from the running system

```bash
curl -sS http://127.0.0.1:8765/v1/manifest | python3 -c '
import sys, json
d = json.load(sys.stdin)
print("Live engines:", sorted(d["engines"].keys()))
print("synth ready:", d["engines"]["synth"]["ready"])
print("fake present anywhere?:", any("fake" in k.lower() for k in d["engines"]))
'
```

**Expected**:
- `['acestep', 'musicgen', 'synth', 'yue']`
- `synth ready: True`
- `fake present anywhere?: False`

## 4. Full browser end-to-end (the main user requirement)

1. Open **http://127.0.0.1:5173** in your browser.
2. Confirm the Engine dropdown shows **"synth (local real audio)"** selected (no fake options usable).
3. Use:
   - Prompt: `dusty lo-fi beat with warm Rhodes`
   - Duration: `8`
4. Click **Generate**.
5. Wait for status `done` + an artifact URL to appear.
6. Click **Play**.
   - Real audio must play in the browser via Web Audio.
   - It must sound like music.
7. Click **Export MP3/WAV**.
   - File downloads.
   - Play the downloaded file in any player and confirm correct duration + audible sound.

Do this at least twice with different prompts.

**Pass condition**: You can generate, hear the track in the browser deck, and successfully export + play a real audio file.

## 5. Optional but recommended: API job + artifact URL

```bash
J=$(curl -sS -X POST http://127.0.0.1:8765/v1/jobs/generate \
  -H 'content-type: application/json' \
  -d '{"prompt":"api test","duration_s":5,"out":"api.wav"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["job_id"])')

echo "Job ID: $J"
sleep 3
curl -sS "http://127.0.0.1:8765/v1/jobs/$J"
```

You should see `status: done` and an `artifacts` array with a working URL.

## 6. If servers need restarting

```bash
# Kill existing
pkill -x python3 || true
pkill -x node || true
sleep 1

# Start API
cd /Users/thatdudealso/beatforge-axi
uv run beatforge-axi serve --host 127.0.0.1 --port 8765

# Start UI (new terminal)
cd /Users/thatdudealso/beatforge-axi/cuelab-axi
corepack pnpm run dev
```

## 7. Approval condition

When you are satisfied, reply with something like:

> Approved. All steps passed. Fake is gone. Real audio works end-to-end. Ready to finish no-mistakes and raise the PR.

At that point we will drive the rest of the no-mistakes pipeline on the axi catalog PR (`feat/beatforge-axi-catalog` branch) and open the PR only through the gate.

---

**Do not** manually create PRs or push to main. Everything for the catalog contribution must go through `no-mistakes`.

Good luck with the testing. Report back with results.
TESTDOC
echo "File written successfully" && ls -l /Users/thatdudealso/beatforge-axi/TESTING_SEQUENCE.md