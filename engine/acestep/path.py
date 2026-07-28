from __future__ import annotations

import sys
from pathlib import Path


def ensure_project_root_on_path(project_root: Path) -> None:
    """Append the pinned ACE-Step checkout so ``import acestep`` works.

    The path is appended (not prepended) so BeatForge's ``cli`` package is not
    shadowed by ACE-Step's top-level ``cli.py``.
    """
    root = str(project_root.resolve())
    if root not in sys.path:
        sys.path.append(root)
