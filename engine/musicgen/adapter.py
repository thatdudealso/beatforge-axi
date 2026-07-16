from __future__ import annotations

import re
from asyncio import to_thread

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
from engine.musicgen.checkpoint import checkpoint_sha256
from engine.musicgen.config import MusicGenConfig
from engine.musicgen.diagnostics import (
    ReadinessCode,
    ReadinessDiagnostic,
    ReadinessReport,
)
from engine.musicgen.runtime import AudioCraftRuntime, MusicGenRuntime

_ALLOWED_LICENSES = {LicenseId.MIT, LicenseId.APACHE_2_0}
_CHECKPOINT_FILES = {"state_dict.bin", "compression_state_dict.bin"}
_SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")
_MEDIA_TYPES = {
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
}


def _is_official_meta_checkpoint(checkpoint_id: str) -> bool:
    normalized = checkpoint_id.strip().casefold()
    return normalized in {"small", "medium", "large", "melody", "style"} or normalized.startswith(
        "facebook/musicgen"
    )


class MusicGenEngine:
    def __init__(self, config: MusicGenConfig, *, runtime: MusicGenRuntime | None = None) -> None:
        self.config = config
        self._runtime = runtime or AudioCraftRuntime()
        report = self.readiness()
        self.descriptor = EngineDescriptor(
            name="musicgen",
            model=config.checkpoint_id or "unconfigured",
            code_license=LicenseId.MIT,
            model_license=config.model_license,
            checkpoint=str(config.checkpoint) if config.checkpoint is not None else None,
            checkpoint_sha256=config.checkpoint_sha256,
            provenance_url=config.provenance_url,
            ready=report.ready,
            capabilities=CapabilitySet(generate=True),
        )

    def readiness(self) -> ReadinessReport:
        diagnostics: list[ReadinessDiagnostic] = []
        required = (
            (self.config.checkpoint, ReadinessCode.CHECKPOINT_REQUIRED, "checkpoint is required"),
            (
                self.config.checkpoint_id,
                ReadinessCode.CHECKPOINT_ID_REQUIRED,
                "checkpoint identity is required",
            ),
            (
                self.config.checkpoint_sha256,
                ReadinessCode.DIGEST_REQUIRED,
                "checkpoint SHA-256 digest is required",
            ),
            (
                self.config.model_license,
                ReadinessCode.LICENSE_REQUIRED,
                "model license is required",
            ),
            (
                self.config.provenance_url,
                ReadinessCode.PROVENANCE_REQUIRED,
                "checkpoint provenance URL is required",
            ),
        )
        diagnostics.extend(
            ReadinessDiagnostic(code, message)
            for value, code, message in required
            if value is None or value == ""
        )
        if not self.config.provenance_verified:
            diagnostics.append(
                ReadinessDiagnostic(
                    ReadinessCode.PROVENANCE_VERIFICATION_REQUIRED,
                    "checkpoint provenance must be independently verified",
                )
            )

        if (
            self.config.model_license is not None
            and self.config.model_license not in _ALLOWED_LICENSES
        ):
            diagnostics.append(
                ReadinessDiagnostic(
                    ReadinessCode.LICENSE_NOT_ALLOWED,
                    "model license must be MIT or Apache-2.0",
                )
            )

        if self.config.checkpoint_id and _is_official_meta_checkpoint(self.config.checkpoint_id):
            diagnostics.append(
                ReadinessDiagnostic(
                    ReadinessCode.OFFICIAL_CHECKPOINT_FORBIDDEN,
                    "Meta's official MusicGen checkpoints are CC-BY-NC-4.0 and cannot be activated",
                )
            )

        checkpoint = self.config.checkpoint
        if checkpoint is not None:
            if not checkpoint.exists():
                diagnostics.append(
                    ReadinessDiagnostic(
                        ReadinessCode.CHECKPOINT_NOT_FOUND,
                        f"local checkpoint does not exist: {checkpoint}",
                    )
                )
            elif not checkpoint.is_dir() or not all(
                (checkpoint / filename).is_file() for filename in _CHECKPOINT_FILES
            ):
                diagnostics.append(
                    ReadinessDiagnostic(
                        ReadinessCode.CHECKPOINT_SHAPE_INVALID,
                        "checkpoint must be a local directory containing state_dict.bin and "
                        "compression_state_dict.bin",
                    )
                )
            elif self.config.checkpoint_sha256:
                if _SHA256_PATTERN.fullmatch(self.config.checkpoint_sha256) is None:
                    diagnostics.append(
                        ReadinessDiagnostic(
                            ReadinessCode.DIGEST_INVALID,
                            "checkpoint SHA-256 must be exactly 64 hexadecimal characters",
                        )
                    )
                elif checkpoint_sha256(checkpoint) != self.config.checkpoint_sha256.casefold():
                    diagnostics.append(
                        ReadinessDiagnostic(
                            ReadinessCode.DIGEST_MISMATCH,
                            "checkpoint contents do not match the configured SHA-256 digest",
                        )
                    )

        dependency_diagnostic = self._runtime.availability_diagnostic()
        if dependency_diagnostic is not None:
            diagnostics.append(
                ReadinessDiagnostic(ReadinessCode.DEPENDENCY_MISSING, dependency_diagnostic)
            )
        return ReadinessReport(tuple(diagnostics))

    def _require_ready(self) -> None:
        report = self.readiness()
        if report.ready:
            return
        diagnostic = report.diagnostics[0]
        raise EngineUnavailableError(
            f"musicgen unavailable [{diagnostic.code.value}]: {diagnostic.message}"
        )

    async def generate(
        self, request: GenerateRequest, context: OperationContext
    ) -> OperationResult:
        self._require_ready()
        checkpoint = self.config.checkpoint
        if checkpoint is None:
            raise EngineUnavailableError("musicgen unavailable [checkpoint_required]")
        media_type = _MEDIA_TYPES.get(request.out.suffix.casefold())
        if media_type is None:
            raise EngineUnavailableError(
                "musicgen generation output must use .wav, .flac, .mp3, or .ogg"
            )
        request.out.parent.mkdir(parents=True, exist_ok=True)
        try:
            generated = await to_thread(
                self._runtime.generate,
                checkpoint=checkpoint,
                device=self.config.device,
                prompt=request.prompt,
                duration_s=request.duration_s,
                seed=request.seed,
                out=request.out,
            )
        except Exception as error:
            raise EngineUnavailableError("musicgen generation failed") from error

        return OperationResult(
            operation=Operation.GENERATE,
            artifacts=[
                Artifact(
                    path=request.out,
                    media_type=media_type,
                    duration_s=request.duration_s,
                )
            ],
            metadata={
                "channels": generated.channels,
                "checkpoint_id": self.config.checkpoint_id,
                "checkpoint_sha256": self.config.checkpoint_sha256,
                "frames": generated.frames,
                "model_license": self.config.model_license.value
                if self.config.model_license is not None
                else None,
                "provenance_url": self.config.provenance_url,
                "provenance_verified": self.config.provenance_verified,
                "sample_rate": generated.sample_rate,
                "seed": request.seed,
            },
        )

    @staticmethod
    def _unsupported(operation: Operation) -> UnsupportedOperationError:
        return UnsupportedOperationError(f"musicgen does not support {operation.value}")

    async def repaint(self, request: RepaintRequest, context: OperationContext) -> OperationResult:
        raise self._unsupported(Operation.REPAINT)

    async def remix(self, request: RemixRequest, context: OperationContext) -> OperationResult:
        raise self._unsupported(Operation.REMIX)

    async def stems(self, request: StemsRequest, context: OperationContext) -> OperationResult:
        raise self._unsupported(Operation.STEMS)

    async def analyze(self, request: AnalyzeRequest, context: OperationContext) -> OperationResult:
        raise self._unsupported(Operation.ANALYZE)
