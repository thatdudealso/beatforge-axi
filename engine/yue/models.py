from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from engine.models import GenerateRequest, OperationContext, RemixRequest

from .config import YueConfig


@dataclass(frozen=True)
class YueDiagnostic:
    code: str
    message: str


@dataclass(frozen=True)
class YueEnvironment:
    missing_dependencies: tuple[str, ...]
    cuda_available: bool
    device_name: str | None
    vram_gb: float | None


@dataclass(frozen=True)
class YueReadiness:
    ready: bool
    diagnostics: tuple[YueDiagnostic, ...]


@dataclass(frozen=True)
class YueRuntimeResult:
    path: Path
    duration_s: float | None
    metadata: dict[str, object] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


class YueRuntimeError(RuntimeError):
    """A normalized failure reported by the isolated YuE runtime boundary."""


class YueRuntime(Protocol):
    def probe(self, config: YueConfig) -> YueEnvironment: ...

    async def generate(
        self,
        config: YueConfig,
        request: GenerateRequest,
        context: OperationContext,
    ) -> YueRuntimeResult: ...

    async def remix(
        self,
        config: YueConfig,
        request: RemixRequest,
        context: OperationContext,
    ) -> YueRuntimeResult: ...
