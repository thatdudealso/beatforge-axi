from __future__ import annotations

from pathlib import Path

from engine.acestep.config import (
    OFFICIAL_CHECKPOINT_IDENTITY,
    OFFICIAL_PROVENANCE_URL,
    OFFICIAL_WEIGHT_DIGESTS,
    PINNED_UPSTREAM_COMMIT,
)
from engine.acestep.env import config_from_environ
from engine.models import LicenseId


def test_config_from_environ_unconfigured_without_project_root() -> None:
    config = config_from_environ({})

    assert config.model_license is None
    assert config.checkpoint is None
    assert config.verified_weights == ()
    assert config.project_root == Path("/__beatforge_acestep_unconfigured__")


def test_config_from_environ_applies_official_defaults(tmp_path: Path) -> None:
    root = tmp_path / "ACE-Step-1.5"
    root.mkdir()
    config = config_from_environ({"BEATFORGE_ACESTEP_PROJECT_ROOT": str(root)})

    assert config.project_root == root
    assert config.checkpoint == OFFICIAL_CHECKPOINT_IDENTITY
    assert config.checkpoint_sha256 == OFFICIAL_WEIGHT_DIGESTS[0].sha256
    assert config.verified_weights == OFFICIAL_WEIGHT_DIGESTS
    assert config.model_license is LicenseId.MIT
    assert config.provenance_url == OFFICIAL_PROVENANCE_URL
    assert config.upstream_commit == PINNED_UPSTREAM_COMMIT
    assert config.device == "auto"
    assert config.use_mlx_dit is True


def test_config_from_environ_cpu_disables_mlx_by_default(tmp_path: Path) -> None:
    root = tmp_path / "ACE-Step-1.5"
    root.mkdir()
    config = config_from_environ(
        {
            "BEATFORGE_ACESTEP_PROJECT_ROOT": str(root),
            "BEATFORGE_ACESTEP_DEVICE": "cpu",
            "BEATFORGE_ACESTEP_OFFLOAD_TO_CPU": "1",
            "BEATFORGE_ACESTEP_OFFLOAD_DIT_TO_CPU": "true",
        }
    )

    assert config.device == "cpu"
    assert config.use_mlx_dit is False
    assert config.offload_to_cpu is True
    assert config.offload_dit_to_cpu is True
