from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from cli.app import app

runner = CliRunner()


def test_generate_writes_artifact_and_toon_summary(tmp_path: Path) -> None:
    # Request WAV explicitly: synth always produces real PCM; MP3 requires ffmpeg in PATH.
    out = tmp_path / "track.wav"

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
    # Real audio engine now (synth). No fake bytes anywhere in production path.
    assert "engine: synth" in result.stdout
    assert "artifacts[1]: path,media_type,duration_s" in result.stdout
    assert str(out) in result.stdout


def test_repaint_reports_unsupported_for_synth_engine(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"placeholder")

    result = runner.invoke(
        app,
        [
            "--engine",
            "synth",
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
    # The real synth raises a concise UnsupportedOperationError
    prefix = "operation: repaint\nstatus: error\ncode: unsupported\nmessage:"
    assert result.stdout.startswith(prefix)
    assert "synth does not support repaint" in result.stdout


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


def test_analyze_is_unsupported_on_synth(tmp_path: Path) -> None:
    # Synth is the real audio engine for generate only (per finished state: no fake).
    # Other operations are explicitly unsupported until implemented.
    source = tmp_path / "source.mp3"
    source.write_bytes(b"placeholder")

    result = runner.invoke(app, ["analyze", "--file", str(source)])

    assert result.exit_code == 1
    assert "code: unsupported" in result.stdout
    assert "synth does not support analyze" in result.stdout
