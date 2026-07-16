from __future__ import annotations

import asyncio
import importlib.util
import re
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from engine.models import GenerateRequest, OperationContext, RemixRequest
from engine.yue import PINNED_UPSTREAM_COMMIT, CheckpointRole, YueCheckpoint, YueConfig
from engine.yue.models import YueRuntimeError
from engine.yue.runtime import YueSubprocessRuntime


def configured_runtime_yue(tmp_path: Path) -> YueConfig:
    upstream_root = tmp_path / "YuE"
    inference_dir = upstream_root / "inference"
    inference_dir.mkdir(parents=True)
    (inference_dir / "infer.py").write_text(
        """
from pathlib import Path
import argparse
import re

parser = argparse.ArgumentParser()
parser.add_argument("--lyrics_txt", required=True)
parser.add_argument("--output_dir", required=True)
parser.add_argument("--audio_prompt_path")
parser.add_argument("--cuda_idx")
parser.add_argument("--stage1_model")
parser.add_argument("--stage2_model")
parser.add_argument("--genre_txt")
parser.add_argument("--run_n_segments", type=int)
parser.add_argument("--seed")
parser.add_argument("--basic_model_config")
parser.add_argument("--resume_path")
parser.add_argument("--config_path")
parser.add_argument("--vocal_decoder_path")
parser.add_argument("--inst_decoder_path")
parser.add_argument("--use_audio_prompt", action="store_true")
args = parser.parse_args()

lyrics = Path(args.lyrics_txt).read_text(encoding="utf-8")
if len(re.findall(r"^\\[\\w+\\]", lyrics, flags=re.MULTILINE)) < 2:
    raise SystemExit("single lyric section would produce no upstream output")
output_dir = Path(args.output_dir)
output_dir.mkdir(parents=True, exist_ok=True)
existing = len(list(output_dir.glob("*.mp3")))
(output_dir / f"song-{existing}.mp3").write_bytes(b"ID3")
""",
        encoding="utf-8",
    )
    return YueConfig(
        upstream_root=upstream_root,
        upstream_commit=PINNED_UPSTREAM_COMMIT,
        checkpoints=tuple(
            YueCheckpoint(
                role=role,
                identity=role.value,
                location=str(tmp_path / role.value),
                sha256="a" * 64,
                provenance_url="https://example.test/checkpoint",
            )
            for role in CheckpointRole
        ),
    )


def test_dependency_probe_does_not_import_absent_optional_packages(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    looked_up: list[str] = []

    def missing(name: str) -> None:
        looked_up.append(name)
        return None

    monkeypatch.setattr(importlib.util, "find_spec", missing)
    runtime = YueSubprocessRuntime()
    config = YueConfig(
        upstream_root=tmp_path,
        upstream_commit=PINNED_UPSTREAM_COMMIT,
        checkpoints=tuple(
            YueCheckpoint(
                role=role,
                identity=role.value,
                location=str(tmp_path / role.value),
                sha256="a" * 64,
                provenance_url="https://example.test/checkpoint",
            )
            for role in CheckpointRole
        ),
    )

    environment = runtime.probe(config)

    assert set(environment.missing_dependencies) >= {"torch", "transformers", "flash_attn"}
    assert set(looked_up) >= {"torch", "transformers", "flash_attn"}
    assert environment.cuda_available is False


def test_generate_with_single_section_prompt_reaches_upstream_with_valid_lyrics(
    tmp_path: Path,
) -> None:
    runtime = YueSubprocessRuntime()
    request = GenerateRequest(
        prompt="[verse]\nSing beneath the stars",
        duration_s=30,
        out=tmp_path / "song.mp3",
    )

    result = asyncio.run(
        runtime.generate(
            configured_runtime_yue(tmp_path),
            request,
            OperationContext(job_id="generate-single", workspace=tmp_path),
        )
    )

    lyrics = (tmp_path / ".yue-generate-single" / "lyrics.txt").read_text(encoding="utf-8")
    assert lyrics.count("[") >= 2
    assert result.path == request.out
    assert request.out.read_bytes() == b"ID3"


def test_generate_with_unsupported_section_prompt_adds_upstream_section(
    tmp_path: Path,
) -> None:
    runtime = YueSubprocessRuntime()
    request = GenerateRequest(
        prompt="[pre-chorus]\nBuild tension\n\n[verse]\nRelease it",
        duration_s=30,
        out=tmp_path / "song.mp3",
    )

    result = asyncio.run(
        runtime.generate(
            configured_runtime_yue(tmp_path),
            request,
            OperationContext(job_id="generate-dashed-section", workspace=tmp_path),
        )
    )

    lyrics = (tmp_path / ".yue-generate-dashed-section" / "lyrics.txt").read_text(encoding="utf-8")
    assert len(re.findall(r"^\[\w+\]", lyrics, flags=re.MULTILINE)) >= 2
    assert result.path == request.out
    assert request.out.read_bytes() == b"ID3"


def test_remix_with_style_prompt_reaches_upstream_with_valid_lyrics(tmp_path: Path) -> None:
    runtime = YueSubprocessRuntime()
    audio_prompt = tmp_path / "reference.wav"
    audio_prompt.write_bytes(b"RIFF")
    request = RemixRequest(
        input_file=audio_prompt,
        style="dreamy synth pop",
        out=tmp_path / "remix.mp3",
    )

    result = asyncio.run(
        runtime.remix(
            configured_runtime_yue(tmp_path),
            request,
            OperationContext(job_id="remix-single", workspace=tmp_path),
        )
    )

    lyrics = (tmp_path / ".yue-remix-single" / "lyrics.txt").read_text(encoding="utf-8")
    assert lyrics.count("[") >= 2
    assert result.path == request.out
    assert request.out.read_bytes() == b"ID3"


def test_runtime_clears_adapter_owned_output_dir_before_each_run(tmp_path: Path) -> None:
    runtime = YueSubprocessRuntime()
    config = configured_runtime_yue(tmp_path)
    context = OperationContext(job_id="retry", workspace=tmp_path)
    request = GenerateRequest(prompt="lyrics", duration_s=30, out=tmp_path / "song.mp3")

    first = asyncio.run(runtime.generate(config, request, context))
    second = asyncio.run(runtime.generate(config, request, context))

    output_dir = tmp_path / ".yue-retry" / "output"
    assert first.path == request.out
    assert second.path == request.out
    assert [path.name for path in output_dir.glob("*.mp3")] == ["song-0.mp3"]


def test_runtime_rejects_non_mp3_output_before_spawning_upstream(tmp_path: Path) -> None:
    config = configured_runtime_yue(tmp_path)
    upstream_root = config.upstream_root
    assert upstream_root is not None
    (upstream_root / "inference" / "infer.py").write_text(
        "raise SystemExit('should not run')\n",
        encoding="utf-8",
    )

    with pytest.raises(YueRuntimeError, match=r"YuE only supports \.mp3 output"):
        asyncio.run(
            YueSubprocessRuntime().generate(
                config,
                GenerateRequest(prompt="lyrics", duration_s=30, out=tmp_path / "song.wav"),
                OperationContext(job_id="bad-format", workspace=tmp_path),
            )
        )
