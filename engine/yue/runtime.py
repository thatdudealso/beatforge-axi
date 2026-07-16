from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import math
import re
import shutil
import sys
from pathlib import Path
from typing import Protocol, cast

from engine.models import GenerateRequest, OperationContext, RemixRequest

from .config import CheckpointRole, YueConfig
from .models import YueEnvironment, YueRuntimeError, YueRuntimeResult

OPTIONAL_DEPENDENCIES = (
    "einops",
    "flash_attn",
    "numpy",
    "omegaconf",
    "soundfile",
    "torch",
    "torchaudio",
    "transformers",
)
UPSTREAM_SECTION_PATTERN = re.compile(r"^\[\w+\]", flags=re.MULTILINE)


class _CudaProperties(Protocol):
    name: str
    total_memory: int


class _CudaApi(Protocol):
    def is_available(self) -> bool: ...

    def get_device_properties(self, device: int) -> _CudaProperties: ...


class _TorchModule(Protocol):
    cuda: _CudaApi


class YueSubprocessRuntime:
    """Runs the pinned upstream script without importing it into BeatForge."""

    def probe(self, config: YueConfig) -> YueEnvironment:
        missing = tuple(
            dependency
            for dependency in OPTIONAL_DEPENDENCIES
            if importlib.util.find_spec(dependency) is None
        )
        if "torch" in missing:
            return YueEnvironment(
                missing_dependencies=missing,
                cuda_available=False,
                device_name=None,
                vram_gb=None,
            )

        try:
            torch_module = cast(_TorchModule, importlib.import_module("torch"))
            cuda_available = torch_module.cuda.is_available()
            if not cuda_available:
                return YueEnvironment(
                    missing_dependencies=missing,
                    cuda_available=False,
                    device_name=None,
                    vram_gb=None,
                )
            properties = torch_module.cuda.get_device_properties(config.cuda_index)
        except (ImportError, RuntimeError, ValueError, AssertionError):
            return YueEnvironment(
                missing_dependencies=missing,
                cuda_available=False,
                device_name=None,
                vram_gb=None,
            )

        return YueEnvironment(
            missing_dependencies=missing,
            cuda_available=True,
            device_name=properties.name,
            vram_gb=properties.total_memory / (1024**3),
        )

    async def generate(
        self,
        config: YueConfig,
        request: GenerateRequest,
        context: OperationContext,
    ) -> YueRuntimeResult:
        lyrics = self._normalize_lyrics(request.prompt)
        return await self._run(
            config=config,
            context=context,
            genre=config.default_genre,
            lyrics=lyrics,
            segments=max(1, math.ceil(request.duration_s / 30)),
            output_path=request.out,
            seed=request.seed,
            stage1_role=CheckpointRole.STAGE1,
        )

    async def remix(
        self,
        config: YueConfig,
        request: RemixRequest,
        context: OperationContext,
    ) -> YueRuntimeResult:
        return await self._run(
            config=config,
            context=context,
            genre=request.style,
            lyrics=self._normalize_lyrics(request.style),
            segments=2,
            output_path=request.out,
            seed=request.seed,
            audio_prompt=request.input_file,
            stage1_role=CheckpointRole.STAGE1_ICL,
        )

    @staticmethod
    def _normalize_lyrics(prompt: str) -> str:
        stripped = prompt.lstrip()
        lyrics = stripped if stripped.startswith("[") else f"[verse]\n{prompt}"
        if len(UPSTREAM_SECTION_PATTERN.findall(lyrics)) >= 2:
            return lyrics
        lines = lyrics.rstrip().splitlines()
        body = "\n".join(lines[1:]).strip() if lines else ""
        continuation = body or "instrumental continuation"
        return f"{lyrics.rstrip()}\n\n[chorus]\n{continuation}"

    async def _run(
        self,
        *,
        config: YueConfig,
        context: OperationContext,
        genre: str,
        lyrics: str,
        segments: int,
        output_path: Path,
        seed: int | None,
        stage1_role: CheckpointRole,
        audio_prompt: Path | None = None,
    ) -> YueRuntimeResult:
        upstream_root = config.upstream_root
        stage1 = config.checkpoint_for(stage1_role)
        stage2 = config.checkpoint_for(CheckpointRole.STAGE2)
        codec = config.checkpoint_for(CheckpointRole.CODEC)
        if output_path.suffix.lower() != ".mp3":
            raise YueRuntimeError("YuE only supports .mp3 output")
        if upstream_root is None or stage1 is None or stage2 is None or codec is None:
            raise YueRuntimeError("adapter configuration was not validated before inference")
        if stage1.location is None or stage2.location is None or codec.location is None:
            raise YueRuntimeError("checkpoint location was not configured")

        inference_dir = upstream_root / "inference"
        job_dir, output_dir, genre_file, lyrics_file = self._adapter_paths(context)
        job_dir.mkdir(parents=True, exist_ok=True)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        genre_file.write_text(f"{genre.strip()}\n", encoding="utf-8")
        lyrics_file.write_text(f"{lyrics.rstrip()}\n", encoding="utf-8")

        command = [
            sys.executable,
            "infer.py",
            "--cuda_idx",
            str(config.cuda_index),
            "--stage1_model",
            stage1.location,
            "--stage2_model",
            stage2.location,
            "--genre_txt",
            str(genre_file),
            "--lyrics_txt",
            str(lyrics_file),
            "--run_n_segments",
            str(segments),
            "--output_dir",
            str(output_dir),
            "--seed",
            str(42 if seed is None else seed),
            "--basic_model_config",
            str(Path(codec.location) / "final_ckpt" / "config.yaml"),
            "--resume_path",
            str(Path(codec.location) / "final_ckpt" / "ckpt_00360000.pth"),
            "--config_path",
            str(Path(codec.location) / "decoders" / "config.yaml"),
            "--vocal_decoder_path",
            str(Path(codec.location) / "decoders" / "decoder_131000.pth"),
            "--inst_decoder_path",
            str(Path(codec.location) / "decoders" / "decoder_151000.pth"),
        ]
        if audio_prompt is not None:
            command.extend(("--use_audio_prompt", "--audio_prompt_path", str(audio_prompt)))

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=inference_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
        except (OSError, ValueError) as error:
            raise YueRuntimeError(f"could not start pinned YuE inference: {error}") from error
        if process.returncode != 0:
            detail = (
                stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
            )
            raise YueRuntimeError(detail[-1000:] or f"process exited {process.returncode}")

        candidates = sorted(output_dir.glob("*.mp3"))
        if len(candidates) != 1:
            raise YueRuntimeError(
                f"expected one final MP3 from YuE, found {len(candidates)} in {output_dir}"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidates[0], output_path)
        return YueRuntimeResult(
            path=output_path,
            duration_s=None,
            metadata={
                "mode": "single-track-icl" if audio_prompt is not None else "lyrics2song",
                "segments": segments,
            },
        )

    @staticmethod
    def _adapter_paths(context: OperationContext) -> tuple[Path, Path, Path, Path]:
        workspace = context.workspace.resolve()
        digest = hashlib.sha256(context.job_id.encode()).hexdigest()[:16]
        job_dir = workspace / f".yue-{digest}"
        output_dir = job_dir / "output"
        genre_file = job_dir / "genre.txt"
        lyrics_file = job_dir / "lyrics.txt"
        for path in (job_dir, output_dir, genre_file, lyrics_file):
            YueSubprocessRuntime._verify_adapter_path(workspace, path)
        return job_dir, output_dir, genre_file, lyrics_file

    @staticmethod
    def _verify_adapter_path(workspace: Path, path: Path) -> None:
        if path.is_symlink():
            raise YueRuntimeError("unsafe YuE workspace path")
        try:
            path.resolve(strict=False).relative_to(workspace)
        except ValueError as error:
            raise YueRuntimeError("unsafe YuE workspace path") from error
