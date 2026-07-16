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
from types import ModuleType, SimpleNamespace
from typing import Any, ClassVar, Self, TypeGuard, cast

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


def _parse_simple_yaml_mapping(text: str) -> dict[str, object]:
    root: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object]]] = [(-1, root)]
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        key, separator, raw_value = raw_line.strip().partition(":")
        assert separator == ":"
        while indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        value = raw_value.strip()
        if not value:
            nested: dict[str, object] = {}
            parent[key] = nested
            stack.append((indent, nested))
            continue
        parent[key] = int(value) if value.isdecimal() else value
    return root


class FakeOmegaConf:
    @staticmethod
    def create(value: object) -> FakeConfig:
        if isinstance(value, str):
            return FakeConfig(_parse_simple_yaml_mapping(value))
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
        if isinstance(value, FakeConfig):
            return deepcopy(value.values)
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
    on_lm_build: Callable[[FakeConfig, ModuleType], None] | None = None,
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
                    "lut": {"n_bins": 256, "tokenizer": "noop"},
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
            calls.append(("construct_lm_cfg", getattr(lm, "cfg", None)))
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
        if on_lm_build is not None:
            on_lm_build(config, modules["audiocraft.models.builders"])
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

    def torch_load(path: Path, *, map_location: str, weights_only: bool) -> dict[str, object]:
        calls.append(("torch_load", (path.name, map_location, weights_only)))
        if path.name == "compression_state_dict.bin":
            return compression_package
        if path.name == "state_dict.bin":
            if on_lm_load is not None:
                on_lm_load(path.parent)
            return lm_package
        raise AssertionError(path)

    class RejectingRemoteT5Conditioner:
        MODELS: ClassVar[list[str]] = ["t5-base"]
        MODELS_DIMS: ClassVar[dict[str, int]] = {"t5-base": 768}

        def __init__(self, name: str, **kwargs: object) -> None:
            if name not in self.MODELS:
                raise AssertionError("remote T5 conditioner was constructed")
            if Path(name).is_absolute():
                calls.append(("local_t5_conditioner", name))
            else:
                calls.append(("remote_t5_conditioner", name))

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
        "audiocraft.modules": ModuleType("audiocraft.modules"),
        "audiocraft.modules.conditioners": ModuleType("audiocraft.modules.conditioners"),
        "audiocraft.data": ModuleType("audiocraft.data"),
        "audiocraft.data.audio": ModuleType("audiocraft.data.audio"),
    }
    modules["torch"].manual_seed = manual_seed  # type: ignore[attr-defined]
    modules["torch"].load = torch_load  # type: ignore[attr-defined]
    modules["torch"].cuda = FakeCuda()  # type: ignore[attr-defined]
    modules["omegaconf"].OmegaConf = FakeOmegaConf  # type: ignore[attr-defined]
    modules["audiocraft.models"].MusicGen = FakeMusicGen  # type: ignore[attr-defined]
    modules["audiocraft.modules.conditioners"].T5Conditioner = (  # type: ignore[attr-defined]
        RejectingRemoteT5Conditioner
    )
    modules["audiocraft.models.builders"].T5Conditioner = (  # type: ignore[attr-defined]
        RejectingRemoteT5Conditioner
    )
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
    def __init__(self, version: str, commit_id: str | None, root: Path) -> None:
        self.version = version
        self.commit_id = commit_id
        self.root = root

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

    def locate_file(self, path: str) -> Path:
        return self.root / path


def _installed_distribution(
    monkeypatch: pytest.MonkeyPatch,
    *,
    version: str = "1.4.0a2",
    commit_id: str | None = _REVIEWED_COMMIT,
    package_origin: Path | None = None,
    distribution_root: Path | None = None,
) -> None:
    root = distribution_root or Path("/opt/reviewed-audiocraft")
    origin = package_origin or root / "audiocraft" / "__init__.py"

    def installed_spec(name: str) -> object:
        return SimpleNamespace(origin=str(origin))

    def find_distribution(name: str) -> FakeDistribution:
        return FakeDistribution(version, commit_id, root)

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


def test_runtime_rejects_shadowed_audiocraft_import_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _installed_distribution(
        monkeypatch,
        package_origin=Path("/tmp/shadow/audiocraft/__init__.py"),
        distribution_root=Path("/opt/reviewed-audiocraft"),
    )

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
    construct_lm_cfg = next(call for call in calls if call[0] == "construct_lm_cfg")
    assert isinstance(construct_lm_cfg[1], FakeConfig)
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


