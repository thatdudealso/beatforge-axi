from __future__ import annotations

import importlib.util
from pathlib import Path

from pytest import MonkeyPatch

from engine.yue import PINNED_UPSTREAM_COMMIT, CheckpointRole, YueCheckpoint, YueConfig
from engine.yue.runtime import YueSubprocessRuntime


def test_dependency_probe_does_not_import_absent_optional_packages(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    looked_up: list[str] = []

    def missing(name: str) -> None:
        looked_up.append(name)
        return None

    monkeypatch.setattr(importlib.util, "find_spec", missing)
    runtime = YueSubprocessRuntime()
    config = YueConfig(
        upstream_root=tmp_path,
        upstream_commit=PINNED_UPSTREAM_COMMIT,
        checkpoints=tuple(
            YueCheckpoint(
                role=role,
                identity=role.value,
                location=str(tmp_path / role.value),
                sha256="a" * 64,
                provenance_url="https://example.test/checkpoint",
            )
            for role in CheckpointRole
        ),
    )

    environment = runtime.probe(config)

    assert set(environment.missing_dependencies) >= {"torch", "transformers", "flash_attn"}
    assert set(looked_up) >= {"torch", "transformers", "flash_attn"}
    assert environment.cuda_available is False
