from __future__ import annotations

import hashlib
import math
import string
from pathlib import Path

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

from .config import PINNED_UPSTREAM_COMMIT, CheckpointRole, YueCheckpoint, YueConfig
from .models import (
    YueDiagnostic,
    YueEnvironment,
    YueReadiness,
    YueRuntime,
    YueRuntimeError,
    YueRuntimeResult,
)
from .runtime import YueSubprocessRuntime

ALLOWED_LICENSES = {LicenseId.MIT, LicenseId.APACHE_2_0}
CAPABILITIES = CapabilitySet(generate=True, remix=True)


class YueEngine:
    def __init__(
        self,
        config: YueConfig | None = None,
        *,
        runtime: YueRuntime | None = None,
    ) -> None:
        self.config = config or YueConfig()
        self._runtime = runtime or YueSubprocessRuntime()
        self.descriptor = self._descriptor()

    def configuration_diagnostics(self) -> tuple[YueDiagnostic, ...]:
        diagnostics: list[YueDiagnostic] = []
        root = self.config.upstream_root
        if root is None:
            diagnostics.append(
                YueDiagnostic(
                    "YUE_UPSTREAM_ROOT_MISSING",
                    "Configure upstream_root with the pinned YuE source checkout.",
                )
            )
        elif not (root / "inference" / "infer.py").is_file():
            diagnostics.append(
                YueDiagnostic(
                    "YUE_UPSTREAM_ENTRYPOINT_MISSING",
                    "Pinned YuE inference entry point is missing: "
                    f"{root / 'inference' / 'infer.py'}.",
                )
            )
        if self.config.upstream_commit != PINNED_UPSTREAM_COMMIT:
            diagnostics.append(
                YueDiagnostic(
                    "YUE_UPSTREAM_COMMIT_UNVERIFIED",
                    "Use the audited YuE commit "
                    f"{PINNED_UPSTREAM_COMMIT}; configured "
                    f"{self.config.upstream_commit or 'none'}.",
                )
            )

        if not self.config.checkpoints:
            diagnostics.append(
                YueDiagnostic(
                    "YUE_CHECKPOINTS_MISSING",
                    "Configure stage1 CoT, stage1 ICL, stage2, and codec checkpoint evidence "
                    "before activation.",
                )
            )
            return tuple(diagnostics)

        roles = [checkpoint.role for checkpoint in self.config.checkpoints]
        for role in CheckpointRole:
            if role not in roles:
                diagnostics.append(
                    YueDiagnostic(
                        "YUE_CHECKPOINT_ROLE_MISSING",
                        f"Configure verified {role.value} checkpoint evidence.",
                    )
                )
            elif roles.count(role) > 1:
                diagnostics.append(
                    YueDiagnostic(
                        "YUE_CHECKPOINT_ROLE_DUPLICATE",
                        f"Configure exactly one {role.value} checkpoint.",
                    )
                )

        for checkpoint in self.config.checkpoints:
            diagnostics.extend(self._checkpoint_diagnostics(checkpoint))

        licenses = {item.license for item in self.config.checkpoints if item.license is not None}
        if len(licenses) > 1 and licenses <= ALLOWED_LICENSES:
            diagnostics.append(
                YueDiagnostic(
                    "YUE_CHECKPOINT_LICENSE_MIXED",
                    "All checkpoint components must use one consistently verified model license.",
                )
            )
        return tuple(diagnostics)

    @staticmethod
    def _checkpoint_diagnostics(checkpoint: YueCheckpoint) -> list[YueDiagnostic]:
        prefix = f"{checkpoint.role.value} checkpoint"
        diagnostics: list[YueDiagnostic] = []
        if not checkpoint.identity:
            diagnostics.append(
                YueDiagnostic(
                    "YUE_CHECKPOINT_IDENTITY_MISSING",
                    f"{prefix} requires an immutable identity.",
                )
            )
        if not checkpoint.location:
            diagnostics.append(
                YueDiagnostic(
                    "YUE_CHECKPOINT_LOCATION_MISSING",
                    f"{prefix} requires a local path or immutable model location.",
                )
            )
        digest = checkpoint.sha256
        if (
            digest is None
            or len(digest) != 64
            or any(char not in string.hexdigits for char in digest)
        ):
            diagnostics.append(
                YueDiagnostic(
                    "YUE_CHECKPOINT_DIGEST_INVALID",
                    f"{prefix} requires a verified 64-character SHA-256 digest.",
                )
            )
        if checkpoint.license is None:
            diagnostics.append(
                YueDiagnostic(
                    "YUE_CHECKPOINT_LICENSE_MISSING",
                    f"{prefix} requires explicit license evidence; filenames are not evidence.",
                )
            )
        elif checkpoint.license not in ALLOWED_LICENSES:
            diagnostics.append(
                YueDiagnostic(
                    "YUE_CHECKPOINT_LICENSE_UNSUPPORTED",
                    f"{prefix} must be verified MIT or Apache-2.0, got {checkpoint.license}.",
                )
            )
        provenance = checkpoint.provenance_url
        if not provenance:
            diagnostics.append(
                YueDiagnostic(
                    "YUE_CHECKPOINT_PROVENANCE_MISSING",
                    f"{prefix} requires an authoritative provenance URL.",
                )
            )
        elif not provenance.startswith("https://"):
            diagnostics.append(
                YueDiagnostic(
                    "YUE_CHECKPOINT_PROVENANCE_INVALID",
                    f"{prefix} provenance must use an HTTPS authoritative URL.",
                )
            )
        return diagnostics

    def readiness(self, *, required_vram_gb: float | None = None) -> YueReadiness:
        diagnostics = list(self.configuration_diagnostics())
        if diagnostics:
            return YueReadiness(ready=False, diagnostics=tuple(diagnostics))
        environment = self._runtime.probe(self.config)
        diagnostics.extend(
            self._environment_diagnostics(
                environment,
                required_vram_gb=required_vram_gb or self.config.minimum_vram_gb,
            )
        )
        return YueReadiness(ready=not diagnostics, diagnostics=tuple(diagnostics))

    @staticmethod
    def _environment_diagnostics(
        environment: YueEnvironment,
        *,
        required_vram_gb: float,
    ) -> list[YueDiagnostic]:
        diagnostics: list[YueDiagnostic] = []
        if environment.missing_dependencies:
            joined = ", ".join(sorted(environment.missing_dependencies))
            diagnostics.append(
                YueDiagnostic(
                    "YUE_DEPENDENCY_MISSING",
                    f"Install YuE optional dependencies in the project uv environment: {joined}.",
                )
            )
        if not environment.cuda_available:
            diagnostics.append(
                YueDiagnostic(
                    "YUE_CUDA_REQUIRED",
                    "YuE Phase 1 requires an NVIDIA CUDA device; MPS and CPU are not supported. "
                    "Contract and installation checks can run here, but inference requires "
                    "NVIDIA hardware.",
                )
            )
        elif environment.vram_gb is None:
            diagnostics.append(
                YueDiagnostic(
                    "YUE_VRAM_UNKNOWN",
                    "Could not verify CUDA VRAM; inference remains disabled until memory is "
                    "measurable.",
                )
            )
        elif environment.vram_gb < required_vram_gb:
            diagnostics.append(
                YueDiagnostic(
                    "YUE_VRAM_INSUFFICIENT",
                    f"{environment.vram_gb:.1f} GiB detected on "
                    f"{environment.device_name or 'CUDA device'}; "
                    f"{required_vram_gb:.1f} GiB required "
                    "by this adapter profile.",
                )
            )
        return diagnostics

    async def generate(
        self,
        request: GenerateRequest,
        context: OperationContext,
    ) -> OperationResult:
        self._ensure_mp3_output(request.out)
        segments = max(1, math.ceil(request.duration_s / 30))
        required_vram = (
            self.config.full_song_vram_gb if segments >= 4 else self.config.minimum_vram_gb
        )
        self._ensure_ready(required_vram_gb=required_vram)
        try:
            result = await self._runtime.generate(self.config, request, context)
        except YueRuntimeError as error:
            raise EngineUnavailableError(
                f"YUE_UPSTREAM_ERROR: YuE inference failed: {error}"
            ) from error
        return self._operation_result(Operation.GENERATE, result)

    async def remix(
        self,
        request: RemixRequest,
        context: OperationContext,
    ) -> OperationResult:
        self._ensure_mp3_output(request.out)
        self._ensure_ready(required_vram_gb=self.config.minimum_vram_gb)
        try:
            result = await self._runtime.remix(self.config, request, context)
        except YueRuntimeError as error:
            raise EngineUnavailableError(
                f"YUE_UPSTREAM_ERROR: YuE inference failed: {error}"
            ) from error
        return self._operation_result(
            Operation.REMIX,
            result,
            extra_warnings=(
                "YuE ICL does not support remix strength; requested value "
                f"{request.strength} was ignored.",
            ),
        )

    async def repaint(
        self,
        request: RepaintRequest,
        context: OperationContext,
    ) -> OperationResult:
        raise UnsupportedOperationError("yue does not support repaint")

    async def stems(
        self,
        request: StemsRequest,
        context: OperationContext,
    ) -> OperationResult:
        raise UnsupportedOperationError("yue does not support stems")

    async def analyze(
        self,
        request: AnalyzeRequest,
        context: OperationContext,
    ) -> OperationResult:
        raise UnsupportedOperationError("yue does not support analyze")

    def _ensure_ready(self, *, required_vram_gb: float) -> None:
        readiness = self.readiness(required_vram_gb=required_vram_gb)
        if not readiness.ready:
            diagnostic = readiness.diagnostics[0]
            raise EngineUnavailableError(f"{diagnostic.code}: {diagnostic.message}")

    @staticmethod
    def _ensure_mp3_output(path: Path) -> None:
        if path.suffix.lower() != ".mp3":
            raise UnsupportedOperationError("yue only supports .mp3 output")

    def _descriptor(self) -> EngineDescriptor:
        diagnostics = self.configuration_diagnostics()
        complete = not diagnostics
        licenses = {item.license for item in self.config.checkpoints if item.license is not None}
        model_license = next(iter(licenses)) if complete and len(licenses) == 1 else None
        checkpoint = self._checkpoint_identity() if complete else None
        digest = self._checkpoint_manifest_digest() if complete else None
        provenance = self.config.checkpoints[0].provenance_url if complete else None
        return EngineDescriptor(
            name="yue",
            model=f"YuE@{PINNED_UPSTREAM_COMMIT}",
            code_license=LicenseId.APACHE_2_0,
            model_license=model_license,
            checkpoint=checkpoint,
            checkpoint_sha256=digest,
            provenance_url=provenance,
            ready=complete,
            capabilities=CAPABILITIES,
        )

    def _checkpoint_identity(self) -> str:
        ordered = sorted(self.config.checkpoints, key=lambda item: item.role.value)
        return ";".join(f"{item.role.value}={item.identity}" for item in ordered)

    def _checkpoint_manifest_digest(self) -> str:
        ordered = sorted(self.config.checkpoints, key=lambda item: item.role.value)
        manifest = "\n".join(
            f"{item.role.value}\0{item.identity}\0{item.sha256}\0{item.provenance_url}"
            for item in ordered
        )
        return hashlib.sha256(manifest.encode()).hexdigest()

    @staticmethod
    def _operation_result(
        operation: Operation,
        result: YueRuntimeResult,
        *,
        extra_warnings: tuple[str, ...] = (),
    ) -> OperationResult:
        metadata = dict(result.metadata)
        metadata["engine"] = "yue"
        return OperationResult(
            operation=operation,
            artifacts=[
                Artifact(
                    path=result.path,
                    media_type=YueEngine._media_type(result.path),
                    duration_s=result.duration_s,
                )
            ],
            metadata=metadata,
            warnings=[*result.warnings, *extra_warnings],
        )

    @staticmethod
    def _media_type(path: Path) -> str:
        return {
            ".mp3": "audio/mpeg",
        }.get(path.suffix.lower(), "application/octet-stream")
