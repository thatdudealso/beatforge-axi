from __future__ import annotations

import importlib.util
import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from typing import Protocol, cast

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


class _Config(Protocol):
    device: str
    dtype: str


class _BuildersModule(Protocol):
    def get_compression_model(self, config: _Config) -> _StatefulModel: ...

    def get_lm_model(self, config: _Config) -> _StatefulModel: ...


class _LoadersModule(Protocol):
    def load_compression_model_ckpt(self, checkpoint: Path) -> dict[str, object]: ...

    def load_lm_model_ckpt(self, checkpoint: Path) -> dict[str, object]: ...


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


def _reviewed_build_installed() -> bool:
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
    return (
        typed_vcs_info.get("vcs") == "git" and typed_vcs_info.get("commit_id") == _AUDIOCRAFT_COMMIT
    )


def _package_value(package: Mapping[str, object], key: str) -> object:
    try:
        return package[key]
    except KeyError as error:
        raise RuntimeError(f"MusicGen checkpoint package is missing {key}") from error


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


def _preflight_conditioners(
    config: _Config,
    snapshot: Path,
    omega_conf: _OmegaConfClass,
) -> None:
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
            continue
        raise RuntimeError(
            f"MusicGen conditioner {name!r} uses unsupported model {model_type!r}; "
            "only self-contained LUT and local T5 conditioners are allowed"
        )


def _load_model(
    *,
    snapshot: Path,
    device: str | None,
    models: _ModelsModule,
    builders: _BuildersModule,
    loaders: _LoadersModule,
    omega_conf: _OmegaConfClass,
    torch: _TorchModule,
) -> _MusicGenModel:
    resolved_device = device or ("cuda" if torch.cuda.device_count() else "cpu")
    compression_package = loaders.load_compression_model_ckpt(snapshot)
    lm_package = loaders.load_lm_model_ckpt(snapshot)
    if "pretrained" in compression_package:
        raise RuntimeError(
            "MusicGen checkpoint must contain a self-contained compression model; "
            "pretrained references could trigger an unverified download"
        )

    compression_config = omega_conf.create(_package_value(compression_package, "xp.cfg"))
    compression_config.device = resolved_device
    lm_config = omega_conf.create(_package_value(lm_package, "xp.cfg"))
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
    _preflight_conditioners(lm_config, snapshot, omega_conf)

    compression_model = builders.get_compression_model(compression_config)
    compression_model.load_state_dict(_package_value(compression_package, "best_state"))
    compression_model.eval()
    lm = builders.get_lm_model(lm_config)
    lm.load_state_dict(_package_value(lm_package, "best_state"))
    lm.eval()
    return models.MusicGen(str(snapshot), compression_model, lm)


class AudioCraftRuntime:
    def availability_diagnostic(self) -> str | None:
        if importlib.util.find_spec("audiocraft") is None:
            return (
                "AudioCraft is not installed; install the pinned optional MusicGen "
                "environment described in docs/spikes/musicgen.md"
            )
        if not _reviewed_build_installed():
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
        with TemporaryDirectory(prefix="beatforge-musicgen-") as temporary_directory:
            snapshot = Path(temporary_directory) / "checkpoint"
            shutil.copytree(checkpoint, snapshot, symlinks=True)
            if calculate_checkpoint_sha256(snapshot) != checkpoint_sha256:
                raise RuntimeError(
                    "MusicGen checkpoint snapshot digest does not match configuration"
                )

            torch = cast(_TorchModule, import_module("torch"))
            models = cast(_ModelsModule, import_module("audiocraft.models"))
            builders = cast(_BuildersModule, import_module("audiocraft.models.builders"))
            loaders = cast(_LoadersModule, import_module("audiocraft.models.loaders"))
            omega_conf_module = cast(_OmegaConfModule, import_module("omegaconf"))
            audio = cast(_AudioModule, import_module("audiocraft.data.audio"))

            with _INFERENCE_LOCK:
                model = _load_model(
                    snapshot=snapshot,
                    device=device,
                    models=models,
                    builders=builders,
                    loaders=loaders,
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
