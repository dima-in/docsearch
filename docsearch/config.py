"""Загрузка config.yaml."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


BACKSLASH = chr(92)

# Служебные папки, которые не должны попадать в индекс никогда — их
# исключаем независимо от конфига. #recycle и @eaDir создаёт Synology:
# это корзина и кэш эскизов; документы из корзины удалены сознательно,
# и находить их в поиске никто не должен.
DEFAULT_EXCLUDE_DIRS = {
    "#recycle",
    "#snapshot",
    "@eadir",
    ".@__thumb",
    "$recycle.bin",
    "system volume information",
    ".git",
}


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

    def __post_init__(self) -> None:
        # служебные папки исключаются всегда, как бы ни собрали Config
        self.exclude_dirs = DEFAULT_EXCLUDE_DIRS | {
            d.lower() for d in self.exclude_dirs
        }

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024


def load(path: str | os.PathLike | None = None) -> Config:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with open(cfg_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    base = cfg_path.resolve().parent

    def resolve(value: str) -> str:
        text = str(value).strip()
        # из адресной строки проводника путь копируется с обратными
        # слэшами: \\server\share. Приводим к прямым, иначе Path не
        # опознаёт UNC и такой путь молча приклеится к папке проекта
        if text.startswith("//") or text.startswith(BACKSLASH * 2):
            return str(Path(text.replace(BACKSLASH, "/")))
        path = Path(text)
        return str(path if path.is_absolute() else (base / path).resolve())

    roots = [Root(label=r.get("label") or r["path"], path=resolve(r["path"]))
             for r in raw.get("roots", [])]
    idx = raw.get("index", {}) or {}
    # относительный путь к базе считаем от папки конфига, а не от текущей
    # директории — иначе индекс будет появляться там, откуда запустили
    return Config(
        roots=roots,
        db=resolve(idx.get("db", "index.db")),
        max_file_mb=int(idx.get("max_file_mb", 200)),
        max_text_chars=int(idx.get("max_text_chars", 400_000)),
        # сравниваем имена папок без учёта регистра
        exclude_dirs=set(idx.get("exclude_dirs", [])),
        exclude_globs=list(idx.get("exclude_globs", [])),
    )
