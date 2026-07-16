from __future__ import annotations

import importlib.util
import json
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from typing import Any, Protocol, cast

from engine.musicgen.checkpoint import checkpoint_sha256 as calculate_checkpoint_sha256

_AUDIOCRAFT_VERSION = "1.4.0a2"
_AUDIOCRAFT_COMMIT = "896ec7c47f5e5d1e5aa1e4b260c4405328bf009d"
_INFERENCE_LOCK = Lock()


@dataclass(frozen=True)
class GeneratedAudio:
    sample_rate: int
    channels: int
    frames: int


class MusicGenRuntime(Protocol):
    def availability_diagnostic(self) -> str | None: ...

    def generate(
        self,
        *,
        checkpoint: Path,
        checkpoint_sha256: str,
        device: str | None,
        prompt: str,
        duration_s: float,
        seed: int | None,
        out: Path,
    ) -> GeneratedAudio: ...


class _Waveform(Protocol):
    @property
    def shape(self) -> tuple[int, ...]: ...

    def cpu(self) -> _Waveform: ...


class _WaveformBatch(Protocol):
    def __getitem__(self, index: int) -> _Waveform: ...


class _MusicGenModel(Protocol):
    sample_rate: int

    def set_generation_params(self, *, duration: float) -> None: ...

    def generate(self, prompts: list[str], *, progress: bool) -> _WaveformBatch: ...


class _StatefulModel(Protocol):
    def load_state_dict(self, state: object) -> object: ...

    def eval(self) -> object: ...


class _MusicGenFactory(Protocol):
    def __call__(
        self,
        name: str,
        compression_model: _StatefulModel,
        lm: _StatefulModel,
    ) -> _MusicGenModel: ...


class _ModelsModule(Protocol):
    MusicGen: _MusicGenFactory


class _ConditionersModule(Protocol):
    T5Conditioner: type[Any]


class _Config(Protocol):
    device: str
    dtype: str


class _BuildersModule(Protocol):
    def get_compression_model(self, config: _Config) -> _StatefulModel: ...

    def get_lm_model(self, config: _Config) -> _StatefulModel: ...


class _OmegaConfClass(Protocol):
    def create(self, value: object) -> _Config: ...

    def select(self, config: _Config, key: str, default: object = None) -> object: ...

    def update(
        self,
        config: _Config,
        key: str,
        value: object,
        *,
        merge: bool,
    ) -> None: ...

    def to_container(self, value: object, *, resolve: bool) -> object: ...


class _OmegaConfModule(Protocol):
    OmegaConf: _OmegaConfClass


class _CudaModule(Protocol):
    def device_count(self) -> int: ...


class _TorchModule(Protocol):
    cuda: _CudaModule

    def load(self, path: Path, *, map_location: str, weights_only: bool) -> object: ...

    def manual_seed(self, seed: int) -> object: ...


class _AudioModule(Protocol):
    def audio_write(
        self,
        out: Path,
        waveform: _Waveform,
        sample_rate: int,
        *,
        add_suffix: bool,
        format: str,
        loudness_compressor: bool,
        strategy: str,
    ) -> Path: ...


def _reviewed_build_installed(package_origin: str | None) -> bool:
    try:
        installed = distribution("audiocraft")
    except PackageNotFoundError:
        return False
    if installed.version != _AUDIOCRAFT_VERSION:
        return False
    direct_url = installed.read_text("direct_url.json")
    if direct_url is None:
        return False
    try:
        metadata_object = cast(object, json.loads(direct_url))
    except (TypeError, ValueError):
        return False
    if not isinstance(metadata_object, dict):
        return False
    metadata = cast(dict[str, object], metadata_object)
    vcs_info = metadata.get("vcs_info")
    if not isinstance(vcs_info, dict):
        return False
    typed_vcs_info = cast(dict[str, object], vcs_info)
    if not (
        typed_vcs_info.get("vcs") == "git" and typed_vcs_info.get("commit_id") == _AUDIOCRAFT_COMMIT
    ):
        return False
    if package_origin is None:
        return False
    try:
        package_path = Path(package_origin).resolve()
        distribution_root = Path(str(installed.locate_file(""))).resolve()
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return False
    return package_path.is_relative_to(distribution_root)


