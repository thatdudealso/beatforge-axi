import React, { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AudioLines,
  Disc3,
  Download,
  ListMusic,
  Play,
  RefreshCw,
  Scissors,
  SlidersHorizontal,
  SplitSquareHorizontal,
  Wand2
} from "lucide-react";
import "./styles.css";

const operations = {
  generate: "/v1/jobs/generate",
  repaint: "/v1/jobs/repaint",
  remix: "/v1/jobs/remix",
  stems: "/v1/jobs/stems",
  analyze: "/v1/jobs/analyze"
};

const presets = ["lo-fi", "garage", "ambient", "dub", "synthwave"];
// Only real engines here. "synth" is the always-ready local engine that produces
// actual playable audio (WAV or MP3). Heavy models remain capability-gated.
const engineCapabilities = {
  synth: ["generate"],
  acestep: ["generate"],
  yue: ["generate", "remix"],
  musicgen: ["generate"]
};
const paths = {
  input_file: "/tmp/beatforge-cuelab/source.mp3",
  out: "/tmp/beatforge-cuelab/take.mp3",
  out_dir: "/tmp/beatforge-cuelab/stems"
};

function App() {
  const [mode, setMode] = useState("easy");
  const [prompt, setPrompt] = useState("dusty lo-fi beat with warm Rhodes");
  const [duration, setDuration] = useState(8);
  const [preset, setPreset] = useState("lo-fi");
  const [engine, setEngine] = useState("synth");
  const [job, setJob] = useState(null);
  const [audioArtifact, setAudioArtifact] = useState(null);
  const audioUrl = audioArtifact?.url || null;
  const deckLabel = useMemo(() => `${preset} / ${duration}s`, [preset, duration]);
  const enabled = useMemo(() => {
    const capabilities = new Set(engineCapabilities[engine] || []);
    return {
      generate: capabilities.has("generate"),
      repaint: capabilities.has("repaint"),
      remix: capabilities.has("remix"),
      stems: capabilities.has("stems"),
      analyze: capabilities.has("analyze")
    };
  }, [engine]);

  async function submit(operation, body) {
    setJob({ operation, status: "queued", route: operations[operation] });
    setAudioArtifact(null);
    try {
      const response = await fetch(operations[operation], {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ engine, ...body })
      });
      const payload = await response.json();
      if (!response.ok) {
        setJob({
          operation,
          status: "error",
          route: operations[operation],
          payload,
          error: payload.error || `HTTP ${response.status}`
        });
        return;
      }
      const jid = payload.job_id;
      setJob({ operation, status: "queued", route: operations[operation], payload, job_id: jid });

      // Poll for completion (real execution on server)
      if (jid) {
        pollJob(jid, operation);
      } else {
        setJob({
          operation,
          status: "error",
          route: operations[operation],
          payload,
          error: "missing_job_id"
        });
      }
    } catch (error) {
      setJob({ operation, status: "offline", route: operations[operation], payload: String(error) });
    }
  }

  async function pollJob(jobId, op) {
    const pollAttempts = 60; // ~30s
    for (let i = 0; i < pollAttempts; i++) {
      await new Promise(r => setTimeout(r, 500));
      try {
        const r = await fetch(`/v1/jobs/${jobId}`);
        const data = await r.json();
        setJob(prev => ({ ...(prev || {}), status: data.status, result: data.result || data, payload: data }));
        if (data.status === "done" && data.artifacts && data.artifacts.length > 0) {
          const first = data.artifacts[0];
          setAudioArtifact(first);
          return;
        }
        if (data.status === "error") return;
      } catch (_) {
        // keep polling
      }
    }
    setJob(prev => ({
      ...(prev || {}),
      operation: op,
      status: "timeout",
      error: "job_poll_timeout",
      job_id: jobId
    }));
  }

  function playAudio() {
    if (!audioUrl) return;
    const a = new Audio(audioUrl);
    a.play().catch(() => {});
    // keep reference simple for basic use
    window.__bf_audio = a;
  }

  async function exportAudio() {
    if (!audioUrl) return;
    const resp = await fetch(audioUrl);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = audioArtifact?.filename || "beatforge-audio";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="shell">
      <section className="deckBand">
        <div className="topbar">
          <div className="brand">
            <Disc3 size={28} aria-hidden="true" />
            <span>CueLab-axi</span>
          </div>
          <div className="modeSwitch" aria-label="Mode">
            <button className={mode === "easy" ? "active" : ""} onClick={() => setMode("easy")}>Easy</button>
            <button className={mode === "advanced" ? "active" : ""} onClick={() => setMode("advanced")}>Advanced</button>
          </div>
        </div>

        <div className="workspace">
          <div className="platter" aria-label="Waveform platter">
            <div className="record">
              <div className="grooves" />
              <AudioLines className="wave" size={92} aria-hidden="true" />
              <div className="spindle" />
            </div>
            <div className="deckMeta">
              <strong>{deckLabel}</strong>
              <span>{job ? `${job.operation} ${job.status}` : "ready"}</span>
            </div>
          </div>

          <section className="controls">
            <label>
              Engine
              <select value={engine} onChange={(event) => setEngine(event.target.value)}>
                <option value="synth">synth (local real audio)</option>
                <option value="acestep">acestep</option>
                <option value="yue">yue</option>
                <option value="musicgen">musicgen</option>
              </select>
            </label>
            <label>
              Prompt
              <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} />
            </label>
            <div className="row">
              <label>
                Duration
                <input type="number" min="1" value={duration} onChange={(event) => setDuration(Number(event.target.value))} />
              </label>
              <label>
                Preset
                <select value={preset} onChange={(event) => setPreset(event.target.value)}>
                  {presets.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
            </div>
            <button className="primary" disabled={!enabled.generate} onClick={() => submit("generate", { prompt, duration_s: duration, out: paths.out, preset })}>
              <Wand2 size={18} aria-hidden="true" />
              Generate
            </button>
          </section>
        </div>
      </section>

      {mode === "advanced" && (
        <section className="advanced">
          <Tool enabled={enabled.repaint} icon={<Scissors size={18} />} label="Repaint" onClick={() => submit("repaint", { input_file: paths.input_file, section: { start_s: 30, end_s: 45 }, prompt, out: paths.out })} />
          <Tool enabled={enabled.remix} icon={<RefreshCw size={18} />} label="Remix" onClick={() => submit("remix", { input_file: paths.input_file, style: preset, out: paths.out })} />
          <Tool enabled={enabled.stems} icon={<SplitSquareHorizontal size={18} />} label="Stems" onClick={() => submit("stems", { input_file: paths.input_file, out_dir: paths.out_dir })} />
          <Tool enabled={enabled.analyze} icon={<SlidersHorizontal size={18} />} label="Analyze" onClick={() => submit("analyze", { file: paths.input_file })} />
          <Tool enabled icon={<ListMusic size={18} />} label="Loop" onClick={() => setJob({ operation: "loop", status: "edited", route: "local" })} />
          <Tool enabled icon={<Download size={18} />} label="Export" onClick={() => setJob({ operation: "export", status: "ready", route: "local" })} />
        </section>
      )}

      <section className="jobPanel" aria-live="polite">
        <div className="playerRow">
          <button
            className="iconButton primary"
            title={audioUrl ? "Play generated audio" : "Generate first"}
            onClick={playAudio}
            disabled={!audioUrl}
          >
            <Play size={18} aria-hidden="true" />
            <span>Play</span>
          </button>
          <button
            className="iconButton"
            title={audioUrl ? "Export as audio file" : "Generate first"}
            onClick={exportAudio}
            disabled={!audioUrl}
          >
            <Download size={18} aria-hidden="true" />
            <span>Export MP3/WAV</span>
          </button>
          {audioUrl && <span className="artifactHint">artifact ready: {audioUrl}</span>}
        </div>
        <pre>{JSON.stringify(job || { status: "ready" }, null, 2)}</pre>
      </section>
    </main>
  );
}

function Tool({ enabled, icon, label, onClick }) {
  return (
    <button className="tool" disabled={!enabled} onClick={onClick} title={enabled ? label : `${label} unsupported`}>
      {icon}
      <span>{label}</span>
    </button>
  );
}

createRoot(document.getElementById("root")).render(<App />);
