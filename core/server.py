from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from pydantic import ValidationError

from core.engines import engine_descriptors, runtime_registry
from core.manifest import OPERATION_MANIFEST
from engine.models import (
    AnalyzeRequest,
    GenerateRequest,
    Operation,
    OperationContext,
    OperationResult,
    RemixRequest,
    RepaintRequest,
    StemsRequest,
)

REQUEST_MODELS = {
    Operation.GENERATE.value: GenerateRequest,
    Operation.REPAINT.value: RepaintRequest,
    Operation.REMIX.value: RemixRequest,
    Operation.STEMS.value: StemsRequest,
    Operation.ANALYZE.value: AnalyzeRequest,
}

# --- Real job runtime (no fake) ---


@dataclass
class JobRecord:
    job_id: str
    operation: str
    status: str  # queued | running | done | error
    engine: str
    result: dict[str, Any] | None = None
    error: str | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ArtifactRecord:
    path: Path
    media_type: str
    filename: str


_JOBS: dict[str, JobRecord] = {}
_ARTIFACTS: dict[str, ArtifactRecord] = {}
_WORKSPACE = Path.cwd() / ".beatforge" / "server-workspace"
_WORKSPACE.mkdir(parents=True, exist_ok=True)

_REGISTRY = runtime_registry()


def _artifact_url(token: str) -> str:
    return f"/v1/artifacts/{token}"


def _job_output_path(job_id: str, client_path: Path, fallback_name: str) -> Path:
    name = client_path.name or fallback_name
    return _WORKSPACE / job_id / name


def _store_artifacts(job_id: str, op_result: OperationResult) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, art in enumerate(op_result.artifacts):
        src = Path(art.path)
        if not src.exists():
            continue
        token = f"{job_id}-{idx}-{uuid4().hex}"
        dst = _WORKSPACE / f"{token}{src.suffix.lower()}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Copy to stable workspace location (simple and safe)
        import shutil

        shutil.copy2(src, dst)
        _ARTIFACTS[token] = ArtifactRecord(
            path=dst.resolve(),
            media_type=art.media_type or "application/octet-stream",
            filename=src.name,
        )
        out.append(
            {
                "url": _artifact_url(token),
                "media_type": art.media_type or "application/octet-stream",
                "duration_s": art.duration_s,
                "filename": src.name,
            }
        )
    return out


def _execute_job(job: JobRecord, body: dict[str, Any]) -> None:
    job.status = "running"
    try:
        op = Operation(job.operation)
        engine_name = job.engine
        # Build the typed request (drop engine from payload)
        req_dict = {k: v for k, v in body.items() if k != "engine"}
        model = REQUEST_MODELS[job.operation]
        request = model.model_validate(req_dict)

        if isinstance(request, GenerateRequest):
            request.out = _job_output_path(job.job_id, Path(request.out), "output.wav")
        elif isinstance(request, (RepaintRequest, RemixRequest)):
            request.out = _job_output_path(  # type: ignore[attr-defined]
                job.job_id,
                Path(request.out),
                "output.mp3",  # type: ignore[attr-defined]
            )
        elif isinstance(request, StemsRequest):
            request.out_dir = _job_output_path(job.job_id, Path(request.out_dir), "stems")

        context = OperationContext(job_id=job.job_id, workspace=_WORKSPACE / job.job_id)
        (_WORKSPACE / job.job_id).mkdir(parents=True, exist_ok=True)

        # Execute via real registry + engine (synth by default)
        engine = _REGISTRY.for_operation(engine_name, op)
        result: OperationResult = asyncio.run(getattr(engine, op.value)(request, context))

        artifacts = _store_artifacts(job.job_id, result)
        job.artifacts = artifacts
        job.result = {
            "operation": result.operation.value,
            "status": "done",
            "engine": engine_name,
            "artifacts": artifacts,
            "metadata": result.metadata,
            "warnings": result.warnings,
        }
        job.status = "done"
    except Exception as exc:  # pragma: no cover - surface real errors
        job.status = "error"
        job.error = str(exc)


