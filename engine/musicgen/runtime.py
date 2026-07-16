from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast


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


class _MusicGenClass(Protocol):
    def get_pretrained(self, name: str, device: str | None = None) -> _MusicGenModel: ...


class _ModelsModule(Protocol):
    MusicGen: _MusicGenClass


class _LoadersModule(Protocol):
    def load_compression_model_ckpt(self, checkpoint: Path) -> dict[str, object]: ...


class _TorchModule(Protocol):
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


class AudioCraftRuntime:
    def availability_diagnostic(self) -> str | None:
        if importlib.util.find_spec("audiocraft") is None:
            return (
                "AudioCraft is not installed; install the pinned optional MusicGen "
                "environment described in docs/spikes/musicgen.md"
            )
        return None

    def generate(
        self,
        *,
        checkpoint: Path,
        device: str | None,
        prompt: str,
        duration_s: float,
        seed: int | None,
        out: Path,
    ) -> GeneratedAudio:
        torch = cast(_TorchModule, import_module("torch"))
        models = cast(_ModelsModule, import_module("audiocraft.models"))
        loaders = cast(_LoadersModule, import_module("audiocraft.models.loaders"))
        audio = cast(_AudioModule, import_module("audiocraft.data.audio"))

        compression_package = loaders.load_compression_model_ckpt(checkpoint)
        if "pretrained" in compression_package:
            raise RuntimeError(
                "MusicGen checkpoint must contain a self-contained compression model; "
                "pretrained references could trigger an unverified download"
            )

        if seed is not None:
            torch.manual_seed(seed)
        model = models.MusicGen.get_pretrained(str(checkpoint), device=device)
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
