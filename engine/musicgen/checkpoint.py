from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol


class _Hasher(Protocol):
    def update(self, data: bytes, /) -> None: ...

    def hexdigest(self) -> str: ...


def _hash_file(hasher: _Hasher, path: Path) -> None:
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            hasher.update(chunk)


def checkpoint_sha256(checkpoint: Path) -> str:
    """Hash a checkpoint file or a deterministic manifest of a checkpoint directory."""
    checkpoint = checkpoint.resolve()
    if checkpoint.is_file():
        hasher = hashlib.sha256()
        _hash_file(hasher, checkpoint)
        return hasher.hexdigest()
    if not checkpoint.is_dir():
        raise FileNotFoundError(checkpoint)

    hasher = hashlib.sha256()
    files = sorted(path for path in checkpoint.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(checkpoint).as_posix().encode()
        hasher.update(len(relative).to_bytes(8, "big"))
        hasher.update(relative)
        hasher.update(path.stat().st_size.to_bytes(8, "big"))
        _hash_file(hasher, path)
    return hasher.hexdigest()