def _package_value(package: Mapping[str, object], key: str) -> object:
    try:
        return package[key]
    except KeyError as error:
        raise RuntimeError(f"MusicGen checkpoint package is missing {key}") from error


def _package_mapping(package: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = _package_value(package, key)
    if not isinstance(value, Mapping):
        raise RuntimeError(f"MusicGen checkpoint package has invalid {key}")
    raw_value = cast(Mapping[object, object], value)
    if not all(isinstance(raw_key, str) for raw_key in raw_value):
        raise RuntimeError(f"MusicGen checkpoint package has invalid {key}")
    return cast(Mapping[str, object], value)


def _package_config(
    package: Mapping[str, object],
    key: str,
    omega_conf: _OmegaConfClass,
) -> _Config:
    value = _package_value(package, key)
    try:
        config = omega_conf.create(value)
        container = omega_conf.to_container(config, resolve=True)
    except Exception as error:
        raise RuntimeError(f"MusicGen checkpoint package has invalid {key}") from error
    if not isinstance(container, Mapping):
        raise RuntimeError(f"MusicGen checkpoint package has invalid {key}")
    raw_container = cast(Mapping[object, object], container)
    if not all(isinstance(raw_key, str) for raw_key in raw_container):
        raise RuntimeError(f"MusicGen checkpoint package has invalid {key}")
    return config


def _load_checkpoint_package(
    torch: _TorchModule,
    path: Path,
    label: str,
) -> Mapping[str, object]:
    try:
        package = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError as error:
        raise RuntimeError("MusicGen requires safe torch checkpoint deserialization") from error
    if not isinstance(package, Mapping):
        raise RuntimeError(f"MusicGen {label} checkpoint package must be a mapping")
    raw_package = cast(Mapping[object, object], package)
    if not all(isinstance(raw_key, str) for raw_key in raw_package):
        raise RuntimeError(f"MusicGen {label} checkpoint package must be a mapping")
    return cast(Mapping[str, object], package)


def _local_auxiliary_path(snapshot: Path, configured: object, label: str) -> Path:
    if not isinstance(configured, str) or not configured.strip():
        raise RuntimeError(f"MusicGen checkpoint must configure a local {label} auxiliary asset")
    relative = Path(configured)
    if relative.is_absolute():
        raise RuntimeError(f"MusicGen checkpoint must configure a local {label} auxiliary asset")
    root = snapshot.resolve()
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root) or not resolved.exists():
        raise RuntimeError(f"MusicGen checkpoint must contain a local {label} auxiliary asset")
    return resolved


