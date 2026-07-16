from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import numpy as np
import pytest

from engine.errors import EngineValidationError, UnsupportedOperationError
from engine.models import GenerateRequest, OperationContext
from engine.synth import SynthEngine
from engine.synth import adapter as synth_adapter


def test_generate_seed_makes_wav_output_reproducible(tmp_path: Path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"

    async def generate(path: Path) -> None:
        await SynthEngine().generate(
            GenerateRequest(
                prompt="warm lofi",
                duration_s=0.1,
                out=path,
                seed=123,
            ),
            OperationContext(job_id=path.stem, workspace=tmp_path / path.stem),
        )

    asyncio.run(generate(first))
    asyncio.run(generate(second))

    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize(
    ("suffix", "expected_codec", "expected_bitrate"),
    [
        (".flac", "flac", None),
        (".mp3", "libmp3lame", "192k"),
        (".ogg", "libvorbis", "192k"),
    ],
)
def test_ffmpeg_convert_uses_real_encoder_when_filtering(
    suffix: str,
    expected_codec: str,
    expected_bitrate: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(
        cmd: list[str],
        *,
        check: bool,
        stdout: int,
        stderr: int,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(synth_adapter.subprocess, "run", run)
    monkeypatch.setattr("engine.synth.adapter._has_ffmpeg", lambda: True)

    asyncio.run(
        SynthEngine().generate(
            GenerateRequest(
                prompt="warm lofi",
                duration_s=0.1,
                out=tmp_path / f"out{suffix}",
                seed=123,
            ),
            OperationContext(job_id=suffix, workspace=tmp_path / suffix),
        )
    )

    cmd = calls[0]
    assert cmd[cmd.index("-c:a") + 1] == expected_codec
    if expected_bitrate is None:
        assert "-b:a" not in cmd
    else:
        assert cmd[cmd.index("-b:a") + 1] == expected_bitrate


def test_non_wav_generation_stages_wav_inside_operation_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested = tmp_path / "song.mp3"
    sibling_wav = tmp_path / "song.wav"
    sibling_wav.write_bytes(b"existing-user-audio")
    workspace = tmp_path / "workspace"
    converted_from: list[Path] = []

    def convert(src: Path, dst: Path, target_duration: float | None = None) -> None:
        converted_from.append(src)
        dst.write_bytes(b"mp3")

    monkeypatch.setattr("engine.synth.adapter._has_ffmpeg", lambda: True)
    monkeypatch.setattr("engine.synth.adapter._ffmpeg_convert", convert)

    asyncio.run(
        SynthEngine().generate(
            GenerateRequest(
                prompt="warm lofi",
                duration_s=0.1,
                out=requested,
                seed=123,
            ),
            OperationContext(job_id="job", workspace=workspace),
        )
    )

    assert sibling_wav.read_bytes() == b"existing-user-audio"
    assert converted_from == [workspace / "job" / "song.wav"]


def test_ffmpeg_convert_reports_structured_conversion_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(
        cmd: list[str],
        *,
        check: bool,
        stdout: int,
        stderr: int,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(
            1,
            cmd,
            stderr="encoder missing\nconversion exploded",
        )

    monkeypatch.setattr(synth_adapter.subprocess, "run", run)
    monkeypatch.setattr("engine.synth.adapter._has_ffmpeg", lambda: True)

    with pytest.raises(UnsupportedOperationError, match="FFmpeg mp3 export failed"):
        asyncio.run(
            SynthEngine().generate(
                GenerateRequest(
                    prompt="warm lofi",
                    duration_s=0.1,
                    out=tmp_path / "out.mp3",
                    seed=123,
                ),
                OperationContext(job_id="ffmpeg", workspace=tmp_path / "workspace"),
            )
        )


@pytest.mark.parametrize("duration_s", [0.0, 300.1])
def test_synth_rejects_unsupported_duration_before_allocating_audio(
    duration_s: float, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def synthesize(
        params: dict[str, float], duration_s: float, rng: np.random.Generator
    ) -> np.ndarray:
        raise AssertionError("synthesis should not start for invalid duration")

    monkeypatch.setattr("engine.synth.adapter._synthesize", synthesize)

    request = GenerateRequest.model_construct(
        prompt="warm lofi",
        duration_s=duration_s,
        out=tmp_path / "out.wav",
        seed=None,
    )

    with pytest.raises(EngineValidationError, match="duration_s must be"):
        asyncio.run(
            SynthEngine().generate(
                request,
                OperationContext(job_id="duration", workspace=tmp_path / "workspace"),
            )
        )
