from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path


class FFmpegUnavailableError(RuntimeError):
    """Raised when ffmpeg or ffprobe is missing or fails."""


@dataclass(frozen=True, slots=True)
class FFmpegTools:
    ffmpeg: str
    ffprobe: str


@dataclass(frozen=True, slots=True)
class AudioProbe:
    duration_s: float
    peak_amplitude: float
    finite: bool
    sample_rate: int
    channels: int


def require_ffmpeg() -> FFmpegTools:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        raise FFmpegUnavailableError("ffmpeg not found on PATH")
    return FFmpegTools(ffmpeg=ffmpeg, ffprobe=ffprobe)


def encode_wav_to_mp3(wav_path: Path, mp3_path: Path, *, bitrate_k: int = 192) -> None:
    tools = require_ffmpeg()
    if not wav_path.is_file():
        raise FFmpegUnavailableError(f"wav input missing: {wav_path}")
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        tools.ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(wav_path),
        "-codec:a",
        "libmp3lame",
        "-b:a",
        f"{bitrate_k}k",
        str(mp3_path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FFmpegUnavailableError("ffmpeg failed to encode MP3") from exc
    if completed.returncode != 0 or not mp3_path.is_file():
        detail = (completed.stderr or completed.stdout or "").strip()
        message = "ffmpeg failed to encode MP3"
        if detail:
            message = f"{message}: {detail}"
        raise FFmpegUnavailableError(message)


def probe_audio(path: Path) -> AudioProbe:
    tools = require_ffmpeg()
    if not path.is_file():
        raise FFmpegUnavailableError(f"audio file missing: {path}")
    duration_s, sample_rate, channels = _probe_format(tools, path)
    peak_amplitude, finite = _probe_pcm_peak(tools, path)
    return AudioProbe(
        duration_s=duration_s,
        peak_amplitude=peak_amplitude,
        finite=finite,
        sample_rate=sample_rate,
        channels=channels,
    )


def _probe_format(tools: FFmpegTools, path: Path) -> tuple[float, int, int]:
    command = [
        tools.ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate,channels:format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FFmpegUnavailableError("ffprobe failed to inspect audio") from exc
    if completed.returncode != 0:
        raise FFmpegUnavailableError("ffprobe failed to inspect audio")
    try:
        payload = json.loads(completed.stdout)
        stream = payload["streams"][0]
        duration_s = float(payload["format"]["duration"])
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FFmpegUnavailableError("ffprobe returned unexpected audio metadata") from exc
    return duration_s, sample_rate, channels


def _probe_pcm_peak(tools: FFmpegTools, path: Path) -> tuple[float, bool]:
    command = [
        tools.ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ac",
        "1",
        "-ar",
        "44100",
        "pipe:1",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FFmpegUnavailableError("ffmpeg failed to decode audio for probing") from exc
    if completed.returncode != 0:
        raise FFmpegUnavailableError("ffmpeg failed to decode audio for probing")
    pcm = completed.stdout
    if len(pcm) < 2:
        return 0.0, True
    peak = 0
    finite = True
    for offset in range(0, len(pcm) - 1, 2):
        sample = struct.unpack_from("<h", pcm, offset)[0]
        if not math.isfinite(float(sample)):
            finite = False
            continue
        absolute = abs(sample)
        if absolute > peak:
            peak = absolute
    return peak / 32767.0, finite


def write_pcm16_wav(
    path: Path,
    samples: list[int],
    *,
    sample_rate: int = 44_100,
    channels: int = 1,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))
