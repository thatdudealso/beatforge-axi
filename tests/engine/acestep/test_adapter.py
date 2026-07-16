from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from engine.acestep import (
    OFFICIAL_CHECKPOINT_IDENTITY,
    OFFICIAL_PROVENANCE_URL,
    OFFICIAL_WEIGHT_DIGESTS,
    PINNED_UPSTREAM_COMMIT,
    REQUIRED_WEIGHT_PATHS,
    AceStepConfig,
    AceStepEngine,
    AceStepRuntime,
    RuntimeGenerateRequest,
    RuntimeGenerateResult,
    VerifiedWeight,
)
from engine.acestep.readiness import checkpoint_sha256 as calculate_checkpoint_sha256
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

if TYPE_CHECKING:
    from engine.acestep import RuntimeBoundary


class FakeRuntime:
    def __init__(self, *, load_error: Exception | None = None) -> None:
        self.load_error = load_error
        self.load_calls: list[AceStepConfig] = []
        self.generate_calls: list[RuntimeGenerateRequest] = []

    def load(self, config: AceStepConfig) -> None:
        self.load_calls.append(config)
        if self.load_error is not None:
            raise self.load_error

    def generate(self, request: RuntimeGenerateRequest) -> RuntimeGenerateResult:
        self.generate_calls.append(request)
        generated = request.output_dir / "upstream.wav"
        generated.write_bytes(b"RIFF-mocked-audio")
        return RuntimeGenerateResult(
            path=generated,
            duration_s=request.duration_s,
            metadata={"device": "mps", "seed": request.seed},
        )


