"""Инкрементальная индексация: обходим папки, разбираем изменившееся."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import db, extract, meta, morph
from .config import Config
from .walker import walk

COMMIT_EVERY = 200


@dataclass
class IndexStats:
    scanned: int = 0
    added: int = 0
    updated: int = 0
    skipped: int = 0
    removed: int = 0
    too_big: int = 0
    unsupported: int = 0
    errors: int = 0
    needs_ocr: int = 0
    by_status: dict = field(default_factory=dict)
    seconds: float = 0.0


def index_root(
    conn: sqlite3.Connection,
    cfg: Config,
    root_path: str,
    label: str,
    stats: IndexStats,
    progress=None,
    force: bool = False,
    retry_errors: bool = False,
) -> None:
    known = db.fingerprints(conn, label)
    retry = db.error_paths(conn, label) if retry_errors else set()
    seen: set[str] = set()
    pending = 0

    for path in walk(root_path, cfg):
        try:
            st = path.stat()
        except OSError:
            continue

        key = str(path)
        seen.add(key)
        stats.scanned += 1
        if progress and stats.scanned % 100 == 0:
            progress(stats)

        ext = path.suffix.lower()
        if not extract.supported(ext):
            stats.unsupported += 1
            continue

        prev = known.get(key)
        # тот же размер и та же дата — файл не трогали, разбирать нечего
        if (not force and key not in retry and prev
                and prev[0] == st.st_size
                and abs(prev[1] - st.st_mtime) < 1.0):
            stats.skipped += 1
            continue

        if st.st_size > cfg.max_file_bytes:
            stats.too_big += 1
            continue

        result = extract.extract(path)
        text = result.text[: cfg.max_text_chars]
        rel_path = str(path.relative_to(root_path))
        attrs = meta.guess(path, rel_path, text, cfg.own_org)
        attrs.update({k: v for k, v in result.meta.items() if v})
        attrs.pop("organizations", None)   # в карточку идёт только контрагент

        doc = {
            "path": key,
            "root": label,
            "rel_path": rel_path,
            "name": path.name,
            "ext": ext,
            "size": st.st_size,
            "mtime": st.st_mtime,
            "page_count": result.page_count,
            "needs_ocr": result.needs_ocr,
            "status": result.status,
            "error": result.error,
            **attrs,
        }

        # имя файла тоже лемматизируем — по нему ищут не реже, чем по тексту
        searchable = f"{path.name}\n{rel_path}\n{text}"
        db.upsert(conn, doc, body=text, lemmas=morph.lemmatize(searchable))

        stats.added += 0 if prev else 1
        stats.updated += 1 if prev else 0
        stats.by_status[result.status] = stats.by_status.get(result.status, 0) + 1
        if result.needs_ocr:
            stats.needs_ocr += 1
        if result.status == "error":
            stats.errors += 1

        pending += 1
        if pending >= COMMIT_EVERY:
            conn.commit()
            pending = 0

    conn.commit()
    stats.removed += db.delete_missing(conn, label, seen)
    conn.commit()


def run(conn: sqlite3.Connection, cfg: Config, progress=None,
        force: bool = False, retry_errors: bool = False) -> IndexStats:
    stats = IndexStats()
    started = time.monotonic()
    for root in cfg.roots:
        if not Path(root.path).exists():
            raise FileNotFoundError(f"Папка недоступна: {root.path}")
        index_root(conn, cfg, root.path, root.label, stats, progress,
                   force, retry_errors)
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('last_index', ?)",
                 (str(time.time()),))
    conn.commit()
    stats.seconds = time.monotonic() - started
    return stats
