from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Operation(StrEnum):
    GENERATE = "generate"
    REPAINT = "repaint"
    REMIX = "remix"
    STEMS = "stems"
    ANALYZE = "analyze"


class LicenseId(StrEnum):
    MIT = "MIT"
    APACHE_2_0 = "Apache-2.0"
    CC_BY_NC_4_0 = "CC-BY-NC-4.0"


class CapabilitySet(BaseModel):
    generate: bool = False
    repaint: bool = False
    remix: bool = False
    stems: bool = False
    analyze: bool = False

    def supported_operations(self) -> set[Operation]:
        return {operation for operation in Operation if getattr(self, operation.value)}

    def supports(self, operation: Operation) -> bool:
        return operation in self.supported_operations()


class EngineDescriptor(BaseModel):
    name: str
    model: str
    code_license: LicenseId
    model_license: LicenseId | None
    checkpoint: str | None
    checkpoint_sha256: str | None
    provenance_url: str | None
    ready: bool
    capabilities: CapabilitySet


class TimeRange(BaseModel):
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)

    @model_validator(mode="after")
    def end_must_follow_start(self) -> TimeRange:
        if self.end_s <= self.start_s:
            raise ValueError("end_s must be greater than start_s")
        return self


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    duration_s: float = Field(gt=0)
    out: Path
    seed: int | None = None


class RepaintRequest(BaseModel):
    input_file: Path
    section: TimeRange
    prompt: str = Field(min_length=1)
    out: Path
    seed: int | None = None


class RemixRequest(BaseModel):
    input_file: Path
    style: str = Field(min_length=1)
    out: Path
    strength: float = Field(default=0.65, ge=0, le=1)
    seed: int | None = None


class StemsRequest(BaseModel):
    input_file: Path
    out_dir: Path


class AnalyzeRequest(BaseModel):
    file: Path


class Artifact(BaseModel):
    path: Path
    media_type: str
    duration_s: float | None = None


class OperationResult(BaseModel):
    operation: Operation
    artifacts: list[Artifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class OperationContext(BaseModel):
    job_id: str
    workspace: Path
