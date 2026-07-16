from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from engine.base import MusicEngine
from engine.errors import EngineUnavailableError, UnsupportedOperationError
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
from engine.musicgen import (
    GeneratedAudio,
    MusicGenConfig,
    MusicGenEngine,
    ReadinessCode,
    checkpoint_sha256,
)


class StubRuntime:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.generate_calls: list[dict[str, object]] = []

    def availability_diagnostic(self) -> str | None:
        if self.available:
            return None
        return "AudioCraft is not installed; install the pinned optional MusicGen environment"

    def generate(
        self,
        *,
        checkpoint: Path,
        device: str | None,
        prompt: str,
        duration_s: float,
        seed: int | None,
        out: Path,
    ) -> GeneratedAudio:
        self.generate_calls.append(
            {
                "checkpoint": checkpoint,
                "device": device,
                "prompt": prompt,
                "duration_s": duration_s,
                "seed": seed,
                "out": out,
            }
        )
        out.write_bytes(b"generated audio")
        return GeneratedAudio(sample_rate=32_000, channels=1, frames=int(duration_s * 32_000))


class FailingRuntime(StubRuntime):
    def generate(
        self,
        *,
        checkpoint: Path,
        device: str | None,
        prompt: str,
        duration_s: float,
        seed: int | None,
        out: Path,
    ) -> GeneratedAudio:
        raise RuntimeError("native failure details")


def _accepts_music_engine(engine: MusicEngine) -> MusicEngine:
    return engine


def test_unconfigured_adapter_conforms_to_protocol_and_reports_why_not_ready() -> None:
    engine = MusicGenEngine(MusicGenConfig())

    assert _accepts_music_engine(engine) is engine
    assert {
        name
        for name, _ in inspect.getmembers(engine, predicate=inspect.ismethod)
        if name in {"generate", "repaint", "remix", "stems", "analyze"}
    } == {"generate", "repaint", "remix", "stems", "analyze"}
    assert engine.descriptor.name == "musicgen"
    assert engine.descriptor.code_license is LicenseId.MIT
    assert engine.descriptor.ready is False
    assert engine.descriptor.capabilities.supported_operations() == {Operation.GENERATE}
    assert {diagnostic.code for diagnostic in engine.readiness().diagnostics} >= {
        ReadinessCode.CHECKPOINT_REQUIRED,
        ReadinessCode.CHECKPOINT_ID_REQUIRED,
        ReadinessCode.DIGEST_REQUIRED,
        ReadinessCode.LICENSE_REQUIRED,
        ReadinessCode.PROVENANCE_REQUIRED,
        ReadinessCode.PROVENANCE_VERIFICATION_REQUIRED,
    }


def _checkpoint(tmp_path: Path) -> Path:
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "state_dict.bin").write_bytes(b"language model")
    (checkpoint / "compression_state_dict.bin").write_bytes(b"audio tokenizer")
    return checkpoint


def _configured(
    checkpoint: Path,
    *,
    model_license: LicenseId = LicenseId.MIT,
    checkpoint_id: str = "acme/musicgen-permissive-v1",
    digest: str | None = None,
    provenance_url: str | None = "https://models.example/checkpoints/musicgen-v1",
    provenance_verified: bool = True,
) -> MusicGenConfig:
    return MusicGenConfig(
        checkpoint=checkpoint,
        checkpoint_id=checkpoint_id,
        checkpoint_sha256=digest or checkpoint_sha256(checkpoint),
        model_license=model_license,
        provenance_url=provenance_url,
        provenance_verified=provenance_verified,
    )


@pytest.mark.parametrize("model_license", [LicenseId.MIT, LicenseId.APACHE_2_0])
def test_permissive_checkpoint_is_ready_when_dependency_is_available(
    tmp_path: Path, model_license: LicenseId
) -> None:
    checkpoint = _checkpoint(tmp_path)

    engine = MusicGenEngine(
        _configured(checkpoint, model_license=model_license), runtime=StubRuntime()
    )

    assert engine.readiness().ready is True
    assert engine.descriptor.ready is True
    assert engine.descriptor.model_license is model_license


def test_missing_optional_dependency_has_actionable_diagnostic(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path)

    engine = MusicGenEngine(_configured(checkpoint), runtime=StubRuntime(available=False))

    assert engine.descriptor.ready is False
    diagnostic = next(
        item
        for item in engine.readiness().diagnostics
        if item.code is ReadinessCode.DEPENDENCY_MISSING
    )
    assert "AudioCraft is not installed" in diagnostic.message


