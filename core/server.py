from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from uuid import uuid4

from pydantic import ValidationError

from core.engines import engine_descriptors
from core.manifest import OPERATION_MANIFEST
from engine.models import (
    AnalyzeRequest,
    GenerateRequest,
    Operation,
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
        engine_name = request.get("engine", "fake")
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
        self._json(
            HTTPStatus.ACCEPTED,
            {
                "job_id": uuid4().hex,
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
