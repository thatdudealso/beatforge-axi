from __future__ import annotations

import importlib.util
import json
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Event
from types import ModuleType
from typing import Any, Self, TypeGuard, cast

import pytest

import engine.musicgen.runtime as runtime_module
from engine.musicgen import checkpoint_sha256
from engine.musicgen.runtime import AudioCraftRuntime

_REVIEWED_COMMIT = "896ec7c47f5e5d1e5aa1e4b260c4405328bf009d"


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

    def __init__(
        self,
        calls: list[tuple[str, object]],
        on_generate: Callable[[list[str]], None] | None,
    ) -> None:
        self.calls = calls
        self.on_generate = on_generate

    def set_generation_params(self, *, duration: float) -> None:
        self.calls.append(("set_generation_params", duration))

    def generate(self, prompts: list[str], *, progress: bool) -> FakeBatch:
        self.calls.append(("generate", (prompts, progress)))
        if self.on_generate is not None:
            self.on_generate(prompts)
        return FakeBatch()


class FakeNativeModel:
    def __init__(self, kind: str, calls: list[tuple[str, object]]) -> None:
        self.kind = kind
        self.calls = calls

    def load_state_dict(self, state: object) -> None:
        self.calls.append((f"load_{self.kind}_state", state))

    def eval(self) -> None:
        self.calls.append((f"eval_{self.kind}", None))


class FakeConfig:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = deepcopy(values)
        self.device = ""
        self.dtype = ""


def _is_object_dict(value: object) -> TypeGuard[dict[str, object]]:
    if not isinstance(value, dict):
        return False
    mapping = cast(dict[object, object], value)
    return all(isinstance(key, str) for key in mapping)


class FakeOmegaConf:
    @staticmethod
    def create(value: object) -> FakeConfig:
        assert isinstance(value, dict)
        return FakeConfig(cast(dict[str, object], value))

    @staticmethod
    def select(config: FakeConfig, key: str, default: object = None) -> object:
        value: object = config.values
        for part in key.split("."):
            if not _is_object_dict(value) or part not in value:
                return default
            value = value[part]
        return value

    @staticmethod
    def update(config: FakeConfig, key: str, value: object, *, merge: bool) -> None:
        assert merge is False
        target = config.values
        parts = key.split(".")
        for part in parts[:-1]:
            nested = target[part]
            assert isinstance(nested, dict)
            target = cast(dict[str, object], nested)
        target[parts[-1]] = value

    @staticmethod
    def to_container(value: object, *, resolve: bool) -> object:
        assert resolve is True
        return deepcopy(value)


def _checkpoint(tmp_path: Path) -> Path:
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "state_dict.bin").write_bytes(b"language model")
    (checkpoint / "compression_state_dict.bin").write_bytes(b"audio tokenizer")
    return checkpoint


def _install_fake_upstream(
    monkeypatch: pytest.MonkeyPatch,
    *,
    out_bytes: bytes = b"wave file",
    compression_package: dict[str, object] | None = None,
    lm_package: dict[str, object] | None = None,
    on_lm_load: Callable[[Path], None] | None = None,
    on_generate: Callable[[list[str]], None] | None = None,
) -> list[tuple[str, object]]:
    calls: list[tuple[str, object]] = []
    generated_model = FakeMusicGenModel(calls, on_generate)
    compression_package = compression_package or {
        "best_state": {"compression": "state"},
        "xp.cfg": {"compression_model": "encodec"},
    }
    lm_package = lm_package or {
        "best_state": {"lm": "state"},
        "xp.cfg": {
            "conditioners": {
                "description": {
                    "model": "lut",
                    "lut": {"n_bins": 256},
                }
            }
        },
    }

    class FakeMusicGen:
        def __new__(
            cls,
            name: str,
            compression_model: FakeNativeModel,
            lm: FakeNativeModel,
        ) -> FakeMusicGenModel:
            calls.append(("construct_musicgen", (name, compression_model.kind, lm.kind)))
            return generated_model

    def load_compression_model_ckpt(checkpoint: Path) -> dict[str, object]:
        calls.append(("load_compression_package", checkpoint))
        return compression_package

    def load_lm_model_ckpt(checkpoint: Path) -> dict[str, object]:
        calls.append(("load_lm_package", checkpoint))
        if on_lm_load is not None:
            on_lm_load(checkpoint)
        return lm_package

    def get_compression_model(config: FakeConfig) -> FakeNativeModel:
        calls.append(("build_compression_model", config))
        return FakeNativeModel("compression", calls)

    def get_lm_model(config: FakeConfig) -> FakeNativeModel:
        calls.append(("build_lm_model", config))
        return FakeNativeModel("lm", calls)

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

    class FakeCuda:
        @staticmethod
        def device_count() -> int:
            return 0

    modules = {
        "torch": ModuleType("torch"),
        "omegaconf": ModuleType("omegaconf"),
        "audiocraft": ModuleType("audiocraft"),
        "audiocraft.models": ModuleType("audiocraft.models"),
        "audiocraft.models.builders": ModuleType("audiocraft.models.builders"),
        "audiocraft.models.loaders": ModuleType("audiocraft.models.loaders"),
        "audiocraft.data": ModuleType("audiocraft.data"),
        "audiocraft.data.audio": ModuleType("audiocraft.data.audio"),
    }
    modules["torch"].manual_seed = manual_seed  # type: ignore[attr-defined]
    modules["torch"].cuda = FakeCuda()  # type: ignore[attr-defined]
    modules["omegaconf"].OmegaConf = FakeOmegaConf  # type: ignore[attr-defined]
    modules["audiocraft.models"].MusicGen = FakeMusicGen  # type: ignore[attr-defined]
    modules["audiocraft.models.builders"].get_compression_model = (  # type: ignore[attr-defined]
        get_compression_model
    )
    modules["audiocraft.models.builders"].get_lm_model = get_lm_model  # type: ignore[attr-defined]
    modules["audiocraft.models.loaders"].load_compression_model_ckpt = (  # type: ignore[attr-defined]
        load_compression_model_ckpt
    )
    modules["audiocraft.models.loaders"].load_lm_model_ckpt = (  # type: ignore[attr-defined]
        load_lm_model_ckpt
    )
    modules["audiocraft.data.audio"].audio_write = audio_write  # type: ignore[attr-defined]
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return calls


