from __future__ import annotations

import gc
import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

from engine.acestep.config import AceStepConfig
from engine.acestep.path import ensure_project_root_on_path


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
        self._release_dit_before_decode = False
        self._config: AceStepConfig | None = None
        self._needs_reload = False

    def load(self, config: AceStepConfig) -> None:
        ensure_project_root_on_path(config.project_root)
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
        self._config = config
        self._needs_reload = False
        # CPU hosts keep DiT resident (~12GB). Free it before VAE decode so
        # longer clips fit in ≤16GB RAM. MPS/CUDA keep the model warm.
        self._release_dit_before_decode = config.device == "cpu" or config.offload_to_cpu

    def generate(self, request: RuntimeGenerateRequest) -> RuntimeGenerateResult:
        if self._needs_reload:
            if self._config is None:
                raise RuntimeError("ACE-Step runtime has not been loaded")
            self.load(self._config)
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
        restore = _install_dit_release_hook(self._handler, enabled=self._release_dit_before_decode)
        try:
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
        finally:
            restore()
            if self._release_dit_before_decode:
                self._needs_reload = True
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


def _install_dit_release_hook(handler: object, *, enabled: bool) -> Callable[[], None]:
    """Free the DiT before VAE decode to reclaim multi-GB of CPU RAM."""
    if not enabled:
        return lambda: None
    decode = getattr(handler, "_decode_generate_music_pred_latents", None)
    if not callable(decode):
        return lambda: None

    def _release_dit() -> None:
        for attr in ("model", "text_encoder", "text_encoder_model"):
            obj = getattr(handler, attr, None)
            if obj is None:
                continue
            setattr(handler, attr, None)
            del obj
        gc.collect()
        release = getattr(handler, "_release_system_memory", None)
        if callable(release):
            release()

    def hooked(*args: Any, **kwargs: Any) -> Any:
        _release_dit()
        return decode(*args, **kwargs)

    handler._decode_generate_music_pred_latents = hooked  # type: ignore[attr-defined]

    def restore() -> None:
        handler._decode_generate_music_pred_latents = decode  # type: ignore[attr-defined]

    return restore
