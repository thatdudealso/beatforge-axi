from __future__ import annotations

from pathlib import Path

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


class FakeEngine:
    def __init__(
        self,
        *,
        name: str = "fake",
        model_license: LicenseId = LicenseId.MIT,
        capabilities: CapabilitySet | None = None,
        descriptor: EngineDescriptor | None = None,
    ) -> None:
        self.descriptor = descriptor or EngineDescriptor(
            name=name,
            model="test",
            code_license=LicenseId.MIT,
            model_license=model_license,
            checkpoint="fake://model",
            checkpoint_sha256="0" * 64,
            provenance_url="https://example.invalid/model",
            ready=True,
            capabilities=capabilities
            or CapabilitySet(
                generate=True,
                repaint=True,
                remix=True,
                stems=True,
                analyze=True,
            ),
        )
        self.calls: list[str] = []

    def _write_fake_audio(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"beatforge fake audio\n")

    def _result(
        self,
        operation: Operation,
        *,
        artifacts: list[Artifact] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> OperationResult:
        self.calls.append(operation.value)
        return OperationResult(
            operation=operation,
            artifacts=artifacts or [],
            metadata=metadata or {},
        )

    async def generate(
        self, request: GenerateRequest, context: OperationContext
    ) -> OperationResult:
        self._write_fake_audio(request.out)
        return self._result(
            Operation.GENERATE,
            artifacts=[
                Artifact(path=request.out, media_type="audio/mpeg", duration_s=request.duration_s)
            ],
        )

    async def repaint(self, request: RepaintRequest, context: OperationContext) -> OperationResult:
        self._write_fake_audio(request.out)
        return self._result(
            Operation.REPAINT,
            artifacts=[Artifact(path=request.out, media_type="audio/mpeg")],
            metadata={
                "section_start_s": request.section.start_s,
                "section_end_s": request.section.end_s,
            },
        )

    async def remix(self, request: RemixRequest, context: OperationContext) -> OperationResult:
        self._write_fake_audio(request.out)
        return self._result(
            Operation.REMIX,
            artifacts=[Artifact(path=request.out, media_type="audio/mpeg")],
            metadata={"style": request.style, "strength": request.strength},
        )

    async def stems(self, request: StemsRequest, context: OperationContext) -> OperationResult:
        request.out_dir.mkdir(parents=True, exist_ok=True)
        artifacts: list[Artifact] = []
        for name in ("drums", "bass", "music", "vocals"):
            path = request.out_dir / f"{name}.mp3"
            self._write_fake_audio(path)
            artifacts.append(Artifact(path=path, media_type="audio/mpeg"))
        return self._result(Operation.STEMS, artifacts=artifacts)

    async def analyze(self, request: AnalyzeRequest, context: OperationContext) -> OperationResult:
        return self._result(Operation.ANALYZE, metadata={"bpm": 90, "key": "C minor"})
