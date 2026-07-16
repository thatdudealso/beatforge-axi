from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ReadinessCode(StrEnum):
    CHECKPOINT_REQUIRED = "checkpoint_required"
    CHECKPOINT_ID_REQUIRED = "checkpoint_id_required"
    DIGEST_REQUIRED = "digest_required"
    LICENSE_REQUIRED = "license_required"
    PROVENANCE_REQUIRED = "provenance_required"
    PROVENANCE_VERIFICATION_REQUIRED = "provenance_verification_required"
    LICENSE_NOT_ALLOWED = "license_not_allowed"
    OFFICIAL_CHECKPOINT_FORBIDDEN = "official_checkpoint_forbidden"
    CHECKPOINT_NOT_FOUND = "checkpoint_not_found"
    CHECKPOINT_SHAPE_INVALID = "checkpoint_shape_invalid"
    DIGEST_INVALID = "digest_invalid"
    DIGEST_MISMATCH = "digest_mismatch"
    DEPENDENCY_MISSING = "dependency_missing"


@dataclass(frozen=True)
class ReadinessDiagnostic:
    code: ReadinessCode
    message: str


@dataclass(frozen=True)
class ReadinessReport:
    diagnostics: tuple[ReadinessDiagnostic, ...]

    @property
    def ready(self) -> bool:
        return not self.diagnostics
