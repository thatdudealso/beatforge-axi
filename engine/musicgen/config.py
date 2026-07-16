from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from engine.models import LicenseId


class MusicGenConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    checkpoint: Path | None = None
    checkpoint_id: str | None = None
    checkpoint_sha256: str | None = None
    model_license: LicenseId | None = None
    provenance_url: str | None = None
    provenance_verified: bool = False
    device: str | None = None
