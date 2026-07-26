from __future__ import annotations

from pathlib import Path

import pytest

from audio.ffmpeg import probe_audio
from engine.errors import UnsupportedOperationError
from engine.models import (
    AnalyzeRequest,
    GenerateRequest,
    LicenseId,
    Operation,
    OperationContext,
    RemixRequest,
    RepaintRequest,
    StemsRequest,
    TimeRange,
)
from engine.synth import SynthEngine


def _context(tmp_path: Path) -> OperationContext:
    return OperationContext(job_id="job-synth", workspace=tmp_path / "jobs")


@pytest.mark.asyncio
async def test_synth_generate_writes_playable_mp3(tmp_path: Path) -> None:
    out = tmp_path / "drone.mp3"
    engine = SynthEngine()
    request = GenerateRequest(
        prompt="soft focus drone",
        duration_s=1.0,
        out=out,
        seed=7,
    )

    result = await engine.generate(request, _context(tmp_path))

    assert engine.descriptor.name == "synth"
    assert engine.descriptor.model_license is LicenseId.MIT
    assert engine.descriptor.ready is True
    assert engine.descriptor.capabilities.supported_operations() == {Operation.GENERATE}
    assert result.operation is Operation.GENERATE
    assert result.artifacts[0].path == out
    assert result.artifacts[0].media_type == "audio/mpeg"
    assert result.artifacts[0].duration_s == 1.0
    probe = probe_audio(out)
    assert abs(probe.duration_s - 1.0) < 0.12
    assert probe.peak_amplitude > 0.01
    assert probe.finite


@pytest.mark.asyncio
async def test_synth_is_generate_only(tmp_path: Path) -> None:
    engine = SynthEngine()
    source = tmp_path / "in.mp3"
    source.write_bytes(b"x")

    with pytest.raises(UnsupportedOperationError, match="repaint"):
        await engine.repaint(
            RepaintRequest(
                input_file=source,
                section=TimeRange(start_s=0, end_s=1),
                prompt="x",
                out=tmp_path / "out.mp3",
            ),
            _context(tmp_path),
        )
    with pytest.raises(UnsupportedOperationError, match="remix"):
        await engine.remix(
            RemixRequest(input_file=source, style="x", out=tmp_path / "out.mp3"),
            _context(tmp_path),
        )
    with pytest.raises(UnsupportedOperationError, match="stems"):
        await engine.stems(
            StemsRequest(input_file=source, out_dir=tmp_path / "stems"), _context(tmp_path)
        )
    with pytest.raises(UnsupportedOperationError, match="analyze"):
        await engine.analyze(AnalyzeRequest(file=source), _context(tmp_path))
