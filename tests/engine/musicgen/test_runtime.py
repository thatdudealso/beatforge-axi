from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Self

import pytest

from engine.musicgen.runtime import AudioCraftRuntime


class FakeWaveform:
    shape = (1, 48_000)

    def cpu(self) -> Self:
        return self


class FakeBatch:
    def __getitem__(self, index: int) -> FakeWaveform:
        assert index == 0
        return FakeWaveform()


class FakeMusicGenModel:
    sample_rate = 32_000

    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def set_generation_params(self, *, duration: float) -> None:
        self.calls.append(("set_generation_params", duration))

    def generate(self, prompts: list[str], *, progress: bool) -> FakeBatch:
        self.calls.append(("generate", (prompts, progress)))
        return FakeBatch()


def _install_fake_upstream(
    monkeypatch: pytest.MonkeyPatch,
    out_bytes: bytes = b"wave file",
    compression_package: dict[str, object] | None = None,
) -> list[tuple[str, object]]:
    calls: list[tuple[str, object]] = []
    model = FakeMusicGenModel(calls)

    class FakeMusicGen:
        @staticmethod
        def get_pretrained(name: str, device: str | None = None) -> FakeMusicGenModel:
            calls.append(("get_pretrained", (name, device)))
            return model

    def load_compression_model_ckpt(checkpoint: Path) -> dict[str, object]:
        calls.append(("inspect_compression", checkpoint))
        return compression_package or {"best_state": {}, "xp.cfg": "config"}

    def audio_write(
        out: Path,
        waveform: FakeWaveform,
        sample_rate: int,
        **kwargs: Any,
    ) -> Path:
        calls.append(("audio_write", (out, waveform, sample_rate, kwargs)))
        out.write_bytes(out_bytes)
        return out

    def manual_seed(seed: int) -> None:
        calls.append(("manual_seed", seed))

    modules = {
        "torch": ModuleType("torch"),
        "audiocraft": ModuleType("audiocraft"),
        "audiocraft.models": ModuleType("audiocraft.models"),
        "audiocraft.models.loaders": ModuleType("audiocraft.models.loaders"),
        "audiocraft.data": ModuleType("audiocraft.data"),
        "audiocraft.data.audio": ModuleType("audiocraft.data.audio"),
    }
    modules["torch"].manual_seed = manual_seed  # type: ignore[attr-defined]
    modules["audiocraft.models"].MusicGen = FakeMusicGen  # type: ignore[attr-defined]
    modules["audiocraft.models.loaders"].load_compression_model_ckpt = (  # type: ignore[attr-defined]
        load_compression_model_ckpt
    )
    modules["audiocraft.data.audio"].audio_write = audio_write  # type: ignore[attr-defined]
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return calls


def test_runtime_reports_missing_optional_dependency_without_importing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_spec(name: str) -> None:
        return None

    monkeypatch.setattr(importlib.util, "find_spec", missing_spec)

    diagnostic = AudioCraftRuntime().availability_diagnostic()

    assert diagnostic is not None
    assert "AudioCraft is not installed" in diagnostic


def test_runtime_uses_pinned_local_checkpoint_generation_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_fake_upstream(monkeypatch)
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    out = tmp_path / "result.wav"

    generated = AudioCraftRuntime().generate(
        checkpoint=checkpoint,
        device="cuda",
        prompt="warm analog synth",
        duration_s=1.5,
        seed=42,
        out=out,
    )

    assert out.read_bytes() == b"wave file"
    assert generated.sample_rate == 32_000
    assert generated.channels == 1
    assert generated.frames == 48_000
    assert calls[:4] == [
        ("inspect_compression", checkpoint),
        ("manual_seed", 42),
        ("get_pretrained", (str(checkpoint), "cuda")),
        ("set_generation_params", 1.5),
    ]
    assert calls[4] == ("generate", (["warm analog synth"], False))
    write_call = calls[5]
    assert write_call[0] == "audio_write"
    write_args = write_call[1]
    assert isinstance(write_args, tuple)
    assert write_args[0] == out
    assert write_args[2] == 32_000
    assert write_args[3] == {
        "add_suffix": False,
        "format": "wav",
        "loudness_compressor": True,
        "strategy": "loudness",
    }


def test_runtime_rejects_compression_reference_before_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_fake_upstream(
        monkeypatch,
        compression_package={"pretrained": "facebook/encodec_32khz"},
    )
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()

    with pytest.raises(RuntimeError, match="self-contained"):
        AudioCraftRuntime().generate(
            checkpoint=checkpoint,
            device=None,
            prompt="ambient",
            duration_s=1,
            seed=None,
            out=tmp_path / "out.wav",
        )

    assert calls == [("inspect_compression", checkpoint)]
