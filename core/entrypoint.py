from __future__ import annotations

import sys
from pathlib import Path


def prefer_beatforge_cli_package() -> None:
    """Demote checkouts that ship a top-level ``cli.py`` (e.g. ACE-Step).

    Editable ACE-Step installs put their project root early on ``sys.path``.
    That root contains ``cli.py``, which otherwise shadows BeatForge's ``cli``
    package and breaks the ``beatforge-axi`` console script.
    """
    demote: list[str] = []
    for entry in sys.path:
        root = Path(entry)
        if (root / "cli.py").is_file() and not (root / "cli" / "__init__.py").is_file():
            demote.append(entry)
    for entry in demote:
        while entry in sys.path:
            sys.path.remove(entry)
        sys.path.append(entry)


def main() -> None:
    prefer_beatforge_cli_package()
    from cli.app import main as cli_main

    cli_main()
