from __future__ import annotations

from core.server import manifest_payload
from engine.models import Operation


def test_manifest_payload_exposes_every_operation_route() -> None:
    payload = manifest_payload()

    assert payload["name"] == "beatforge-axi"
    assert set(payload["operations"]) == {operation.value for operation in Operation}
    assert payload["operations"]["generate"] == {
        "cli_command": "generate",
        "api_route": "/v1/jobs/generate",
        "ui_control": "Prompt deck",
        "capability": "generate",
    }
    assert payload["engines"]["fake"]["capabilities"] == [
        "analyze",
        "generate",
        "remix",
        "repaint",
        "stems",
    ]
