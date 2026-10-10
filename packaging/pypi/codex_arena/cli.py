"""Dispatch the installed console command to its bundled Arena CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        print("Codex Arena requires Python 3.11 or newer.", file=sys.stderr)
        return 2

    script = Path(__file__).resolve().parent / "payload" / "scripts" / "arena.py"
    if not script.is_file():
        print(f"Codex Arena payload is missing: {script}", file=sys.stderr)
        return 2

    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        return subprocess.run([sys.executable, str(script), *arguments], check=False).returncode
    except OSError as exc:
        print(f"Could not start Codex Arena: {exc}", file=sys.stderr)
        return 2
