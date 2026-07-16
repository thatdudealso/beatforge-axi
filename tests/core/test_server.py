from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import core.server as server_module
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
    assert payload["engines"]["synth"]["capabilities"] == [
        "generate",
    ]


def test_generate_job_runs_and_confines_absolute_client_output_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "server-workspace"
    client_output = tmp_path / "client-controlled.wav"
    monkeypatch.setattr(server_module, "_WORKSPACE", workspace)
    monkeypatch.setattr(server_module, "_JOBS", {})
    monkeypatch.setattr(server_module, "_ARTIFACTS", {})

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_module.BeatForgeHandler)
    host = "127.0.0.1"
    port = httpd.server_port
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://{host}:{port}"
    try:
        payload = json.dumps(
            {
                "engine": "synth",
                "prompt": "warm lofi",
                "duration_s": 0.1,
                "out": str(client_output),
                "seed": 7,
            }
        ).encode()
        request = urllib.request.Request(
            f"{base_url}/v1/jobs/generate",
            data=payload,
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == HTTPStatus.ACCEPTED
            accepted = json.loads(response.read())

        job_url = f"{base_url}/v1/jobs/{accepted['job_id']}"
        for _ in range(40):
            with urllib.request.urlopen(job_url, timeout=5) as response:
                job = json.loads(response.read())
            if job["status"] in {"done", "error"}:
                break
            time.sleep(0.05)
        else:
            pytest.fail("job did not finish")

        assert job["status"] == "done", job
        assert not client_output.exists()
        artifact = job["artifacts"][0]
        assert artifact["url"].startswith("/v1/artifacts/")
        assert artifact["filename"] == client_output.name

        artifact_files = list(workspace.rglob(client_output.name))
        assert len(artifact_files) == 1

        with urllib.request.urlopen(f"{base_url}{artifact['url']}", timeout=5) as response:
            assert response.status == HTTPStatus.OK
            assert response.headers["content-type"] == "audio/wav"
    except urllib.error.HTTPError as exc:
        pytest.fail(f"unexpected HTTP {exc.code}: {exc.read().decode()}")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
