from __future__ import annotations

from engine.models import (
    AnalyzeRequest,
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

    def _result(self, operation: Operation) -> OperationResult:
        self.calls.append(operation.value)
        return OperationResult(operation=operation)

    async def generate(
        self, request: GenerateRequest, context: OperationContext
    ) -> OperationResult:
        return self._result(Operation.GENERATE)

    async def repaint(self, request: RepaintRequest, context: OperationContext) -> OperationResult:
        return self._result(Operation.REPAINT)

    async def remix(self, request: RemixRequest, context: OperationContext) -> OperationResult:
        return self._result(Operation.REMIX)

    async def stems(self, request: StemsRequest, context: OperationContext) -> OperationResult:
        return self._result(Operation.STEMS)

    async def analyze(self, request: AnalyzeRequest, context: OperationContext) -> OperationResult:
        return self._result(Operation.ANALYZE)
