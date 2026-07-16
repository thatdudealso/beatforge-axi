from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

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
