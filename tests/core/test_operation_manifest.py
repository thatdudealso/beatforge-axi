from __future__ import annotations

from core.manifest import OPERATION_MANIFEST
from engine.models import Operation


def test_every_operation_has_agent_and_human_front_doors() -> None:
    assert set(OPERATION_MANIFEST) == set(Operation)

    for operation, entry in OPERATION_MANIFEST.items():
        assert entry.cli_command == operation.value
        assert entry.api_route == f"/v1/jobs/{operation.value}"
        assert entry.ui_control.strip()
        assert entry.capability == operation


def test_manifest_routes_are_unique() -> None:
    routes = [entry.api_route for entry in OPERATION_MANIFEST.values()]

    assert len(routes) == len(set(routes))
