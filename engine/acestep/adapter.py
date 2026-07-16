from __future__ import annotations

import asyncio
import importlib.util
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from engine.acestep.config import AceStepConfig
from engine.acestep.readiness import ReadinessReport, inspect_readiness
from engine.acestep.runtime import (
    AceStepRuntime,
    RuntimeBoundary,
    RuntimeGenerateRequest,
    RuntimeGenerateResult,
)
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

_OUTPUT_MEDIA_TYPES = {
    "wav": "audio/wav",
    "flac": "audio/flac",
    "mp3": "audio/mpeg",
    "opus": "audio/opus",
    "aac": "audio/aac",
}


def _optional_dependency_available() -> bool:
    return importlib.util.find_spec("acestep") is not None


class AceStepEngine:
    def __init__(
        self,
        config: AceStepConfig,
        *,
        runtime_factory: Callable[[], RuntimeBoundary] = AceStepRuntime,
        dependency_probe: Callable[[], bool] = _optional_dependency_available,
    ) -> None:
        self._config = config
        self._runtime_factory = runtime_factory
        self._dependency_probe = dependency_probe
        self._runtime: RuntimeBoundary | None = None
        self._runtime_loaded = False
        self._operation_lock = asyncio.Lock()
        report = self.readiness()
        self.descriptor = EngineDescriptor(
            name="acestep",
            model=config.config_path,
            code_license=LicenseId.MIT,
            model_license=config.model_license,
            checkpoint=config.checkpoint,
            checkpoint_sha256=config.checkpoint_sha256,
            provenance_url=config.provenance_url,
            ready=report.ready,
            capabilities=CapabilitySet(generate=True),
        )

    def readiness(self) -> ReadinessReport:
        return inspect_readiness(self._config, dependency_probe=self._dependency_probe)

    async def generate(
        self, request: GenerateRequest, context: OperationContext
    ) -> OperationResult:
        output_format = request.out.suffix.removeprefix(".").lower()
        if output_format not in _OUTPUT_MEDIA_TYPES:
            suffix = request.out.suffix or "<none>"
            raise EngineUnavailableError(f"acestep unsupported output format '{suffix}'")
        async with self._operation_lock:
            return await asyncio.to_thread(
                self._generate_sync, request, output_format, context.workspace
            )

    def _generate_sync(
        self, request: GenerateRequest, output_format: str, workspace: Path
    ) -> OperationResult:
        self._ensure_ready()
        runtime = self._load_runtime()
        request.out.parent.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="acestep-", dir=workspace) as stage:
            native_request = RuntimeGenerateRequest(
                prompt=request.prompt,
                duration_s=request.duration_s,
                output_dir=Path(stage),
                output_format=output_format,
                seed=request.seed,
            )
            try:
                native_result = runtime.generate(native_request)
            except Exception as exc:
                raise EngineUnavailableError(
                    "acestep generation failed; inspect the local ACE-Step logs for details"
                ) from exc
            self._copy_artifact(native_result, request.out)
            metadata = dict(native_result.metadata)
        metadata.update(
            {
                "checkpoint": self._config.checkpoint,
                "upstream_commit": self._config.upstream_commit,
            }
        )
        metadata.setdefault("device", self._config.device)
        return OperationResult(
            operation=Operation.GENERATE,
            artifacts=[
                Artifact(
                    path=request.out,
                    media_type=_OUTPUT_MEDIA_TYPES[output_format],
                    duration_s=native_result.duration_s or request.duration_s,
                )
            ],
            metadata=metadata,
        )

    def _ensure_ready(self) -> None:
        report = self.readiness()
        if not report.ready:
            raise EngineUnavailableError(f"acestep is not ready: {report.summary}")

    def _load_runtime(self) -> RuntimeBoundary:
        if self._runtime is None:
            self._runtime = self._runtime_factory()
        if not self._runtime_loaded:
            try:
                self._runtime.load(self._config)
            except Exception as exc:
                raise EngineUnavailableError(
                    "acestep runtime failed to load; verify the pinned installation and checkpoint"
                ) from exc
            self._runtime_loaded = True
        return self._runtime

    @staticmethod
    def _copy_artifact(result: RuntimeGenerateResult, destination: Path) -> None:
        if not result.path.is_file():
            raise EngineUnavailableError("acestep generation returned a missing audio artifact")
        if result.path.resolve() != destination.resolve():
            shutil.copy2(result.path, destination)

    async def repaint(self, request: RepaintRequest, context: OperationContext) -> OperationResult:
        del request, context
        raise UnsupportedOperationError("acestep does not support repaint")

    async def remix(self, request: RemixRequest, context: OperationContext) -> OperationResult:
        del request, context
        raise UnsupportedOperationError("acestep does not support remix")

    async def stems(self, request: StemsRequest, context: OperationContext) -> OperationResult:
        del request, context
        raise UnsupportedOperationError("acestep does not support stems")

    async def analyze(self, request: AnalyzeRequest, context: OperationContext) -> OperationResult:
        del request, context
        raise UnsupportedOperationError("acestep does not support analyze")
