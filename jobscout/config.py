"""Lê o .env e decide onde ficam os dados."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env_paths() -> list[Path]:
    paths = [Path.cwd() / ".env", ROOT / ".env"]
    if getattr(sys, "frozen", False):
        paths.insert(0, Path(sys.executable).resolve().parent / ".env")
    unique: list[Path] = []
    for path in paths:
        if path not in unique:
            unique.append(path)
    return unique


@lru_cache(maxsize=1)
def _file_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in _env_paths():
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return values


def setting(name: str, default: str = "") -> str:
    """A variável de ambiente do sistema ganha do .env."""
    value = os.environ.get(name)
    if value is None:
        value = _file_values().get(name, "")
    return value.strip() or default


def flag(name: str) -> bool:
    return setting(name).lower() in {"1", "sim", "true", "on", "yes"}


def data_dir() -> Path:
    configured = setting("JOBSCOUT_DATA_DIR")
    folder = Path(configured).expanduser() if configured else Path.home() / ".jobscout"
    folder.mkdir(parents=True, exist_ok=True)
    return folder
