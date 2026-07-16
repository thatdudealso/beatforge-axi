from __future__ import annotations

from pathlib import Path


def test_cuelab_polling_keeps_waiting_for_terminal_state() -> None:
    source = Path("cuelab-axi/src/main.jsx").read_text()

    assert "while (activeRequestRef.current === requestId)" in source
    assert "pollAttempts" not in source
    assert 'status: "timeout"' not in source
    assert "job_poll_timeout" not in source


def test_cuelab_ignores_superseded_poll_results() -> None:
    source = Path("cuelab-axi/src/main.jsx").read_text()

    assert "activeRequestRef" in source
    assert "pollJob(jid, requestId)" in source
    assert "if (activeRequestRef.current !== requestId) return;" in source


def test_cuelab_export_checks_http_and_delays_url_revoke() -> None:
    source = Path("cuelab-axi/src/main.jsx").read_text()

    assert "if (!resp.ok)" in source
    assert "window.setTimeout(() => URL.revokeObjectURL(url), 1000);" in source


def test_cuelab_generate_defaults_to_real_audio_container() -> None:
    source = Path("cuelab-axi/src/main.jsx").read_text()

    assert 'out: "/tmp/beatforge-cuelab/take.wav"' in source