@pytest.fixture(autouse=True)
def _use_published_digests_for_small_test_files(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = {weight.relative_path: weight.sha256 for weight in OFFICIAL_WEIGHT_DIGESTS}

    def published_digest(path: Path) -> str:
        relative_path = Path(*path.parts[-2:])
        return published[relative_path]

    def pinned_commit(_project_root: Path) -> str:
        return PINNED_UPSTREAM_COMMIT

    def clean_checkout(_project_root: Path) -> bool:
        return True

    monkeypatch.setattr("engine.acestep.readiness.checkpoint_sha256", published_digest)
    monkeypatch.setattr(
        "engine.acestep.readiness.upstream_checkout_commit",
        pinned_commit,
    )
    monkeypatch.setattr(
        "engine.acestep.readiness.upstream_checkout_is_clean",
        clean_checkout,
    )


def _configured(tmp_path: Path, **overrides: object) -> AceStepConfig:
    project_root = tmp_path / "upstream"
    for relative_path in REQUIRED_WEIGHT_PATHS:
        checkpoint_file = project_root / "checkpoints" / relative_path
        checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        contents = f"verified:{relative_path.as_posix()}".encode()
        checkpoint_file.write_bytes(contents)
    primary_digest = next(
        weight.sha256
        for weight in OFFICIAL_WEIGHT_DIGESTS
        if weight.relative_path == Path("acestep-v15-turbo/model.safetensors")
    )
    values: dict[str, object] = {
        "project_root": project_root,
        "checkpoint": OFFICIAL_CHECKPOINT_IDENTITY,
        "checkpoint_sha256": primary_digest,
        "verified_weights": OFFICIAL_WEIGHT_DIGESTS,
        "model_license": LicenseId.MIT,
        "provenance_url": OFFICIAL_PROVENANCE_URL,
        "upstream_commit": PINNED_UPSTREAM_COMMIT,
        "device": "mps",
    }
    values.update(overrides)
    return AceStepConfig(**values)  # type: ignore[arg-type]


def _context(tmp_path: Path) -> OperationContext:
    return OperationContext(job_id="job-1", workspace=tmp_path)


def test_checkpoint_hasher_reads_file_contents(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint"
    checkpoint.write_bytes(b"contents")

    assert (
        calculate_checkpoint_sha256(checkpoint)
        == "d1b2a59fbea7e20077af9f91b27e95e865061b270be03ff539ab3b73587882e8"
    )


def test_configuration_builds_verified_ready_descriptor(tmp_path: Path) -> None:
    config = _configured(tmp_path)
    engine = AceStepEngine(config, dependency_probe=lambda: True)

    assert engine.descriptor.ready is True
    assert engine.descriptor.model_license is LicenseId.MIT
    assert engine.descriptor.checkpoint == config.checkpoint
    assert engine.descriptor.checkpoint_sha256 == config.checkpoint_sha256
    assert engine.readiness().issues == ()


def test_readiness_rejects_an_unverifiable_upstream_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_commit(_project_root: Path) -> None:
        return None

    monkeypatch.setattr(
        "engine.acestep.readiness.upstream_checkout_commit",
        no_commit,
    )
    engine = AceStepEngine(_configured(tmp_path), dependency_probe=lambda: True)

    assert "upstream_checkout_unverified" in engine.readiness().issue_codes


def test_readiness_rejects_a_dirty_upstream_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def dirty_checkout(_project_root: Path) -> bool:
        return False

    monkeypatch.setattr(
        "engine.acestep.readiness.upstream_checkout_is_clean",
        dirty_checkout,
    )
    engine = AceStepEngine(_configured(tmp_path), dependency_probe=lambda: True)

    assert "upstream_checkout_dirty" in engine.readiness().issue_codes


def test_adapter_conforms_to_music_engine_protocol(tmp_path: Path) -> None:
    engine: MusicEngine = AceStepEngine(_configured(tmp_path), dependency_probe=lambda: True)

    assert callable(engine.generate)
    assert callable(engine.repaint)
    assert callable(engine.remix)
    assert callable(engine.stems)
    assert callable(engine.analyze)


def test_import_and_configuration_do_not_load_optional_runtime(tmp_path: Path) -> None:
    factory_calls = 0

    def factory() -> RuntimeBoundary:
        nonlocal factory_calls
        factory_calls += 1
        return FakeRuntime()

    AceStepEngine(
        _configured(tmp_path),
        runtime_factory=factory,
        dependency_probe=lambda: True,
    )

    assert factory_calls == 0


@pytest.mark.asyncio
async def test_missing_optional_dependency_is_actionable_and_does_not_call_runtime(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime()
    engine = AceStepEngine(
        _configured(tmp_path),
        runtime_factory=lambda: runtime,
        dependency_probe=lambda: False,
    )

    report = engine.readiness()
    assert report.ready is False
    assert report.issue_codes == {"optional_dependency_missing"}
    with pytest.raises(EngineUnavailableError, match=r"uv sync.*ACE-Step-1\.5"):
        await engine.generate(
            GenerateRequest(prompt="bright synth pulse", duration_s=10, out=tmp_path / "out.wav"),
            _context(tmp_path),
        )
    assert runtime.load_calls == []


@pytest.mark.parametrize(
    "model_license",
    [None, LicenseId.CC_BY_NC_4_0, LicenseId.APACHE_2_0],
)
def test_readiness_rejects_missing_or_nonpermissive_license(
    tmp_path: Path, model_license: LicenseId | None
) -> None:
    engine = AceStepEngine(
        _configured(tmp_path, model_license=model_license),
        dependency_probe=lambda: True,
    )

    assert engine.readiness().ready is False
    assert "model_license_unverified" in engine.readiness().issue_codes


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        ({"checkpoint": None}, "checkpoint_identity_missing"),
        ({"checkpoint_sha256": None}, "checkpoint_digest_missing"),
        ({"checkpoint_sha256": "0" * 64}, "checkpoint_digest_mismatch"),
        ({"provenance_url": None}, "provenance_missing"),
        ({"provenance_url": "http://example.invalid/model"}, "provenance_invalid"),
        (
            {"provenance_url": "https://example.invalid/ACE-Step/Ace-Step1.5"},
            "provenance_unverified",
        ),
        (
            {
                "checkpoint": (
                    "someone-else/Ace-Step1.5@19671f406d603126926c1b7e2adc169acbcade22/"
                    "acestep-v15-turbo/model.safetensors"
                )
            },
            "checkpoint_identity_unverified",
        ),
        ({"config_path": "acestep-v15-sft"}, "model_variant_unverified"),
        ({"upstream_commit": "f" * 40}, "upstream_commit_mismatch"),
    ],
)
def test_readiness_fails_closed_for_unverified_provenance(
    tmp_path: Path, overrides: dict[str, object], expected_code: str
) -> None:
    engine = AceStepEngine(
        _configured(tmp_path, **overrides),
        dependency_probe=lambda: True,
    )

    assert engine.readiness().ready is False
    assert expected_code in engine.readiness().issue_codes


def test_readiness_reports_missing_checkpoint_file(tmp_path: Path) -> None:
    config = _configured(tmp_path)
    config.checkpoint_file.unlink()
    engine = AceStepEngine(config, dependency_probe=lambda: True)

    assert engine.readiness().issue_codes == {"checkpoint_file_missing"}
    assert str(config.checkpoint_file) in engine.readiness().summary


def test_readiness_rejects_self_asserted_unpublished_weight_digest(tmp_path: Path) -> None:
    weights = tuple(
        VerifiedWeight(weight.relative_path, "1" * 64)
        if weight.relative_path == Path("acestep-v15-turbo/model.safetensors")
        else weight
        for weight in OFFICIAL_WEIGHT_DIGESTS
    )
    engine = AceStepEngine(
        _configured(
            tmp_path,
            checkpoint_sha256="1" * 64,
            verified_weights=weights,
        ),
        dependency_probe=lambda: True,
    )

    assert "checkpoint_digest_unverified" in engine.readiness().issue_codes
    assert "weight_digest_unverified" in engine.readiness().issue_codes


def test_capabilities_are_generate_only(tmp_path: Path) -> None:
    engine = AceStepEngine(_configured(tmp_path), dependency_probe=lambda: True)

    assert engine.descriptor.capabilities.supported_operations() == {Operation.GENERATE}


@pytest.mark.asyncio
async def test_unsupported_operations_are_stable_and_never_load_runtime(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    engine = AceStepEngine(
        _configured(tmp_path),
        runtime_factory=lambda: runtime,
        dependency_probe=lambda: True,
    )
    context = _context(tmp_path)
    input_file = tmp_path / "input.wav"
    requests = [
        (
            engine.repaint,
            RepaintRequest(
                input_file=input_file,
                section=TimeRange(start_s=1, end_s=2),
                prompt="new chorus",
                out=tmp_path / "repaint.wav",
            ),
            "repaint",
        ),
        (
            engine.remix,
            RemixRequest(
                input_file=input_file,
                style="ambient",
                out=tmp_path / "remix.wav",
            ),
            "remix",
        ),
        (engine.stems, StemsRequest(input_file=input_file, out_dir=tmp_path / "stems"), "stems"),
        (engine.analyze, AnalyzeRequest(file=input_file), "analyze"),
    ]

    for method, request, operation in requests:
        with pytest.raises(
            UnsupportedOperationError,
            match=rf"^acestep does not support {operation}$",
        ):
            await method(request, context)  # type: ignore[arg-type]

    assert runtime.load_calls == []


@pytest.mark.asyncio
async def test_generation_maps_request_and_copies_mocked_upstream_artifact(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    config = _configured(tmp_path)
    engine = AceStepEngine(
        config,
        runtime_factory=lambda: runtime,
        dependency_probe=lambda: True,
    )
    output = tmp_path / "result.wav"

    result = await engine.generate(
        GenerateRequest(prompt="warm modular arpeggio", duration_s=12, out=output, seed=42),
        _context(tmp_path),
    )

    staged_dir = runtime.generate_calls[0].output_dir
    assert runtime.load_calls == [config]
    assert runtime.generate_calls == [
        RuntimeGenerateRequest(
            prompt="warm modular arpeggio",
            duration_s=12,
            output_dir=staged_dir,
            output_format="wav",
            seed=42,
        )
    ]
    assert staged_dir.parent == tmp_path
    assert staged_dir != tmp_path
    assert not staged_dir.exists()
    assert output.read_bytes() == b"RIFF-mocked-audio"
    assert result.operation is Operation.GENERATE
    assert result.artifacts[0].path == output
    assert result.artifacts[0].media_type == "audio/wav"
    assert result.artifacts[0].duration_s == 12
    assert result.metadata["checkpoint"] == config.checkpoint
    assert result.metadata["device"] == "mps"
    assert result.metadata["seed"] == 42


@pytest.mark.asyncio
async def test_upstream_load_error_is_translated_without_leaking_native_exception(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime(load_error=ValueError("native tensor mismatch"))
    engine = AceStepEngine(
        _configured(tmp_path),
        runtime_factory=lambda: runtime,
        dependency_probe=lambda: True,
    )

    with pytest.raises(
        EngineUnavailableError,
        match=r"^acestep runtime failed to load; verify the pinned installation and checkpoint$",
    ) as raised:
        await engine.generate(
            GenerateRequest(prompt="a pulse", duration_s=10, out=tmp_path / "out.wav"),
            _context(tmp_path),
        )

    assert "native tensor mismatch" not in str(raised.value)


@pytest.mark.asyncio
async def test_generation_rejects_unknown_output_format_before_loading_runtime(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime()
    engine = AceStepEngine(
        _configured(tmp_path),
        runtime_factory=lambda: runtime,
        dependency_probe=lambda: True,
    )

    with pytest.raises(EngineUnavailableError, match=r"unsupported output format '\.ogg'"):
        await engine.generate(
            GenerateRequest(prompt="a pulse", duration_s=10, out=tmp_path / "out.ogg"),
            _context(tmp_path),
        )

    assert runtime.load_calls == []


def test_runtime_reports_native_random_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _configured(tmp_path, device="auto")
    generated = tmp_path / "native.wav"
    captured_params: list[SimpleNamespace] = []

    class Handler:
        device = "mps"

        def initialize_service(self, **_kwargs: object) -> tuple[str, bool]:
            return ("ready", True)

    def params_factory(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(**kwargs)

    def config_factory(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(**kwargs)

    def generate_music(
        _handler: Handler,
        _llm_handler: object,
        _params: SimpleNamespace,
        _config: SimpleNamespace,
        *,
        save_dir: str,
    ) -> SimpleNamespace:
        del save_dir
        captured_params.append(_params)
        generated.write_bytes(b"RIFF-native-audio")
        return SimpleNamespace(
            success=True,
            error=None,
            audios=[{"path": str(generated), "params": {"seed": 8675309}}],
        )

    handler_module = SimpleNamespace(
        __file__=str(config.project_root / "acestep" / "handler.py"),
        AceStepHandler=Handler,
    )
    inference_module = SimpleNamespace(
        __file__=str(config.project_root / "acestep" / "inference.py"),
        GenerationParams=params_factory,
        GenerationConfig=config_factory,
        generate_music=generate_music,
    )

    def import_module(name: str) -> object:
        return {
            "acestep.handler": handler_module,
            "acestep.inference": inference_module,
        }[name]

    monkeypatch.setattr("engine.acestep.runtime.importlib.import_module", import_module)
    runtime = AceStepRuntime()

    runtime.load(config)
    result = runtime.generate(
        RuntimeGenerateRequest(
            prompt="random pulse",
            duration_s=10,
            output_dir=tmp_path,
            output_format="wav",
            seed=None,
        )
    )

    assert result.metadata["seed"] == 8675309
    assert result.metadata["device"] == "mps"
    assert captured_params[0].shift == 3.0
