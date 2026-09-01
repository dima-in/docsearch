"""Обход файлового дерева с учётом исключений из конфига."""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Iterator

from .config import Config


def _excluded_name(name: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, g) or fnmatch.fnmatch(name.lower(), g.lower())
               for g in globs)


def walk(root: str, cfg: Config) -> Iterator[Path]:
    """Все файлы под root, кроме отфильтрованных."""
    root_path = Path(root)
    for dirpath, dirnames, filenames in os.walk(root_path, onerror=lambda e: None):
        # правим dirnames на месте — так os.walk не заходит внутрь
        dirnames[:] = [
            d for d in dirnames
            if d.lower() not in cfg.exclude_dirs and not d.startswith("~$")
        ]
        for filename in filenames:
            if _excluded_name(filename, cfg.exclude_globs):
                continue
            yield Path(dirpath) / filename
