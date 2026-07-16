from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

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
