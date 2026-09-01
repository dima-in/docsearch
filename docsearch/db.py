"""Хранилище: SQLite + FTS5.

documents  — карточка файла (путь, размер, метаданные, статус разбора)
doc_fts    — полнотекстовый индекс, rowid совпадает с documents.id
             body   — исходный текст, из него делаем сниппеты
             lemmas — тот же текст в начальных формах, по нему ищем
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY,
    path        TEXT    NOT NULL UNIQUE,
    root        TEXT    NOT NULL,
    rel_path    TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    ext         TEXT    NOT NULL,
    size        INTEGER NOT NULL,
    mtime       REAL    NOT NULL,
    doc_type    TEXT,
    doc_number  TEXT,
    doc_date    TEXT,
    counterparty TEXT,
    object_code TEXT,
    page_count  INTEGER,
    needs_ocr   INTEGER NOT NULL DEFAULT 0,
    status      TEXT    NOT NULL DEFAULT 'ok',
    error       TEXT,
    indexed_at  REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_ext    ON documents(ext);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_date   ON documents(doc_date);
CREATE INDEX IF NOT EXISTS idx_documents_root   ON documents(root);

CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(
    name,
    body,
    lemmas,
    tokenize = "unicode61 remove_diacritics 2"
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def fingerprints(conn: sqlite3.Connection, root: str) -> dict[str, tuple[int, float]]:
    """path -> (size, mtime) для инкрементального обхода."""
    rows = conn.execute(
        "SELECT path, size, mtime FROM documents WHERE root = ?", (root,)
    )
    return {r["path"]: (r["size"], r["mtime"]) for r in rows}


def upsert(conn: sqlite3.Connection, doc: dict, body: str, lemmas: str) -> int:
    """Записать карточку файла и его текст. Возвращает id."""
    cur = conn.execute("SELECT id FROM documents WHERE path = ?", (doc["path"],))
    row = cur.fetchone()
    fields = (
        doc["root"], doc["rel_path"], doc["name"], doc["ext"], doc["size"],
        doc["mtime"], doc.get("doc_type"), doc.get("doc_number"),
        doc.get("doc_date"), doc.get("counterparty"), doc.get("object_code"),
        doc.get("page_count"), int(doc.get("needs_ocr", 0)),
        doc.get("status", "ok"), doc.get("error"), time.time(),
    )
    if row:
        doc_id = row["id"]
        conn.execute(
            """UPDATE documents SET root=?, rel_path=?, name=?, ext=?, size=?,
               mtime=?, doc_type=?, doc_number=?, doc_date=?, counterparty=?,
               object_code=?, page_count=?, needs_ocr=?, status=?, error=?,
               indexed_at=? WHERE id=?""",
            fields + (doc_id,),
        )
        conn.execute("DELETE FROM doc_fts WHERE rowid = ?", (doc_id,))
    else:
        cur = conn.execute(
            """INSERT INTO documents (path, root, rel_path, name, ext, size,
               mtime, doc_type, doc_number, doc_date, counterparty, object_code,
               page_count, needs_ocr, status, error, indexed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (doc["path"],) + fields,
        )
        doc_id = cur.lastrowid

    conn.execute(
        "INSERT INTO doc_fts (rowid, name, body, lemmas) VALUES (?,?,?,?)",
        (doc_id, doc["name"], body, lemmas),
    )
    return doc_id


def delete_missing(conn: sqlite3.Connection, root: str, seen: set[str]) -> int:
    """Убрать из индекса файлы, которых больше нет на диске."""
    rows = conn.execute("SELECT id, path FROM documents WHERE root = ?", (root,))
    stale = [r["id"] for r in rows if r["path"] not in seen]
    for doc_id in stale:
        conn.execute("DELETE FROM doc_fts WHERE rowid = ?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    return len(stale)


def stats(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
    by_status = {
        r["status"]: r["c"]
        for r in conn.execute(
            "SELECT status, COUNT(*) c FROM documents GROUP BY status ORDER BY c DESC"
        )
    }
    by_ext = [
        (r["ext"], r["c"])
        for r in conn.execute(
            "SELECT ext, COUNT(*) c FROM documents GROUP BY ext ORDER BY c DESC LIMIT 25"
        )
    ]
    ocr = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE needs_ocr = 1"
    ).fetchone()["c"]
    return {"total": total, "by_status": by_status, "by_ext": by_ext, "needs_ocr": ocr}


def problems(conn: sqlite3.Connection, limit: int = 20) -> dict:
    """Файлы, с которыми что-то не так: не открылись, пустые, без текста.

    На реальном архиве это главный отчёт: он показывает, какую часть
    документов поиск сейчас не видит и почему.
    """
    def rows(status: str, order: str = "size DESC"):
        return [
            dict(r)
            for r in conn.execute(
                f"SELECT name, rel_path, root, ext, size, error FROM documents"
                f" WHERE status = ? ORDER BY {order} LIMIT ?",
                (status, limit),
            )
        ]

    counts = {
        r["status"]: r["c"]
        for r in conn.execute(
            "SELECT status, COUNT(*) c FROM documents GROUP BY status"
        )
    }
    ocr_by_ext = [
        (r["ext"], r["c"])
        for r in conn.execute(
            "SELECT ext, COUNT(*) c FROM documents WHERE needs_ocr = 1"
            " GROUP BY ext ORDER BY c DESC"
        )
    ]
    return {
        "counts": counts,
        "errors": rows("error"),
        "empty": rows("empty"),
        "needs_ocr": rows("needs_ocr"),
        "ocr_by_ext": ocr_by_ext,
    }
