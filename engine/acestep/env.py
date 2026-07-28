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
from engine.acestep.path import ensure_project_root_on_path
from engine.models import LicenseId

UNCONFIGURED_PROJECT_ROOT = Path("/__beatforge_acestep_unconfigured__")
PROJECT_ROOT_ENV = "BEATFORGE_ACESTEP_PROJECT_ROOT"
DEVICE_ENV = "BEATFORGE_ACESTEP_DEVICE"
USE_MLX_DIT_ENV = "BEATFORGE_ACESTEP_USE_MLX_DIT"
OFFLOAD_TO_CPU_ENV = "BEATFORGE_ACESTEP_OFFLOAD_TO_CPU"
OFFLOAD_DIT_TO_CPU_ENV = "BEATFORGE_ACESTEP_OFFLOAD_DIT_TO_CPU"


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


def _truthy(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    device = _device_from_env(env.get(DEVICE_ENV, "auto").strip() or "auto")
    # MLX DiT is Apple Silicon only; default off unless device is auto/mps.
    default_mlx = device in {"auto", "mps"}
    project_root = Path(root_value).expanduser()
    ensure_project_root_on_path(project_root)
    return AceStepConfig(
        project_root=project_root,
        checkpoint=OFFICIAL_CHECKPOINT_IDENTITY,
        checkpoint_sha256=primary_digest,
        verified_weights=OFFICIAL_WEIGHT_DIGESTS,
        model_license=LicenseId.MIT,
        provenance_url=OFFICIAL_PROVENANCE_URL,
        upstream_commit=PINNED_UPSTREAM_COMMIT,
        device=device,
        use_mlx_dit=_truthy(env.get(USE_MLX_DIT_ENV), default=default_mlx),
        offload_to_cpu=_truthy(env.get(OFFLOAD_TO_CPU_ENV), default=False),
        offload_dit_to_cpu=_truthy(env.get(OFFLOAD_DIT_TO_CPU_ENV), default=False),
    )