@pytest.mark.parametrize(
    ("config_override", "expected_code"),
    [
        ({"checkpoint_sha256": None}, ReadinessCode.DIGEST_REQUIRED),
        ({"checkpoint_sha256": "f" * 64}, ReadinessCode.DIGEST_MISMATCH),
        ({"model_license": LicenseId.CC_BY_NC_4_0}, ReadinessCode.LICENSE_NOT_ALLOWED),
        ({"provenance_url": None}, ReadinessCode.PROVENANCE_REQUIRED),
        (
            {"provenance_verified": False},
            ReadinessCode.PROVENANCE_VERIFICATION_REQUIRED,
        ),
        (
            {"checkpoint_id": "facebook/musicgen-small"},
            ReadinessCode.OFFICIAL_CHECKPOINT_FORBIDDEN,
        ),
    ],
)
@pytest.mark.asyncio
async def test_safety_gate_rejects_before_runtime_load(
    tmp_path: Path,
    config_override: dict[str, object],
    expected_code: ReadinessCode,
) -> None:
    checkpoint = _checkpoint(tmp_path)
    config = _configured(checkpoint).model_copy(update=config_override)
    runtime = StubRuntime()
    engine = MusicGenEngine(config, runtime=runtime)

    assert expected_code in {item.code for item in engine.readiness().diagnostics}
    with pytest.raises(EngineUnavailableError, match=expected_code.value):
        await engine.generate(
            request=_generate_request(tmp_path),
            context=_operation_context(tmp_path),
        )
    assert runtime.generate_calls == []


@pytest.mark.asyncio
async def test_generate_writes_artifact_and_returns_provenance_metadata(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path)
    runtime = StubRuntime()
    config = _configured(checkpoint).model_copy(update={"device": "cuda"})
    engine = MusicGenEngine(config, runtime=runtime)
    request = GenerateRequest(
        prompt="warm analog synth",
        duration_s=1.5,
        out=tmp_path / "exports" / "track.wav",
        seed=42,
    )

    result = await engine.generate(request, _operation_context(tmp_path))

    assert request.out.read_bytes() == b"generated audio"
    assert runtime.generate_calls == [
        {
            "checkpoint": checkpoint,
            "device": "cuda",
            "prompt": "warm analog synth",
            "duration_s": 1.5,
            "seed": 42,
            "out": request.out,
        }
    ]
    assert result.operation is Operation.GENERATE
    assert len(result.artifacts) == 1
    assert result.artifacts[0].path == request.out
    assert result.artifacts[0].media_type == "audio/wav"
    assert result.artifacts[0].duration_s == 1.5
    assert result.metadata == {
        "channels": 1,
        "checkpoint_id": "acme/musicgen-permissive-v1",
        "checkpoint_sha256": config.checkpoint_sha256,
        "frames": 48_000,
        "model_license": "MIT",
        "provenance_url": "https://models.example/checkpoints/musicgen-v1",
        "provenance_verified": True,
        "sample_rate": 32_000,
        "seed": 42,
    }
    assert result.warnings == []


@pytest.mark.asyncio
async def test_upstream_generation_error_is_translated(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path)
    engine = MusicGenEngine(_configured(checkpoint), runtime=FailingRuntime())

    with pytest.raises(EngineUnavailableError, match="musicgen generation failed") as raised:
        await engine.generate(_generate_request(tmp_path), _operation_context(tmp_path))

    assert isinstance(raised.value.__cause__, RuntimeError)


@pytest.mark.asyncio
async def test_unsupported_operations_are_stable_and_do_not_load_runtime(
    tmp_path: Path,
) -> None:
    runtime = StubRuntime(available=False)
    engine = MusicGenEngine(MusicGenConfig(), runtime=runtime)
    context = _operation_context(tmp_path)
    with pytest.raises(UnsupportedOperationError, match=r"^musicgen does not support repaint$"):
        await engine.repaint(
            RepaintRequest(
                input_file=tmp_path / "in.wav",
                section=TimeRange(start_s=0, end_s=1),
                prompt="new section",
                out=tmp_path / "out.wav",
            ),
            context,
        )
    with pytest.raises(UnsupportedOperationError, match=r"^musicgen does not support remix$"):
        await engine.remix(
            RemixRequest(
                input_file=tmp_path / "in.wav",
                style="ambient",
                out=tmp_path / "out.wav",
            ),
            context,
        )
    with pytest.raises(UnsupportedOperationError, match=r"^musicgen does not support stems$"):
        await engine.stems(
            StemsRequest(input_file=tmp_path / "in.wav", out_dir=tmp_path / "stems"),
            context,
        )
    with pytest.raises(UnsupportedOperationError, match=r"^musicgen does not support analyze$"):
        await engine.analyze(AnalyzeRequest(file=tmp_path / "in.wav"), context)
    assert runtime.generate_calls == []


def _generate_request(tmp_path: Path) -> GenerateRequest:
    return GenerateRequest(prompt="warm analog synth", duration_s=1.5, out=tmp_path / "out.wav")


def _operation_context(tmp_path: Path) -> OperationContext:
    return OperationContext(job_id="job-1", workspace=tmp_path)
