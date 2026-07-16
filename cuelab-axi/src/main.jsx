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
const engineCapabilities = {
  fake: ["generate", "repaint", "remix", "stems", "analyze"],
  "fake-generate-only": ["generate"],
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
  const [duration, setDuration] = useState(60);
  const [preset, setPreset] = useState("lo-fi");
  const [engine, setEngine] = useState("fake");
  const [job, setJob] = useState(null);
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
    try {
      const response = await fetch(operations[operation], {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ engine, ...body })
      });
      const payload = await response.json();
      setJob({ operation, status: response.ok ? "done" : "error", route: operations[operation], payload });
    } catch (error) {
      setJob({ operation, status: "offline", route: operations[operation], payload: String(error) });
    }
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
                <option value="fake">fake</option>
                <option value="fake-generate-only">fake-generate-only</option>
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
        <button className="iconButton" title="Preview">
          <Play size={18} aria-hidden="true" />
        </button>
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