class FakeDistribution:
    def __init__(self, version: str, commit_id: str | None) -> None:
        self.version = version
        self.commit_id = commit_id

    def read_text(self, filename: str) -> str | None:
        assert filename == "direct_url.json"
        if self.commit_id is None:
            return None
        return json.dumps(
            {
                "url": "https://github.com/facebookresearch/audiocraft.git",
                "vcs_info": {"commit_id": self.commit_id, "vcs": "git"},
            }
        )


def _installed_distribution(
    monkeypatch: pytest.MonkeyPatch,
    *,
    version: str = "1.4.0a2",
    commit_id: str | None = _REVIEWED_COMMIT,
) -> None:
    def installed_spec(name: str) -> object:
        return object()

    def find_distribution(name: str) -> FakeDistribution:
        return FakeDistribution(version, commit_id)

    monkeypatch.setattr(importlib.util, "find_spec", installed_spec)
    monkeypatch.setattr(
        runtime_module,
        "distribution",
        find_distribution,
        raising=False,
    )


def test_runtime_reports_missing_optional_dependency_without_importing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_spec(name: str) -> None:
        return None

    monkeypatch.setattr(importlib.util, "find_spec", missing_spec)

    diagnostic = AudioCraftRuntime().availability_diagnostic()

    assert diagnostic is not None
    assert "AudioCraft is not installed" in diagnostic


@pytest.mark.parametrize(
    ("version", "commit_id"),
    [
        ("1.3.0", _REVIEWED_COMMIT),
        ("1.4.0a2", None),
        ("1.4.0a2", "0" * 40),
    ],
)
def test_runtime_rejects_unreviewed_audiocraft_builds(
    monkeypatch: pytest.MonkeyPatch,
    version: str,
    commit_id: str | None,
) -> None:
    _installed_distribution(monkeypatch, version=version, commit_id=commit_id)

    diagnostic = AudioCraftRuntime().availability_diagnostic()

    assert diagnostic is not None
    assert "reviewed AudioCraft build" in diagnostic


def test_runtime_accepts_exact_reviewed_audiocraft_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _installed_distribution(monkeypatch)

    assert AudioCraftRuntime().availability_diagnostic() is None


