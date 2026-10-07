from __future__ import annotations

import asyncio
import json
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote
from uuid import uuid4

from pydantic import ValidationError

from core.engines import engine_descriptors, runtime_registry
from core.manifest import OPERATION_MANIFEST
from engine.errors import EngineValidationError
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

_REGISTRY = runtime_registry()


def _ensure_workspace() -> Path:
    _WORKSPACE.mkdir(parents=True, exist_ok=True)
    return _WORKSPACE


def _artifact_url(token: str) -> str:
    return f"/v1/artifacts/{token}"


def _job_output_path(job_id: str, client_path: Path, fallback_name: str) -> Path:
    name = client_path.name or fallback_name
    return _WORKSPACE / job_id / name


def _job_workspace(job_id: str) -> Path:
    return (_ensure_workspace() / job_id).resolve()


def _content_disposition(filename: str) -> str:
    display_name = "".join(
        "_" if ord(char) < 32 or ord(char) == 127 or char in {'"', "\\"} else char
        for char in filename
    )
    fallback_name = "".join(
        "_"
        if ord(char) < 32 or ord(char) == 127 or ord(char) > 126 or char in {'"', "\\"}
        else char
        for char in display_name
    )
    encoded = quote(display_name, safe="")
    return f"inline; filename=\"{fallback_name}\"; filename*=UTF-8''{encoded}"


def _validate_engine_request(engine_name: str, operation: Operation, request: object) -> None:
    engine = _REGISTRY.for_operation(engine_name, operation)
    validator = getattr(engine, "validate_request", None)
    if callable(validator):
        cast(Callable[[Operation, object], None], validator)(operation, request)


def _store_artifacts(job_id: str, op_result: OperationResult) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    workspace = _ensure_workspace()
    job_workspace = _job_workspace(job_id)
    for idx, art in enumerate(op_result.artifacts):
        src = Path(art.path)
        if not src.exists() or not src.is_file():
            raise ValueError(f"artifact path is not a file: {src}")
        resolved_src = src.resolve()
        if not resolved_src.is_relative_to(job_workspace):
            raise ValueError(f"artifact path escapes the job workspace: {src}")
        token = f"{job_id}-{idx}-{uuid4().hex}"
        dst = workspace / f"{token}{resolved_src.suffix.lower()}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved_src, dst)
        _ARTIFACTS[token] = ArtifactRecord(
            path=dst.resolve(),
            media_type=art.media_type or "application/octet-stream",
            filename=resolved_src.name,
        )
        out.append(
            {
                "url": _artifact_url(token),
                "media_type": art.media_type or "application/octet-stream",
                "duration_s": art.duration_s,
                "filename": resolved_src.name,
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

        workspace = _ensure_workspace()
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

        context = OperationContext(job_id=job.job_id, workspace=workspace / job.job_id)
        context.workspace.mkdir(parents=True, exist_ok=True)

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
            try:
                size = artifact.path.stat().st_size
                with artifact.path.open("rb") as fp:
                    self.send_response(HTTPStatus.OK)
                    self.send_header("content-type", artifact.media_type)
                    self.send_header("content-length", str(size))
                    self.send_header("content-disposition", _content_disposition(artifact.filename))
                    self.end_headers()
                    shutil.copyfileobj(fp, self.wfile, length=1024 * 64)
            except Exception:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "read_failed"})
                return
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
            typed_request = REQUEST_MODELS[operation].model_validate(
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
        try:
            _validate_engine_request(engine_name, selected_operation, typed_request)
        except EngineValidationError as exc:
            self._json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "validation_error",
                    "details": exc.details(),
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
    _ensure_workspace()
    server = ThreadingHTTPServer((host, port), BeatForgeHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