def _t5_dimension(localized: Path) -> int:
    config_file = localized / "config.json"
    try:
        config = json.loads(config_file.read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError("MusicGen T5 auxiliary asset must contain config.json") from error
    if not isinstance(config, dict):
        raise RuntimeError("MusicGen T5 auxiliary config is invalid")
    typed_config = cast(dict[str, object], config)
    dimension = typed_config.get("d_model", typed_config.get("hidden_size"))
    if not isinstance(dimension, int) or dimension <= 0:
        raise RuntimeError("MusicGen T5 auxiliary config must declare d_model")
    return dimension


def _preflight_conditioners(
    config: _Config,
    snapshot: Path,
    omega_conf: _OmegaConfClass,
) -> dict[str, int]:
    local_t5_dimensions: dict[str, int] = {}
    raw_conditioners = omega_conf.select(config, "conditioners", {})
    conditioners = omega_conf.to_container(raw_conditioners, resolve=True)
    if not isinstance(conditioners, dict):
        raise RuntimeError("MusicGen checkpoint has an invalid conditioners configuration")
    typed_conditioners = cast(dict[str, object], conditioners)
    for name, raw_conditioner in typed_conditioners.items():
        if name == "args":
            continue
        if not isinstance(raw_conditioner, dict):
            raise RuntimeError("MusicGen checkpoint has an invalid conditioner configuration")
        typed_conditioner = cast(dict[str, object], raw_conditioner)
        model_type = typed_conditioner.get("model")
        if model_type == "lut":
            model_args = typed_conditioner.get("lut")
            if not isinstance(model_args, dict):
                raise RuntimeError("MusicGen checkpoint has an invalid LUT conditioner")
            typed_model_args = cast(dict[str, object], model_args)
            if typed_model_args.get("tokenizer") != "noop":
                raise RuntimeError("MusicGen LUT conditioners must use the noop tokenizer")
            continue
        if model_type == "t5":
            model_args = typed_conditioner.get("t5")
            if not isinstance(model_args, dict):
                raise RuntimeError("MusicGen checkpoint has an invalid T5 conditioner")
            typed_model_args = cast(dict[str, object], model_args)
            localized = _local_auxiliary_path(snapshot, typed_model_args.get("name"), "T5")
            if not localized.is_dir():
                raise RuntimeError("MusicGen T5 auxiliary asset must be a local directory")
            omega_conf.update(
                config,
                f"conditioners.{name}.t5.name",
                str(localized),
                merge=False,
            )
            local_t5_dimensions[str(localized)] = _t5_dimension(localized)
            continue
        raise RuntimeError(
            f"MusicGen conditioner {name!r} uses unsupported model {model_type!r}; "
            "only self-contained LUT and local T5 conditioners are allowed"
        )
    return local_t5_dimensions


def _allow_local_t5_conditioners(
    builders: _BuildersModule,
    conditioners: _ConditionersModule,
    local_t5_dimensions: Mapping[str, int],
) -> Callable[[], None]:
    if not local_t5_dimensions:
        return lambda: None
    t5_conditioner = conditioners.T5Conditioner
    builder_t5_conditioner = getattr(builders, "T5Conditioner", None)
    if builder_t5_conditioner is not t5_conditioner:
        raise RuntimeError("MusicGen AudioCraft builder uses an unexpected T5 conditioner")
    models = getattr(t5_conditioner, "MODELS", None)
    model_dimensions = getattr(t5_conditioner, "MODELS_DIMS", None)
    if not isinstance(models, list) or not isinstance(model_dimensions, dict):
        raise RuntimeError("MusicGen AudioCraft T5 conditioner has an unexpected shape")
    typed_models = cast(list[object], models)
    typed_dimensions = cast(dict[object, object], model_dimensions)
    original_models = list(typed_models)
    original_dimensions = dict(typed_dimensions)
    for model, dimension in local_t5_dimensions.items():
        if model not in typed_models:
            typed_models.append(model)
        typed_dimensions[model] = dimension

    def restore() -> None:
        typed_models[:] = original_models
        typed_dimensions.clear()
        typed_dimensions.update(original_dimensions)

    return restore


def _load_model(
    *,
    snapshot: Path,
    device: str | None,
    models: _ModelsModule,
    builders: _BuildersModule,
    conditioners: _ConditionersModule,
    omega_conf: _OmegaConfClass,
    torch: _TorchModule,
) -> _MusicGenModel:
    resolved_device = device or ("cuda" if torch.cuda.device_count() else "cpu")
    compression_package = _load_checkpoint_package(
        torch,
        snapshot / "compression_state_dict.bin",
        "compression",
    )
    lm_package = _load_checkpoint_package(torch, snapshot / "state_dict.bin", "language model")
    if "pretrained" in compression_package:
        raise RuntimeError(
            "MusicGen checkpoint must contain a self-contained compression model; "
            "pretrained references could trigger an unverified download"
        )

    compression_config = _package_config(compression_package, "xp.cfg", omega_conf)
    compression_config.device = resolved_device
    lm_config = _package_config(lm_package, "xp.cfg", omega_conf)
    lm_config.device = resolved_device
    lm_config.dtype = "float32" if resolved_device == "cpu" else "float16"
    missing = object()
    for key in (
        "conditioners.self_wav.chroma_stem.cache_path",
        "conditioners.args.merge_text_conditions_p",
        "conditioners.args.drop_desc_p",
    ):
        if omega_conf.select(lm_config, key, missing) is not missing:
            omega_conf.update(lm_config, key, None, merge=False)
    local_t5_dimensions = _preflight_conditioners(lm_config, snapshot, omega_conf)
    compression_state = _package_mapping(compression_package, "best_state")
    lm_state = _package_mapping(lm_package, "best_state")

    compression_model = builders.get_compression_model(compression_config)
    compression_model.load_state_dict(compression_state)
    compression_model.eval()
    restore_t5_conditioners = _allow_local_t5_conditioners(
        builders,
        conditioners,
        local_t5_dimensions,
    )
    try:
        lm = builders.get_lm_model(lm_config)
    finally:
        restore_t5_conditioners()
    lm.load_state_dict(lm_state)
    lm.eval()
    cast(Any, lm).cfg = lm_config
    return models.MusicGen(str(snapshot), compression_model, lm)


class AudioCraftRuntime:
    def availability_diagnostic(self) -> str | None:
        package_spec = importlib.util.find_spec("audiocraft")
        if package_spec is None:
            return (
                "AudioCraft is not installed; install the pinned optional MusicGen "
                "environment described in docs/spikes/musicgen.md"
            )
        if not _reviewed_build_installed(package_spec.origin):
            return (
                "the installed package is not the reviewed AudioCraft build; install version "
                f"{_AUDIOCRAFT_VERSION} from commit {_AUDIOCRAFT_COMMIT} as described in "
                "docs/spikes/musicgen.md"
            )
        return None

    def generate(
        self,
        *,
        checkpoint: Path,
        checkpoint_sha256: str,
        device: str | None,
        prompt: str,
        duration_s: float,
        seed: int | None,
        out: Path,
    ) -> GeneratedAudio:
        with (
            _INFERENCE_LOCK,
            TemporaryDirectory(prefix="beatforge-musicgen-") as temporary_directory,
        ):
            snapshot = Path(temporary_directory) / "checkpoint"
            shutil.copytree(checkpoint, snapshot, symlinks=True)
            if calculate_checkpoint_sha256(snapshot) != checkpoint_sha256:
                raise RuntimeError(
                    "MusicGen checkpoint snapshot digest does not match configuration"
                )

            torch = cast(_TorchModule, import_module("torch"))
            models = cast(_ModelsModule, import_module("audiocraft.models"))
            builders = cast(_BuildersModule, import_module("audiocraft.models.builders"))
            conditioners = cast(
                _ConditionersModule,
                import_module("audiocraft.modules.conditioners"),
            )
            omega_conf_module = cast(_OmegaConfModule, import_module("omegaconf"))
            audio = cast(_AudioModule, import_module("audiocraft.data.audio"))

            model = _load_model(
                snapshot=snapshot,
                device=device,
                models=models,
                builders=builders,
                conditioners=conditioners,
                omega_conf=omega_conf_module.OmegaConf,
                torch=torch,
            )
            if seed is not None:
                torch.manual_seed(seed)
            model.set_generation_params(duration=duration_s)
            waveform = model.generate([prompt], progress=False)[0]
            if len(waveform.shape) < 2:
                raise RuntimeError("MusicGen returned an invalid waveform shape")

            output_format = out.suffix.casefold().removeprefix(".")
            audio.audio_write(
                out,
                waveform.cpu(),
                model.sample_rate,
                add_suffix=False,
                format=output_format,
                loudness_compressor=True,
                strategy="loudness",
            )
            return GeneratedAudio(
                sample_rate=model.sample_rate,
                channels=waveform.shape[-2],
                frames=waveform.shape[-1],
            )
