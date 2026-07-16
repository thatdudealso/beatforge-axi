from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import core.server as server_module
from core.server import manifest_payload
from engine.models import Artifact, GenerateRequest, Operation, OperationContext, OperationResult


class _Registry:
    def __init__(self, media_type: str) -> None:
        self._media_type = media_type

    def for_operation(self, engine_name: str, operation: Operation) -> object:
        return _GenerateEngine(self._media_type)


class _GenerateEngine:
    def __init__(self, media_type: str) -> None:
        self._media_type = media_type

    async def generate(
        self, request: GenerateRequest, context: OperationContext
    ) -> OperationResult:
        request.out.parent.mkdir(parents=True, exist_ok=True)
        request.out.write_bytes(b"audio")
        return OperationResult(
            operation=Operation.GENERATE,
            artifacts=[
                Artifact(path=request.out, media_type=self._media_type, duration_s=1.0),
            ],
        )


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == HTTPStatus.ACCEPTED
        return json.loads(response.read())


def _wait_for_job(base_url: str, job_id: str) -> dict[str, Any]:
    job_url = f"{base_url}/v1/jobs/{job_id}"
    for _ in range(40):
        with urllib.request.urlopen(job_url, timeout=5) as response:
            job = json.loads(response.read())
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(0.05)
    pytest.fail("job did not finish")


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
        accepted = _post_json(f"{base_url}/v1/jobs/generate", json.loads(payload))
        job = _wait_for_job(base_url, accepted["job_id"])

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


def test_artifact_url_is_safe_for_display_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "server-workspace"
    monkeypatch.setattr(server_module, "_WORKSPACE", workspace)
    monkeypatch.setattr(server_module, "_JOBS", {})
    monkeypatch.setattr(server_module, "_ARTIFACTS", {})
    monkeypatch.setattr(server_module, "_REGISTRY", _Registry("audio/wav"))
    source = tmp_path / "my beat #1.wav"

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_module.BeatForgeHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{httpd.server_port}"
    try:
        accepted = _post_json(
            f"{base_url}/v1/jobs/generate",
            {
                "engine": "synth",
                "prompt": "warm lofi",
                "duration_s": 1,
                "out": str(source),
            },
        )
        job = _wait_for_job(base_url, accepted["job_id"])

        assert job["status"] == "done", job
        artifact = job["artifacts"][0]
        assert artifact["filename"] == source.name
        assert urllib.parse.quote(source.name) not in artifact["url"]
        assert source.name not in artifact["url"]
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_artifact_endpoint_serves_registered_media_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "server-workspace"
    monkeypatch.setattr(server_module, "_WORKSPACE", workspace)
    monkeypatch.setattr(server_module, "_JOBS", {})
    monkeypatch.setattr(server_module, "_ARTIFACTS", {})
    monkeypatch.setattr(server_module, "_REGISTRY", _Registry("audio/flac"))

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_module.BeatForgeHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{httpd.server_port}"
    try:
        accepted = _post_json(
            f"{base_url}/v1/jobs/generate",
            {
                "engine": "synth",
                "prompt": "warm lofi",
                "duration_s": 1,
                "out": str(tmp_path / "take.flac"),
            },
        )
        job = _wait_for_job(base_url, accepted["job_id"])

        assert job["status"] == "done", job
        with urllib.request.urlopen(
            f"{base_url}{job['artifacts'][0]['url']}", timeout=5
        ) as response:
            assert response.status == HTTPStatus.OK
            assert response.headers["content-type"] == "audio/flac"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
