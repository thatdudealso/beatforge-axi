from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer
from pydantic import ValidationError

from core.engines import runtime_registry
from core.server import run_server
from engine.errors import EngineUnavailableError, UnsupportedOperationError
from engine.models import (
    AnalyzeRequest,
    GenerateRequest,
    Operation,
    OperationContext,
    OperationResult,
    RemixRequest,
    RepaintRequest,
    StemsRequest,
    TimeRange,
)
from engine.registry import EngineRegistry

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Local-first music generation AXI.",
)


def _registry() -> EngineRegistry:
    return runtime_registry()


def _context() -> OperationContext:
    return OperationContext(job_id=uuid4().hex, workspace=Path.cwd() / ".beatforge" / "jobs")


def _parse_section(value: str) -> TimeRange:
    try:
        start, end = value.split("-", maxsplit=1)
        return TimeRange(start_s=_parse_timestamp(start), end_s=_parse_timestamp(end))
    except ValueError as exc:
        raise typer.BadParameter("expected START-END, for example 0:30-0:45") from exc


def _parse_timestamp(value: str) -> float:
    parts = value.split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    raise ValueError("invalid timestamp")


def _media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".wav": "audio/wav",
    }.get(suffix, "application/octet-stream")


def _format_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _toon_success(engine: str, result: OperationResult) -> str:
    lines = [
        f"operation: {result.operation.value}",
        "status: ok",
        f"engine: {engine}",
    ]
    if result.artifacts:
        lines.append(f"artifacts[{len(result.artifacts)}]: path,media_type,duration_s")
        for artifact in result.artifacts:
            media_type = artifact.media_type or _media_type(artifact.path)
            duration = "" if artifact.duration_s is None else str(float(artifact.duration_s))
            lines.append(f"  {artifact.path},{media_type},{duration}")
    if result.metadata:
        lines.append("metadata:")
        for key in sorted(result.metadata):
            lines.append(f"  {key}: {_format_scalar(result.metadata[key])}")
    if result.warnings:
        lines.append(f"warnings[{len(result.warnings)}]: message")
        lines.extend(f"  {warning}" for warning in result.warnings)
    return "\n".join(lines) + "\n"


def _toon_error(operation: Operation, code: str, message: str) -> str:
    return (
        "\n".join(
            [
                f"operation: {operation.value}",
                "status: error",
                f"code: {code}",
                f"message: {message}",
            ]
        )
        + "\n"
    )


def _run(operation: Operation, engine_name: str, request: object) -> tuple[int, str]:
    registry = _registry()
    try:
        engine = registry.for_operation(engine_name, operation)
        context = _context()
        result = asyncio.run(getattr(engine, operation.value)(request, context))
    except UnsupportedOperationError as exc:
        return 1, _toon_error(operation, "unsupported", str(exc))
    except EngineUnavailableError as exc:
        return 1, _toon_error(operation, "engine_unavailable", str(exc))
    except KeyError:
        return 1, _toon_error(operation, "engine_unavailable", f"unknown engine: {engine_name}")
    return 0, _toon_success(engine.descriptor.name, result)


def _validation_error(operation: Operation, exc: ValidationError) -> tuple[int, str]:
    message = "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
    )
    return 1, _toon_error(operation, "validation_error", message)


@app.callback()
def configure(
    ctx: typer.Context,
    engine: Annotated[str, typer.Option("--engine", help="Engine adapter to use.")] = "fake",
) -> None:
    ctx.obj = {"engine": engine}


@app.command()
def generate(
    ctx: typer.Context,
    prompt: Annotated[str, typer.Option("--prompt", help="Text prompt.")],
    duration: Annotated[float, typer.Option("--duration", min=0.1, help="Duration in seconds.")],
    out: Annotated[Path, typer.Option("--out", help="Output audio path.")],
    seed: Annotated[int | None, typer.Option("--seed", help="Optional deterministic seed.")] = None,
) -> None:
    try:
        request = GenerateRequest(prompt=prompt, duration_s=duration, out=out, seed=seed)
    except ValidationError as exc:
        code, output = _validation_error(Operation.GENERATE, exc)
    else:
        code, output = _run(Operation.GENERATE, ctx.obj["engine"], request)
    typer.echo(output, nl=False)
    raise typer.Exit(code)


@app.command()
def repaint(
    ctx: typer.Context,
    input_file: Annotated[Path, typer.Option("--in", help="Input audio path.")],
    section: Annotated[str, typer.Option("--section", help="Section range, like 0:30-0:45.")],
    prompt: Annotated[str, typer.Option("--prompt", help="Repaint prompt.")],
    out: Annotated[Path | None, typer.Option("--out", help="Output audio path.")] = None,
    seed: Annotated[int | None, typer.Option("--seed", help="Optional deterministic seed.")] = None,
) -> None:
    output = out or input_file.with_name(f"{input_file.stem}.repaint.mp3")
    try:
        request = RepaintRequest(
            input_file=input_file,
            section=_parse_section(section),
            prompt=prompt,
            out=output,
            seed=seed,
        )
    except ValidationError as exc:
        code, body = _validation_error(Operation.REPAINT, exc)
    else:
        code, body = _run(Operation.REPAINT, ctx.obj["engine"], request)
    typer.echo(body, nl=False)
    raise typer.Exit(code)


@app.command()
def remix(
    ctx: typer.Context,
    input_file: Annotated[Path, typer.Option("--in", help="Input audio path.")],
    style: Annotated[str, typer.Option("--style", help="Target style.")],
    out: Annotated[Path | None, typer.Option("--out", help="Output audio path.")] = None,
    strength: Annotated[float, typer.Option("--strength", min=0, max=1)] = 0.65,
    seed: Annotated[int | None, typer.Option("--seed", help="Optional deterministic seed.")] = None,
) -> None:
    output = out or input_file.with_name(f"{input_file.stem}.remix.mp3")
    try:
        request = RemixRequest(
            input_file=input_file, style=style, out=output, strength=strength, seed=seed
        )
    except ValidationError as exc:
        code, body = _validation_error(Operation.REMIX, exc)
    else:
        code, body = _run(Operation.REMIX, ctx.obj["engine"], request)
    typer.echo(body, nl=False)
    raise typer.Exit(code)


@app.command()
def stems(
    ctx: typer.Context,
    input_file: Annotated[Path, typer.Option("--in", help="Input audio path.")],
    out_dir: Annotated[
        Path | None, typer.Option("--out-dir", help="Stem output directory.")
    ] = None,
) -> None:
    output = out_dir or input_file.with_name(f"{input_file.stem}.stems")
    try:
        request = StemsRequest(input_file=input_file, out_dir=output)
    except ValidationError as exc:
        code, body = _validation_error(Operation.STEMS, exc)
    else:
        code, body = _run(Operation.STEMS, ctx.obj["engine"], request)
    typer.echo(body, nl=False)
    raise typer.Exit(code)


@app.command()
def analyze(
    ctx: typer.Context,
    file: Annotated[Path, typer.Option("--file", help="Audio file to analyze.")],
) -> None:
    try:
        request = AnalyzeRequest(file=file)
    except ValidationError as exc:
        code, body = _validation_error(Operation.ANALYZE, exc)
    else:
        code, body = _run(Operation.ANALYZE, ctx.obj["engine"], request)
    typer.echo(body, nl=False)
    raise typer.Exit(code)


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host", help="Loopback host to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535, help="Port to bind.")] = 8765,
) -> None:
    run_server(host, port)


def main() -> None:
    app()
