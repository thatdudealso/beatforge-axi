from __future__ import annotations

from typing import Protocol

from engine.models import (
    AnalyzeRequest,
    EngineDescriptor,
    GenerateRequest,
    OperationContext,
    OperationResult,
    RemixRequest,
    RepaintRequest,
    StemsRequest,
)


class MusicEngine(Protocol):
    descriptor: EngineDescriptor

    async def generate(
        self, request: GenerateRequest, context: OperationContext
    ) -> OperationResult: ...

    async def repaint(
        self, request: RepaintRequest, context: OperationContext
    ) -> OperationResult: ...

    async def remix(self, request: RemixRequest, context: OperationContext) -> OperationResult: ...

    async def stems(self, request: StemsRequest, context: OperationContext) -> OperationResult: ...

    async def analyze(
        self, request: AnalyzeRequest, context: OperationContext
    ) -> OperationResult: ...
