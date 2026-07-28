from __future__ import annotations

import hashlib
import math
import tempfile
from pathlib import Path

from audio.ffmpeg import FFmpegUnavailableError, encode_wav_to_mp3, write_pcm16_wav
from engine.errors import EngineUnavailableError, UnsupportedOperationError
from engine.models import (
    AnalyzeRequest,
    Artifact,
    CapabilitySet,
    EngineDescriptor,
    GenerateRequest,
    LicenseId,
    Operation,
    OperationContext,
    OperationResult,
    RemixRequest,
    RepaintRequest,
    StemsRequest,
)

_SAMPLE_RATE = 44_100


class SynthEngine:
    """Always-ready local tone generator for orchestrator plumbing and CI."""

    def __init__(self) -> None:
        self.descriptor = EngineDescriptor(
            name="synth",
            model="stdlib-drone",
            code_license=LicenseId.MIT,
            model_license=LicenseId.MIT,
            checkpoint="synth://stdlib-drone",
            checkpoint_sha256="0" * 64,
            provenance_url="https://github.com/thatdudealso/beatforge-axi",
            ready=True,
            capabilities=CapabilitySet(generate=True),
        )

    async def generate(
        self, request: GenerateRequest, context: OperationContext
    ) -> OperationResult:
        del context
        seed = request.seed if request.seed is not None else _seed_from_prompt(request.prompt)
        samples = _render_drone(duration_s=request.duration_s, seed=seed)
        request.out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="beatforge-synth-") as stage:
                wav_path = Path(stage) / "tone.wav"
                write_pcm16_wav(wav_path, samples, sample_rate=_SAMPLE_RATE, channels=1)
                encode_wav_to_mp3(wav_path, request.out)
        except FFmpegUnavailableError as exc:
            raise EngineUnavailableError(str(exc)) from exc
        return OperationResult(
            operation=Operation.GENERATE,
            artifacts=[
                Artifact(
                    path=request.out,
                    media_type="audio/mpeg",
                    duration_s=request.duration_s,
                )
            ],
        )

    async def repaint(self, request: RepaintRequest, context: OperationContext) -> OperationResult:
        del request, context
        raise UnsupportedOperationError("synth does not support repaint")

    async def remix(self, request: RemixRequest, context: OperationContext) -> OperationResult:
        del request, context
        raise UnsupportedOperationError("synth does not support remix")

    async def stems(self, request: StemsRequest, context: OperationContext) -> OperationResult:
        del request, context
        raise UnsupportedOperationError("synth does not support stems")

    async def analyze(self, request: AnalyzeRequest, context: OperationContext) -> OperationResult:
        del request, context
        raise UnsupportedOperationError("synth does not support analyze")


def _seed_from_prompt(prompt: str) -> int:
    digest = hashlib.sha256(prompt.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def _render_drone(*, duration_s: float, seed: int) -> list[int]:
    frame_count = max(1, round(duration_s * _SAMPLE_RATE))
    # Map seed into a pleasant low-mid drone band with light harmonic color.
    base_hz = 110.0 + (seed % 97)
    third_hz = base_hz * (5.0 / 4.0)
    fifth_hz = base_hz * (3.0 / 2.0)
    samples: list[int] = []
    for index in range(frame_count):
        t = index / _SAMPLE_RATE
        # Soft attack/release so exports are audible and non-clicky.
        envelope = min(1.0, t * 8.0) * min(1.0, (duration_s - t) * 8.0)
        envelope = max(0.0, min(1.0, envelope))
        value = (
            0.55 * math.sin(2 * math.pi * base_hz * t)
            + 0.28 * math.sin(2 * math.pi * third_hz * t)
            + 0.17 * math.sin(2 * math.pi * fifth_hz * t)
        )
        # Slow amplitude shimmer so the drone is not a pure DC-looking tone.
        value *= 0.85 + 0.15 * math.sin(2 * math.pi * 0.25 * t + (seed % 13))
        sample = int(max(-1.0, min(1.0, value * envelope)) * 12_000)
        samples.append(sample)
    return samples