def test_runtime_loads_snapshot_packages_with_safe_torch_deserialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = _checkpoint(tmp_path)
    calls = _install_fake_upstream(monkeypatch)

    AudioCraftRuntime().generate(
        checkpoint=checkpoint,
        checkpoint_sha256=checkpoint_sha256(checkpoint),
        device=None,
        prompt="ambient",
        duration_s=1,
        seed=None,
        out=tmp_path / "out.wav",
    )

    assert ("torch_load", ("compression_state_dict.bin", "cpu", True)) in calls
    assert ("torch_load", ("state_dict.bin", "cpu", True)) in calls
    assert not any(call[0].startswith("load_") and "package" in call[0] for call in calls)


def test_runtime_accepts_exported_xp_cfg_yaml_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = _checkpoint(tmp_path)
    calls = _install_fake_upstream(
        monkeypatch,
        compression_package={
            "best_state": {"compression": "state"},
            "xp.cfg": "compression_model: encodec\n",
        },
        lm_package={
            "best_state": {"lm": "state"},
            "xp.cfg": "\n".join(
                [
                    "conditioners:",
                    "  description:",
                    "    model: lut",
                    "    lut:",
                    "      n_bins: 256",
                    "      tokenizer: noop",
                ]
            ),
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

    compression_call = next(call for call in calls if call[0] == "build_compression_model")
    lm_call = next(call for call in calls if call[0] == "build_lm_model")
    assert isinstance(compression_call[1], FakeConfig)
    assert compression_call[1].values == {"compression_model": "encodec"}
    assert isinstance(lm_call[1], FakeConfig)
    assert FakeOmegaConf.select(lm_call[1], "conditioners.description.lut.tokenizer") == "noop"


def test_runtime_rejects_unsafe_checkpoint_package_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = _checkpoint(tmp_path)
    calls = _install_fake_upstream(monkeypatch, lm_package={"xp.cfg": {}})

    with pytest.raises(RuntimeError, match="best_state"):
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


def test_runtime_rejects_lut_conditioners_with_downloadable_tokenizers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_fake_upstream(
        monkeypatch,
        lm_package={
            "best_state": {},
            "xp.cfg": {
                "conditioners": {
                    "description": {
                        "model": "lut",
                        "lut": {"n_bins": 256, "tokenizer": "whitespace"},
                    }
                }
            },
        },
    )
    checkpoint = _checkpoint(tmp_path)

    with pytest.raises(RuntimeError, match="noop"):
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
    (auxiliary / "config.json").write_text('{"d_model": 768}')

    def build_t5(config: FakeConfig, builders: ModuleType) -> None:
        name = FakeOmegaConf.select(config, "conditioners.description.t5.name")
        assert isinstance(name, str)
        builders.T5Conditioner(  # type: ignore[attr-defined]
            name=name,
            output_dim=32,
            finetune=False,
            device=config.device,
        )

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
        on_lm_build=build_t5,
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
    assert ("local_t5_conditioner", name) in calls


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


def test_runtime_serializes_snapshot_creation_with_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = _checkpoint(tmp_path)
    first_started = Event()
    release_first = Event()
    copied_snapshots: list[Path] = []
    original_copytree = runtime_module.shutil.copytree

    def block_first_request(prompts: list[str]) -> None:
        if prompts == ["first"]:
            first_started.set()
            assert release_first.wait(timeout=2)

    def copytree(source: Path, destination: Path, *, symlinks: bool) -> Path:
        copied_snapshots.append(destination)
        return original_copytree(source, destination, symlinks=symlinks)

    monkeypatch.setattr(runtime_module.shutil, "copytree", copytree)
    _install_fake_upstream(monkeypatch, on_generate=block_first_request)
    runtime = AudioCraftRuntime()
    digest = checkpoint_sha256(checkpoint)

    def generate(prompt: str) -> None:
        runtime.generate(
            checkpoint=checkpoint,
            checkpoint_sha256=digest,
            device=None,
            prompt=prompt,
            duration_s=1,
            seed=None,
            out=tmp_path / f"{prompt}.wav",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(generate, "first")
        assert first_started.wait(timeout=2)
        second = executor.submit(generate, "second")
        time.sleep(0.05)
        assert len(copied_snapshots) == 1
        release_first.set()
        first.result(timeout=2)
        second.result(timeout=2)
