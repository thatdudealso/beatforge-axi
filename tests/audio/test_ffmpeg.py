from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

from audio.ffmpeg import (
    FFmpegUnavailableError,
    encode_wav_to_mp3,
    probe_audio,
    require_ffmpeg,
)


def _write_tone_wav(path: Path, *, duration_s: float = 0.25, sample_rate: int = 44_100) -> None:
    frame_count = int(duration_s * sample_rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            sample = int(8_000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        handle.writeframes(bytes(frames))


def test_require_ffmpeg_finds_binaries_on_path() -> None:
    tools = require_ffmpeg()
    assert Path(tools.ffmpeg).is_file()
    assert Path(tools.ffprobe).is_file()


def test_encode_wav_to_mp3_produces_audible_file(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    mp3 = tmp_path / "tone.mp3"
    _write_tone_wav(wav, duration_s=0.5)

    encode_wav_to_mp3(wav, mp3)

    assert mp3.is_file()
    assert mp3.stat().st_size > 500
    probe = probe_audio(mp3)
    assert abs(probe.duration_s - 0.5) < 0.08
    assert probe.peak_amplitude > 0.01
    assert probe.finite


def test_encode_wav_to_mp3_fails_closed_when_ffmpeg_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav = tmp_path / "tone.wav"
    mp3 = tmp_path / "tone.mp3"
    _write_tone_wav(wav)

    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    (tmp_path / "empty-bin").mkdir()

    with pytest.raises(FFmpegUnavailableError, match="ffmpeg not found on PATH"):
        encode_wav_to_mp3(wav, mp3)
