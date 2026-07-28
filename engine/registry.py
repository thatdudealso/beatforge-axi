from __future__ import annotations

from engine.base import MusicEngine
from engine.errors import EngineUnavailableError, UnsupportedOperationError
from engine.models import LicenseId, Operation

ALLOWED_MODEL_LICENSES = {LicenseId.MIT, LicenseId.APACHE_2_0}


class EngineRegistry:
    def __init__(self) -> None:
        self._engines: dict[str, MusicEngine] = {}

    def register(self, engine: MusicEngine) -> None:
        self._engines[engine.descriptor.name] = engine

    def get(self, name: str) -> MusicEngine:
        return self._engines[name]

    def activate(self, name: str) -> MusicEngine:
        engine = self.get(name)
        descriptor = engine.descriptor
        if descriptor.model_license is None:
            raise EngineUnavailableError(
                f"{name} has no configured model license; configure a checkpoint with provenance"
            )
        if descriptor.model_license not in ALLOWED_MODEL_LICENSES:
            raise EngineUnavailableError(
                f"{name} model license must be MIT or Apache-2.0, got {descriptor.model_license}"
            )
        if not descriptor.ready:
            detail = ""
            readiness = getattr(engine, "readiness", None)
            if callable(readiness):
                report = readiness()
                summary = getattr(report, "summary", None)
                if isinstance(summary, str) and summary:
                    detail = f": {summary}"
            raise EngineUnavailableError(f"{name} is configured but not ready{detail}")
        return engine

    def for_operation(self, name: str, operation: Operation) -> MusicEngine:
        engine = self.activate(name)
        if not engine.descriptor.capabilities.supports(operation):
            raise UnsupportedOperationError(f"{name} does not support {operation.value}")
        return engine
