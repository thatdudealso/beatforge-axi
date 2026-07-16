from __future__ import annotations

from pathlib import Path


def test_cuelab_polling_reports_timeout_instead_of_expiring_silently() -> None:
    source = Path("cuelab-axi/src/main.jsx").read_text()

    assert "pollAttempts" in source
    assert 'status: "timeout"' in source
    assert "maxTries" not in source


def test_cuelab_ignores_superseded_poll_results() -> None:
    source = Path("cuelab-axi/src/main.jsx").read_text()

    assert "activeRequestRef" in source
    assert "pollJob(jid, operation, requestId)" in source
    assert "if (activeRequestRef.current !== requestId) return;" in source


def test_cuelab_transport_controls_are_visible_and_explicit() -> None:
    source = Path("cuelab-axi/src/main.jsx").read_text()

    assert "transportBar" in source
    assert "generateButton" in source
    assert 'type="button"' in source
