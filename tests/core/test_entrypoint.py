from __future__ import annotations

import sys
from pathlib import Path

from core.entrypoint import prefer_beatforge_cli_package


def test_prefer_beatforge_cli_demotes_acestep_cli_py(tmp_path: Path) -> None:
    ace_root = tmp_path / "ACE-Step-1.5"
    ace_root.mkdir()
    (ace_root / "cli.py").write_text("# upstream cli\n", encoding="utf-8")
    forge_root = tmp_path / "beatforge"
    (forge_root / "cli").mkdir(parents=True)
    (forge_root / "cli" / "__init__.py").write_text("", encoding="utf-8")

    original = list(sys.path)
    try:
        sys.path[:] = [str(ace_root), str(forge_root)]
        prefer_beatforge_cli_package()
        assert sys.path.index(str(forge_root)) < sys.path.index(str(ace_root))
    finally:
        sys.path[:] = original
