from __future__ import annotations

import asyncio
from collections.abc import Sequence
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
from engine.yue import (
    PINNED_UPSTREAM_COMMIT,
    CheckpointRole,
    YueCheckpoint,
    YueConfig,
    YueDiagnostic,
    YueEngine,
    YueEnvironment,
    YueRuntimeError,
    YueRuntimeResult,
)


class StubRuntime:
    def __init__(
        self,
        environment: YueEnvironment | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.environment = environment or YueEnvironment(
            missing_dependencies=(),
            cuda_available=True,
            device_name="NVIDIA A100",
            vram_gb=80,
        )
        self.error = error
        self.probe_calls = 0
        self.calls: list[tuple[str, object, OperationContext]] = []

    def probe(self, config: YueConfig) -> YueEnvironment:
        self.probe_calls += 1
        return self.environment

    async def generate(
        self,
        config: YueConfig,
        request: GenerateRequest,
        context: OperationContext,
    ) -> YueRuntimeResult:
        self.calls.append(("generate", request, context))
        if self.error is not None:
            raise self.error
        return YueRuntimeResult(
            path=request.out,
            duration_s=request.duration_s,
            metadata={"mode": "lyrics2song"},
            warnings=("mocked upstream",),
        )

    async def remix(
        self,
        config: YueConfig,
        request: RemixRequest,
        context: OperationContext,
    ) -> YueRuntimeResult:
        self.calls.append(("remix", request, context))
        if self.error is not None:
            raise self.error
        return YueRuntimeResult(
            path=request.out,
            duration_s=None,
            metadata={"mode": "single-track-icl"},
        )


def _checkpoint(role: CheckpointRole) -> YueCheckpoint:
    return YueCheckpoint(
        role=role,
        identity=f"m-a-p/yue-{role.value}@immutable-revision",
        location=f"/models/{role.value}",
        sha256={
            CheckpointRole.STAGE1: "1" * 64,
            CheckpointRole.STAGE1_ICL: "a" * 64,
            CheckpointRole.STAGE2: "2" * 64,
            CheckpointRole.CODEC: "c" * 64,
        }[role],
        license=LicenseId.APACHE_2_0,
        provenance_url=f"https://huggingface.co/m-a-p/yue-{role.value}/tree/immutable-revision",
    )


def configured_yue(tmp_path: Path, **changes: object) -> YueConfig:
    upstream_root = tmp_path / "YuE"
    inference_dir = upstream_root / "inference"
    inference_dir.mkdir(parents=True, exist_ok=True)
    (inference_dir / "infer.py").write_text("# pinned upstream entry point\n")
    values: dict[str, object] = {
        "upstream_root": upstream_root,
        "upstream_commit": PINNED_UPSTREAM_COMMIT,
        "checkpoints": tuple(_checkpoint(role) for role in CheckpointRole),
    }
    values.update(changes)
    return YueConfig.model_validate(values)


def diagnostic_codes(diagnostics: Sequence[YueDiagnostic]) -> set[str]:
    return {diagnostic.code for diagnostic in diagnostics}


def accepts_music_engine(engine: MusicEngine) -> MusicEngine:
    return engine


def test_adapter_conforms_to_music_engine_protocol(tmp_path: Path) -> None:
    engine = YueEngine(configured_yue(tmp_path), runtime=StubRuntime())

    assert accepts_music_engine(engine) is engine
    assert all(callable(getattr(engine, method)) for method in Operation)


def test_unconfigured_adapter_is_importable_and_fails_closed() -> None:
    runtime = StubRuntime()
    engine = YueEngine(YueConfig(), runtime=runtime)

    assert engine.descriptor.name == "yue"
    assert engine.descriptor.ready is False
    assert engine.descriptor.model_license is None
    assert "YUE_CHECKPOINTS_MISSING" in diagnostic_codes(engine.configuration_diagnostics())
    assert runtime.probe_calls == 0


def test_capabilities_match_official_phase_one_workflows(tmp_path: Path) -> None:
    engine = YueEngine(configured_yue(tmp_path), runtime=StubRuntime())

    assert engine.descriptor.capabilities.generate is True
    assert engine.descriptor.capabilities.remix is True
    assert engine.descriptor.capabilities.repaint is False
    assert engine.descriptor.capabilities.stems is False
    assert engine.descriptor.capabilities.analyze is False


def test_checkpoint_roles_separate_cot_and_icl_stage_one_models() -> None:
    assert {role.value for role in CheckpointRole} == {
        "stage1",
        "stage1_icl",
        "stage2",
        "codec",
    }


@pytest.mark.parametrize(
    ("checkpoint", "expected_code"),
    [
        (
            YueCheckpoint(role=CheckpointRole.STAGE1),
            "YUE_CHECKPOINT_IDENTITY_MISSING",
        ),
        (
            YueCheckpoint(
                role=CheckpointRole.STAGE1,
                identity="stage1",
                location="/models/stage1",
                sha256="not-a-digest",
                license=LicenseId.APACHE_2_0,
                provenance_url="https://example.test/stage1",
            ),
            "YUE_CHECKPOINT_DIGEST_INVALID",
        ),
        (
            YueCheckpoint(
                role=CheckpointRole.STAGE1,
                identity="stage1",
                location="/models/stage1",
                sha256="a" * 64,
                license=None,
                provenance_url="https://example.test/stage1",
            ),
            "YUE_CHECKPOINT_LICENSE_MISSING",
        ),
        (
            YueCheckpoint(
                role=CheckpointRole.STAGE1,
                identity="stage1",
                location="/models/stage1",
                sha256="a" * 64,
                license=LicenseId.CC_BY_NC_4_0,
                provenance_url="https://example.test/stage1",
            ),
            "YUE_CHECKPOINT_LICENSE_UNSUPPORTED",
        ),
        (
            YueCheckpoint(
                role=CheckpointRole.STAGE1,
                identity="stage1",
                location="/models/stage1",
                sha256="a" * 64,
                license=LicenseId.APACHE_2_0,
                provenance_url=None,
            ),
            "YUE_CHECKPOINT_PROVENANCE_MISSING",
        ),
    ],
)
def test_checkpoint_gate_rejects_incomplete_or_unapproved_evidence(
    tmp_path: Path,
    checkpoint: YueCheckpoint,
    expected_code: str,
) -> None:
    runtime = StubRuntime()
    other_checkpoints = tuple(
        _checkpoint(role) for role in CheckpointRole if role is not CheckpointRole.STAGE1
    )
    config = configured_yue(tmp_path, checkpoints=(checkpoint, *other_checkpoints))
    engine = YueEngine(config, runtime=runtime)

    assert expected_code in diagnostic_codes(engine.configuration_diagnostics())
    assert engine.descriptor.ready is False
    with pytest.raises(EngineUnavailableError, match=expected_code):
        asyncio.run(
            engine.generate(
                GenerateRequest(prompt="lyrics", duration_s=30, out=tmp_path / "out.mp3"),
                OperationContext(job_id="job", workspace=tmp_path),
            )
        )
    assert runtime.probe_calls == 0


def test_configuration_requires_every_checkpoint_role(tmp_path: Path) -> None:
    config = configured_yue(
        tmp_path,
        checkpoints=(_checkpoint(CheckpointRole.STAGE1), _checkpoint(CheckpointRole.STAGE2)),
    )

    assert "YUE_CHECKPOINT_ROLE_MISSING" in diagnostic_codes(
        YueEngine(config, runtime=StubRuntime()).configuration_diagnostics()
    )


def test_configuration_pins_upstream_source_and_entry_point(tmp_path: Path) -> None:
    wrong_commit = YueEngine(
        configured_yue(tmp_path, upstream_commit="f" * 40), runtime=StubRuntime()
    )
    missing_source = YueEngine(
        configured_yue(tmp_path, upstream_root=tmp_path / "missing"), runtime=StubRuntime()
    )

    assert "YUE_UPSTREAM_COMMIT_UNVERIFIED" in diagnostic_codes(
        wrong_commit.configuration_diagnostics()
    )
    assert "YUE_UPSTREAM_ENTRYPOINT_MISSING" in diagnostic_codes(
        missing_source.configuration_diagnostics()
    )


def test_descriptor_contains_verified_checkpoint_manifest(tmp_path: Path) -> None:
    engine = YueEngine(configured_yue(tmp_path), runtime=StubRuntime())

    descriptor = engine.descriptor
    assert descriptor.ready is True
    assert descriptor.code_license is LicenseId.APACHE_2_0
    assert descriptor.model_license is LicenseId.APACHE_2_0
    assert descriptor.checkpoint is not None
    assert all(role.value in descriptor.checkpoint for role in CheckpointRole)
    assert descriptor.checkpoint_sha256 is not None
    assert len(descriptor.checkpoint_sha256) == 64
    assert descriptor.provenance_url is not None


def test_readiness_reports_missing_optional_dependencies(tmp_path: Path) -> None:
    engine = YueEngine(
        configured_yue(tmp_path),
        runtime=StubRuntime(
            YueEnvironment(
                missing_dependencies=("flash_attn", "torch"),
                cuda_available=False,
                device_name=None,
                vram_gb=None,
            )
        ),
    )

    readiness = engine.readiness()

    assert readiness.ready is False
    assert "YUE_DEPENDENCY_MISSING" in diagnostic_codes(readiness.diagnostics)
    assert "flash_attn" in readiness.diagnostics[0].message


def test_readiness_reports_cuda_requirement_on_unsupported_mac(tmp_path: Path) -> None:
    engine = YueEngine(
        configured_yue(tmp_path),
        runtime=StubRuntime(
            YueEnvironment(
                missing_dependencies=(),
                cuda_available=False,
                device_name="Apple MPS",
                vram_gb=64,
            )
        ),
    )

    readiness = engine.readiness()

    assert readiness.ready is False
    diagnostic = next(item for item in readiness.diagnostics if item.code == "YUE_CUDA_REQUIRED")
    assert "NVIDIA CUDA" in diagnostic.message
    assert "MPS and CPU are not supported" in diagnostic.message


def test_readiness_reports_insufficient_vram(tmp_path: Path) -> None:
    engine = YueEngine(
        configured_yue(tmp_path, minimum_vram_gb=24),
        runtime=StubRuntime(
            YueEnvironment(
                missing_dependencies=(),
                cuda_available=True,
                device_name="NVIDIA GPU",
                vram_gb=16,
            )
        ),
    )

    readiness = engine.readiness()

    assert readiness.ready is False
    diagnostic = next(
        item for item in readiness.diagnostics if item.code == "YUE_VRAM_INSUFFICIENT"
    )
    assert "16.0 GiB detected" in diagnostic.message
    assert "24.0 GiB required" in diagnostic.message


@pytest.mark.parametrize(
    ("method", "operation_request", "operation"),
    [
        (
            "repaint",
            RepaintRequest(
                input_file=Path("input.wav"),
                section=TimeRange(start_s=1, end_s=2),
                prompt="change",
                out=Path("out.wav"),
            ),
            "repaint",
        ),
        ("stems", StemsRequest(input_file=Path("input.wav"), out_dir=Path("stems")), "stems"),
        ("analyze", AnalyzeRequest(file=Path("input.wav")), "analyze"),
    ],
)
def test_unsupported_operations_are_stable_and_do_not_load_runtime(
    tmp_path: Path,
    method: str,
    operation_request: object,
    operation: str,
) -> None:
    runtime = StubRuntime()
    engine = YueEngine(configured_yue(tmp_path), runtime=runtime)
    context = OperationContext(job_id="job", workspace=tmp_path)

    with pytest.raises(
        UnsupportedOperationError,
        match=rf"^yue does not support {operation}$",
    ):
        asyncio.run(getattr(engine, method)(operation_request, context))
    assert runtime.probe_calls == 0
    assert runtime.calls == []


def test_generate_calls_mocked_upstream_and_normalizes_result(tmp_path: Path) -> None:
    runtime = StubRuntime()
    engine = YueEngine(configured_yue(tmp_path), runtime=runtime)
    request = GenerateRequest(
        prompt="[verse]\nSing beneath the stars",
        duration_s=30,
        out=tmp_path / "song.mp3",
        seed=7,
    )
    original = request.model_dump()
    context = OperationContext(job_id="generate-1", workspace=tmp_path)

    result = asyncio.run(engine.generate(request, context))

    assert request.model_dump() == original
    assert runtime.calls == [("generate", request, context)]
    assert result.operation is Operation.GENERATE
    assert result.artifacts[0].path == request.out
    assert result.artifacts[0].media_type == "audio/mpeg"
    assert result.artifacts[0].duration_s == 30
    assert result.metadata["mode"] == "lyrics2song"
    assert result.metadata["engine"] == "yue"
    assert result.warnings == ["mocked upstream"]


def test_remix_calls_mocked_single_track_icl_boundary(tmp_path: Path) -> None:
    runtime = StubRuntime()
    engine = YueEngine(configured_yue(tmp_path), runtime=runtime)
    request = RemixRequest(
        input_file=tmp_path / "reference.wav",
        style="dreamy synth pop",
        out=tmp_path / "remix.mp3",
        seed=9,
    )
    context = OperationContext(job_id="remix-1", workspace=tmp_path)

    result = asyncio.run(engine.remix(request, context))

    assert runtime.calls == [("remix", request, context)]
    assert result.operation is Operation.REMIX
    assert result.artifacts[0].path == request.out
    assert result.metadata["mode"] == "single-track-icl"
    assert result.warnings == [
        "YuE ICL does not support remix strength; requested value 0.65 was ignored."
    ]


@pytest.mark.parametrize(
    ("method", "operation_request"),
    [
        ("generate", GenerateRequest(prompt="lyrics", duration_s=30, out=Path("song.wav"))),
        (
            "remix",
            RemixRequest(input_file=Path("reference.wav"), style="dream pop", out=Path("song.wav")),
        ),
    ],
)
def test_supported_operations_reject_non_mp3_output_before_loading_runtime(
    tmp_path: Path,
    method: str,
    operation_request: object,
) -> None:
    runtime = StubRuntime()
    engine = YueEngine(configured_yue(tmp_path), runtime=runtime)

    with pytest.raises(UnsupportedOperationError, match=r"^yue only supports \.mp3 output$"):
        asyncio.run(
            getattr(engine, method)(
                operation_request, OperationContext(job_id="job", workspace=tmp_path)
            )
        )

    assert runtime.probe_calls == 0
    assert runtime.calls == []


def test_upstream_errors_are_translated_without_losing_stable_code(tmp_path: Path) -> None:
    engine = YueEngine(
        configured_yue(tmp_path),
        runtime=StubRuntime(error=YueRuntimeError("CUDA out of memory")),
    )

    with pytest.raises(
        EngineUnavailableError,
        match=r"^YUE_UPSTREAM_ERROR: YuE inference failed: CUDA out of memory$",
    ):
        asyncio.run(
            engine.generate(
                GenerateRequest(prompt="lyrics", duration_s=30, out=tmp_path / "out.mp3"),
                OperationContext(job_id="job", workspace=tmp_path),
            )
        )
