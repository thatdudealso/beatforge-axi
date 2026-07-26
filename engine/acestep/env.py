from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from engine.acestep.config import (
    OFFICIAL_CHECKPOINT_IDENTITY,
    OFFICIAL_PROVENANCE_URL,
    OFFICIAL_WEIGHT_DIGESTS,
    PINNED_UPSTREAM_COMMIT,
    PRIMARY_WEIGHT_PATH,
    AceStepConfig,
    Device,
)
from engine.models import LicenseId

UNCONFIGURED_PROJECT_ROOT = Path("/__beatforge_acestep_unconfigured__")
PROJECT_ROOT_ENV = "BEATFORGE_ACESTEP_PROJECT_ROOT"


def _device_from_env(value: str) -> Device:
    if value == "cpu":
        return "cpu"
    if value == "cuda":
        return "cuda"
    if value == "mps":
        return "mps"
    if value == "xpu":
        return "xpu"
    return "auto"


def config_from_environ(environ: Mapping[str, str] | None = None) -> AceStepConfig:
    """Build AceStepConfig from process env, failing closed when unset."""
    env = os.environ if environ is None else environ
    root_value = env.get(PROJECT_ROOT_ENV, "").strip()
    if not root_value:
        return AceStepConfig(project_root=UNCONFIGURED_PROJECT_ROOT)

    primary_digest = next(
        weight.sha256
        for weight in OFFICIAL_WEIGHT_DIGESTS
        if weight.relative_path == PRIMARY_WEIGHT_PATH
    )
    return AceStepConfig(
        project_root=Path(root_value).expanduser(),
        checkpoint=OFFICIAL_CHECKPOINT_IDENTITY,
        checkpoint_sha256=primary_digest,
        verified_weights=OFFICIAL_WEIGHT_DIGESTS,
        model_license=LicenseId.MIT,
        provenance_url=OFFICIAL_PROVENANCE_URL,
        upstream_commit=PINNED_UPSTREAM_COMMIT,
        device=_device_from_env(env.get("BEATFORGE_ACESTEP_DEVICE", "auto").strip() or "auto"),
    )