def manifest_payload() -> dict[str, Any]:
    return {
        "name": "beatforge-axi",
        "version": 1,
        "operations": {
            operation.value: {
                "cli_command": entry.cli_command,
                "api_route": entry.api_route,
                "ui_control": entry.ui_control,
                "capability": entry.capability.value,
            }
            for operation, entry in OPERATION_MANIFEST.items()
        },
        "engines": {
            name: {
                "ready": descriptor.ready,
                "capabilities": sorted(
                    operation.value for operation in descriptor.capabilities.supported_operations()
                ),
            }
            for name, descriptor in engine_descriptors().items()
        },
    }


class BeatForgeHandler(BaseHTTPRequestHandler):
    server_version = "beatforge-axi/0.1"

    def do_GET(self) -> None:
        if self.path == "/v1/manifest":
            self._json(HTTPStatus.OK, manifest_payload())
            return

        if self.path.startswith("/v1/jobs/"):
            job_id = self.path.removeprefix("/v1/jobs/")
            job = _JOBS.get(job_id)
            if job is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "job_not_found"})
                return
            payload: dict[str, Any] = {
                "job_id": job.job_id,
                "operation": job.operation,
                "status": job.status,
                "engine": job.engine,
            }
            if job.result is not None:
                payload["result"] = job.result
            if job.error:
                payload["error"] = job.error
            if job.artifacts:
                payload["artifacts"] = job.artifacts
            self._json(HTTPStatus.OK, payload)
            return

        if self.path.startswith("/v1/artifacts/"):
            token = self.path.removeprefix("/v1/artifacts/")
            artifact = _ARTIFACTS.get(token)
            if artifact is None or not artifact.path.exists():
                self._json(HTTPStatus.NOT_FOUND, {"error": "artifact_not_found"})
                return
            # Safe serve: only tokens we registered map to real files in our workspace
            try:
                data = artifact.path.read_bytes()
            except Exception:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "read_failed"})
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", artifact.media_type)
            self.send_header("content-length", str(len(data)))
            filename = artifact.filename.replace("\\", "_").replace('"', "_")
            self.send_header("content-disposition", f'inline; filename="{filename}"')
            self.end_headers()
            self.wfile.write(data)
            return

        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        operation = self.path.removeprefix("/v1/jobs/")
        if operation not in {item.value for item in OPERATION_MANIFEST}:
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown_operation"})
            return
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        try:
            decoded: object = json.loads(body)
        except json.JSONDecodeError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return
        if not isinstance(decoded, dict):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json_object"})
            return
        request = cast(dict[str, Any], decoded)
        engine_name = request.get("engine", "synth")
        if not isinstance(engine_name, str):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_engine"})
            return
        descriptor = engine_descriptors().get(engine_name)
        if descriptor is None:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "unknown_engine"})
            return
        if not descriptor.ready:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "engine_unavailable"})
            return
        selected_operation = Operation(operation)
        if not descriptor.capabilities.supports(selected_operation):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "unsupported_operation"})
            return
        try:
            REQUEST_MODELS[operation].model_validate(
                {key: value for key, value in request.items() if key != "engine"}
            )
        except ValidationError as exc:
            self._json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "validation_error",
                    "details": exc.errors(include_url=False),
                },
            )
            return
        job_id = uuid4().hex
        job = JobRecord(job_id=job_id, operation=operation, status="queued", engine=engine_name)
        _JOBS[job_id] = job

        # Start real execution in background thread (synth produces real audio)
        body_for_exec = request  # original decoded dict
        t = threading.Thread(target=_execute_job, args=(job, body_for_exec), daemon=True)
        t.start()

        self._json(
            HTTPStatus.ACCEPTED,
            {
                "job_id": job_id,
                "operation": operation,
                "status": "queued",
                "engine": engine_name,
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), BeatForgeHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