def test_runtime_uses_verified_snapshot_and_local_checkpoint_generation_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = _checkpoint(tmp_path)
    observed_loader_paths: list[Path] = []
    observed_snapshot_bytes: list[bytes] = []

    def mutate_source(snapshot: Path) -> None:
        observed_loader_paths.append(snapshot)
        observed_snapshot_bytes.append((snapshot / "state_dict.bin").read_bytes())
        (checkpoint / "state_dict.bin").write_bytes(b"replaced after validation")

    calls = _install_fake_upstream(monkeypatch, on_lm_load=mutate_source)
    out = tmp_path / "result.wav"

    generated = AudioCraftRuntime().generate(
        checkpoint=checkpoint,
        checkpoint_sha256=checkpoint_sha256(checkpoint),
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
    assert observed_loader_paths[0] != checkpoint
    assert observed_loader_paths[0].parent != checkpoint.parent
    assert observed_snapshot_bytes == [b"language model"]
    assert ("manual_seed", 42) in calls
    assert ("set_generation_params", 1.5) in calls
    assert ("generate", (["warm analog synth"], False)) in calls
    write_call = next(call for call in calls if call[0] == "audio_write")
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


def test_runtime_rejects_snapshot_digest_mismatch_before_importing_upstream(
    tmp_path: Path,
) -> None:
    checkpoint = _checkpoint(tmp_path)

    with pytest.raises(RuntimeError, match="digest"):
        AudioCraftRuntime().generate(
            checkpoint=checkpoint,
            checkpoint_sha256="0" * 64,
            device=None,
            prompt="ambient",
            duration_s=1,
            seed=None,
            out=tmp_path / "out.wav",
        )

    assert "torch" not in sys.modules
    assert "audiocraft.models" not in sys.modules


def test_runtime_rejects_compression_reference_before_model_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_fake_upstream(
        monkeypatch,
        compression_package={"pretrained": "facebook/encodec_32khz"},
    )
    checkpoint = _checkpoint(tmp_path)

    with pytest.raises(RuntimeError, match="self-contained"):
        AudioCraftRuntime().generate(
            checkpoint=checkpoint,
            checkpoint_sha256=checkpoint_sha256(checkpoint),
            device=None,
            prompt="ambient",
            duration_s=1,
            seed=None,
            out=tmp_path / "out.wav",
        )

    assert not any(call[0].startswith("build_") for call in calls)


def test_runtime_rejects_remote_t5_conditioner_before_model_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_fake_upstream(
        monkeypatch,
        lm_package={
            "best_state": {},
            "xp.cfg": {"conditioners": {"description": {"model": "t5", "t5": {"name": "t5-base"}}}},
        },
    )
    checkpoint = _checkpoint(tmp_path)

    with pytest.raises(RuntimeError, match="local T5 auxiliary asset"):
        AudioCraftRuntime().generate(
            checkpoint=checkpoint,
            checkpoint_sha256=checkpoint_sha256(checkpoint),
            device=None,
            prompt="ambient",
            duration_s=1,
            seed=None,
            out=tmp_path / "out.wav",
        )

    assert not any(call[0].startswith("build_") for call in calls)


def test_runtime_localizes_verified_t5_conditioner_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = _checkpoint(tmp_path)
    auxiliary = checkpoint / "aux" / "t5-base"
    auxiliary.mkdir(parents=True)
    (auxiliary / "config.json").write_text("{}")
    calls = _install_fake_upstream(
        monkeypatch,
        lm_package={
            "best_state": {},
            "xp.cfg": {
                "conditioners": {
                    "description": {
                        "model": "t5",
                        "t5": {"name": "aux/t5-base"},
                    }
                }
            },
        },
    )

    AudioCraftRuntime().generate(
        checkpoint=checkpoint,
        checkpoint_sha256=checkpoint_sha256(checkpoint),
        device=None,
        prompt="ambient",
        duration_s=1,
        seed=None,
        out=tmp_path / "out.wav",
    )

    build_call = next(call for call in calls if call[0] == "build_lm_model")
    config = build_call[1]
    assert isinstance(config, FakeConfig)
    name = FakeOmegaConf.select(config, "conditioners.description.t5.name")
    assert isinstance(name, str)
    localized = Path(name)
    assert localized.is_absolute()
    assert localized.name == "t5-base"
    assert localized.parent.name == "aux"


def test_runtime_serializes_seed_and_inference_across_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = _checkpoint(tmp_path)
    first_started = Event()
    release_first = Event()

    def block_first_request(prompts: list[str]) -> None:
        if prompts == ["first"]:
            first_started.set()
            assert release_first.wait(timeout=2)

    calls = _install_fake_upstream(monkeypatch, on_generate=block_first_request)
    runtime = AudioCraftRuntime()
    digest = checkpoint_sha256(checkpoint)

    def generate(prompt: str, seed: int) -> None:
        runtime.generate(
            checkpoint=checkpoint,
            checkpoint_sha256=digest,
            device=None,
            prompt=prompt,
            duration_s=1,
            seed=seed,
            out=tmp_path / f"{prompt}.wav",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(generate, "first", 1)
        assert first_started.wait(timeout=2)
        second = executor.submit(generate, "second", 2)
        time.sleep(0.05)
        assert ("manual_seed", 2) not in calls
        release_first.set()
        first.result(timeout=2)
        second.result(timeout=2)

    assert calls.index(("manual_seed", 1)) < calls.index(("generate", (["first"], False)))
    assert calls.index(("generate", (["first"], False))) < calls.index(("manual_seed", 2))
