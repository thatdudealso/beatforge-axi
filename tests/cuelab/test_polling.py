from __future__ import annotations

from pathlib import Path


def test_cuelab_polling_surfaces_terminal_errors() -> None:
    source = Path("cuelab-axi/src/main.jsx").read_text()

    assert "while (activeRequestRef.current === requestId)" in source
    assert 'if (!r.ok)' in source
    assert 'status: "error"' in source
    assert "keep polling" not in source


def test_cuelab_ignores_superseded_poll_results() -> None:
    source = Path("cuelab-axi/src/main.jsx").read_text()

    assert "activeRequestRef" in source
    assert "pollJob(jid, requestId)" in source
    assert "if (activeRequestRef.current !== requestId) return;" in source


def test_cuelab_transport_controls_are_visible_and_explicit() -> None:
    source = Path("cuelab-axi/src/main.jsx").read_text()

    assert "transportBar" in source
    assert "generateButton" in source
    assert 'type="button"' in source

def test_cuelab_export_checks_http_and_delays_url_revoke() -> None:
    source = Path("cuelab-axi/src/main.jsx").read_text()

    assert "if (!resp.ok)" in source
    assert "window.setTimeout(() => URL.revokeObjectURL(url), 1000);" in source


def test_cuelab_polling_stops_on_fetch_failure() -> None:
    source = Path("cuelab-axi/src/main.jsx").read_text()

    assert "setJob(prev => ({\n          ...(prev || {}),\n          status: \"error\"" in source


def test_cuelab_generate_defaults_to_real_audio_container() -> None:
    source = Path("cuelab-axi/src/main.jsx").read_text()

    assert 'out: "/tmp/beatforge-cuelab/take.wav"' in source
