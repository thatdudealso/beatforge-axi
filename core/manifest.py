from __future__ import annotations

from dataclasses import dataclass

from engine.models import Operation


@dataclass(frozen=True, slots=True)
class OperationEntry:
    cli_command: str
    api_route: str
    ui_control: str
    capability: Operation


def _entry(operation: Operation, ui_control: str) -> OperationEntry:
    return OperationEntry(
        cli_command=operation.value,
        api_route=f"/v1/jobs/{operation.value}",
        ui_control=ui_control,
        capability=operation,
    )


OPERATION_MANIFEST = {
    Operation.GENERATE: _entry(Operation.GENERATE, "Prompt deck"),
    Operation.REPAINT: _entry(Operation.REPAINT, "Waveform repaint region"),
    Operation.REMIX: _entry(Operation.REMIX, "Remix style controls"),
    Operation.STEMS: _entry(Operation.STEMS, "Stem mixer"),
    Operation.ANALYZE: _entry(Operation.ANALYZE, "Track analysis panel"),
}
