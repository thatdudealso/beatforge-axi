from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from audio.ffmpeg import probe_audio
from cli.app import app

runner = CliRunner()


def test_generate_writes_artifact_and_toon_summary(tmp_path: Path) -> None:
    out = tmp_path / "track.mp3"

    result = runner.invoke(
        app,
        [
            "generate",
            "--prompt",
            "dusty lo-fi beat",
            "--duration",
            "12",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0
    assert out.exists()
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "operation: generate",
        "status: ok",
        "engine: fake",
        "artifacts[1]: path,media_type,duration_s",
        f"  {out},audio/mpeg,12.0",
    ]


def test_repaint_reports_unsupported_for_generate_only_engine(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"fake audio")

    result = runner.invoke(
        app,
        [
            "--engine",
            "fake-generate-only",
            "repaint",
            "--in",
            str(source),
            "--section",
            "0:03-0:05",
            "--prompt",
            "add hats",
        ],
    )

    assert result.exit_code == 1
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "operation: repaint",
        "status: error",
        "code: unsupported",
        "message: fake-generate-only does not support repaint",
    ]


def test_unknown_engine_returns_structured_toon_error(tmp_path: Path) -> None:
    out = tmp_path / "track.mp3"

    result = runner.invoke(
        app,
        [
            "--engine",
            "missing",
            "generate",
            "--prompt",
            "beat",
            "--duration",
            "4",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 1
    assert result.stdout.splitlines() == [
        "operation: generate",
        "status: error",
        "code: engine_unavailable",
        "message: unknown engine: missing",
    ]


def test_invalid_request_returns_structured_toon_validation_error(tmp_path: Path) -> None:
    out = tmp_path / "track.mp3"

    result = runner.invoke(
        app,
        ["generate", "--prompt", "", "--duration", "4", "--out", str(out)],
    )

    assert result.exit_code == 1
    assert result.stderr == ""
    assert result.stdout.startswith(
        "operation: generate\nstatus: error\ncode: validation_error\nmessage: prompt:"
    )


def test_analyze_returns_toon_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"fake audio")

    result = runner.invoke(app, ["analyze", "--file", str(source)])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "operation: analyze",
        "status: ok",
        "engine: fake",
        "metadata:",
        "  bpm: 90",
        "  key: C minor",
    ]


def test_synth_generate_returns_ok_and_playable_mp3(tmp_path: Path) -> None:
    out = tmp_path / "auraflow-bf-synth.mp3"

    result = runner.invoke(
        app,
        [
            "--engine",
            "synth",
            "generate",
            "--prompt",
            "soft focus drone",
            "--duration",
            "1.0",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "operation: generate",
        "status: ok",
        "engine: synth",
        "artifacts[1]: path,media_type,duration_s",
        f"  {out},audio/mpeg,1.0",
    ]
    probe = probe_audio(out)
    assert abs(probe.duration_s - 1.0) < 0.12
    assert probe.peak_amplitude > 0.01
    assert probe.finite


def test_acestep_generate_fails_closed_when_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BEATFORGE_ACESTEP_PROJECT_ROOT", raising=False)
    out = tmp_path / "auraflow-bf-daily.mp3"

    result = runner.invoke(
        app,
        [
            "--engine",
            "acestep",
            "generate",
            "--prompt",
            "dusty lo-fi beat with warm Rhodes",
            "--duration",
            "2",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 1
    assert not out.exists()
    lines = result.stdout.splitlines()
    assert lines[0] == "operation: generate"
    assert lines[1] == "status: error"
    assert lines[2] == "code: engine_unavailable"
    assert lines[3].startswith("message: ")
    assert "acestep" in lines[3].lower()
