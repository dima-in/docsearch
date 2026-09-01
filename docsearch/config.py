"""Загрузка config.yaml."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


@dataclass
class Root:
    label: str
    path: str


@dataclass
class Config:
    roots: list[Root]
    db: str
    max_file_mb: int = 200
    max_text_chars: int = 400_000
    exclude_dirs: set[str] = field(default_factory=set)
    exclude_globs: list[str] = field(default_factory=list)

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024


def load(path: str | os.PathLike | None = None) -> Config:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with open(cfg_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    roots = [Root(label=r.get("label") or r["path"], path=r["path"])
             for r in raw.get("roots", [])]
    idx = raw.get("index", {}) or {}
    return Config(
        roots=roots,
        db=idx.get("db", "index.db"),
        max_file_mb=int(idx.get("max_file_mb", 200)),
        max_text_chars=int(idx.get("max_text_chars", 400_000)),
        # сравниваем имена папок без учёта регистра
        exclude_dirs={d.lower() for d in idx.get("exclude_dirs", [])},
        exclude_globs=list(idx.get("exclude_globs", [])),
    )
