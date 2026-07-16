from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast

from engine.acestep.config import AceStepConfig


@dataclass(frozen=True, slots=True)
class RuntimeGenerateRequest:
    prompt: str
    duration_s: float
    output_dir: Path
    output_format: str
    seed: int | None


@dataclass(frozen=True, slots=True)
class RuntimeGenerateResult:
    path: Path
    duration_s: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class RuntimeBoundary(Protocol):
    def load(self, config: AceStepConfig) -> None: ...

    def generate(self, request: RuntimeGenerateRequest) -> RuntimeGenerateResult: ...


class _UpstreamHandler(Protocol):
    device: str

    def initialize_service(
        self,
        project_root: str,
        config_path: str,
        device: str = "auto",
        use_flash_attention: bool = False,
        compile_model: bool = False,
        offload_to_cpu: bool = False,
        offload_dit_to_cpu: bool = False,
        quantization: str | None = None,
        prefer_source: str | None = None,
        use_mlx_dit: bool = True,
        vae_checkpoint: str | None = None,
    ) -> tuple[str, bool]: ...


class _UpstreamGeneration(Protocol):
    success: bool
    error: str | None
    audios: list[dict[str, object]]


class AceStepRuntime:
    """Lazy boundary around the API at the pinned upstream commit."""

    def __init__(self) -> None:
        self._handler: _UpstreamHandler | None = None
        self._params_factory: Callable[..., object] | None = None
        self._config_factory: Callable[..., object] | None = None
        self._generate_music: Callable[..., object] | None = None
        self._device: str | None = None

    def load(self, config: AceStepConfig) -> None:
        handler_module = importlib.import_module("acestep.handler")
        inference_module = importlib.import_module("acestep.inference")
        handler_file = handler_module.__file__
        if not isinstance(handler_file, str) or not Path(handler_file).resolve().is_relative_to(
            config.project_root.resolve()
        ):
            raise RuntimeError("imported ACE-Step package does not come from project_root")
        handler_factory = cast(Callable[[], _UpstreamHandler], handler_module.AceStepHandler)
        self._params_factory = cast(Callable[..., object], inference_module.GenerationParams)
        self._config_factory = cast(Callable[..., object], inference_module.GenerationConfig)
        self._generate_music = cast(Callable[..., object], inference_module.generate_music)
        handler = handler_factory()
        status, initialized = handler.initialize_service(
            project_root=str(config.project_root),
            config_path=config.config_path,
            device=config.device,
            use_flash_attention=False,
            compile_model=False,
            offload_to_cpu=config.offload_to_cpu,
            offload_dit_to_cpu=config.offload_dit_to_cpu,
            quantization=None,
            prefer_source="huggingface",
            use_mlx_dit=config.use_mlx_dit,
            vae_checkpoint="official",
        )
        if not initialized:
            raise RuntimeError(status)
        self._handler = handler
        self._device = handler.device

    def generate(self, request: RuntimeGenerateRequest) -> RuntimeGenerateResult:
        if (
            self._handler is None
            or self._params_factory is None
            or self._config_factory is None
            or self._generate_music is None
        ):
            raise RuntimeError("ACE-Step runtime has not been loaded")
        params = self._params_factory(
            task_type="text2music",
            caption=request.prompt,
            lyrics="[Instrumental]",
            instrumental=True,
            duration=request.duration_s,
            inference_steps=8,
            seed=request.seed if request.seed is not None else -1,
            guidance_scale=1.0,
            shift=3.0,
            thinking=False,
            use_cot_metas=False,
            use_cot_caption=False,
            use_cot_language=False,
        )
        generation_config = self._config_factory(
            batch_size=1,
            use_random_seed=request.seed is None,
            seeds=None if request.seed is None else [request.seed],
            audio_format=request.output_format,
        )
        native_result = cast(
            _UpstreamGeneration,
            self._generate_music(
                self._handler,
                None,
                params,
                generation_config,
                save_dir=str(request.output_dir),
            ),
        )
        if not native_result.success:
            raise RuntimeError(native_result.error or "ACE-Step returned an unsuccessful result")
        if not native_result.audios:
            raise RuntimeError("ACE-Step returned no audio artifacts")
        path_value = native_result.audios[0].get("path")
        if not isinstance(path_value, str) or not path_value:
            raise RuntimeError("ACE-Step returned an invalid audio artifact path")
        audio_params = native_result.audios[0].get("params")
        seed = request.seed
        if isinstance(audio_params, dict):
            seed_value = cast(dict[str, object], audio_params).get("seed")
            if isinstance(seed_value, int):
                seed = seed_value
        return RuntimeGenerateResult(
            path=Path(path_value),
            duration_s=request.duration_s,
            metadata={"device": self._device, "seed": seed},
        )
