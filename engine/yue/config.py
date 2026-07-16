from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from engine.models import LicenseId

PINNED_UPSTREAM_COMMIT = "9f1394bae1d8d218fea750c1413c2d9d731c7310"


class CheckpointRole(StrEnum):
    STAGE1 = "stage1"
    STAGE1_ICL = "stage1_icl"
    STAGE2 = "stage2"
    CODEC = "codec"


class YueCheckpoint(BaseModel):
    """License and provenance evidence for one required YuE checkpoint component."""

    model_config = ConfigDict(frozen=True)

    role: CheckpointRole
    identity: str | None = None
    location: str | None = None
    sha256: str | None = None
    license: LicenseId | None = None
    provenance_url: str | None = None


class YueConfig(BaseModel):
    """Adapter-local YuE source, checkpoint, and hardware policy."""

    model_config = ConfigDict(frozen=True)

    upstream_root: Path | None = None
    upstream_commit: str | None = None
    checkpoints: tuple[YueCheckpoint, ...] = ()
    cuda_index: int = Field(default=0, ge=0)
    minimum_vram_gb: float = Field(default=24.0, gt=0)
    full_song_vram_gb: float = Field(default=80.0, gt=0)
    default_genre: str = "vocal pop expressive balanced"

    def checkpoint_for(self, role: CheckpointRole) -> YueCheckpoint | None:
        return next((item for item in self.checkpoints if item.role is role), None)
