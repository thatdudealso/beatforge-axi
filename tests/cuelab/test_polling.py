from __future__ import annotations

from pathlib import Path


def test_cuelab_polling_reports_timeout_instead_of_expiring_silently() -> None:
    source = Path("cuelab-axi/src/main.jsx").read_text()

    assert "pollAttempts" in source
    assert 'status: "timeout"' in source
    assert "maxTries" not in source
