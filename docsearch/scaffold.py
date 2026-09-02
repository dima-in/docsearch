"""Создание конфига для нового архива.

Отдельная команда, а не «создайте файл в блокноте»: в консоли Windows
русский текст пишется в кодировке консоли, и YAML потом не читается.
Здесь кодировка задана явно, а путь приводится к виду, который загрузчик
понимает однозначно.
"""
from __future__ import annotations

from pathlib import Path

TEMPLATE = """# Что индексируем. Путь можно скопировать из адресной строки проводника.
roots:
  - label: "{label}"
    path: '{path}'

index:
  db: '{db}'
  # Название своей организации: она стоит в шапке каждого исходящего
  # письма, и без этого контрагентом у половины архива окажемся мы сами
  own_organization: ""
  max_file_mb: 200
  max_text_chars: 400000
  exclude_dirs:
    - "Temp"
  exclude_globs:
    - "~$*"
    - "*.tmp"
    - "*.bak"
    - "Thumbs.db"
    - "desktop.ini"

ocr:
  lang: "rus"
  dpi: 300
  max_pages: 40
"""


def default_label(root: str) -> str:
    """Метка по умолчанию — последняя осмысленная часть пути."""
    parts = [p for p in root.replace(chr(92), "/").split("/") if p]
    return parts[-1] if parts else "Архив"


def normalize_path(value: str) -> str:
    """Обратные слэши приводим к прямым: в двойных кавычках YAML считает их
    экранированием и конфиг вообще не читается."""
    return value.strip().replace(chr(92), "/")


# прежнее имя оставлено ради читаемости вызовов
normalize_root = normalize_path


def render(root: str, label: str | None = None, db: str = "index.db") -> str:
    path = normalize_path(root)
    return TEMPLATE.format(label=label or default_label(path), path=path,
                           db=normalize_path(db))


def write(target: Path, root: str, label: str | None = None,
          db: str = "index.db", force: bool = False) -> Path:
    if target.exists() and not force:
        raise FileExistsError(str(target))
    target.write_text(render(root, label, db), encoding="utf-8")
    return target
