"""Существующий индекс не должен ломаться при добавлении новых колонок."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from docsearch import db

OLD_SCHEMA = """
CREATE TABLE documents (
    id          INTEGER PRIMARY KEY,
    path        TEXT    NOT NULL UNIQUE,
    root        TEXT    NOT NULL,
    rel_path    TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    ext         TEXT    NOT NULL,
    size        INTEGER NOT NULL,
    mtime       REAL    NOT NULL,
    needs_ocr   INTEGER NOT NULL DEFAULT 0,
    status      TEXT    NOT NULL DEFAULT 'ok',
    indexed_at  REAL    NOT NULL
);
"""


def test_old_index_gets_new_columns(tmp_path: Path):
    db_path = tmp_path / "index.db"
    old = sqlite3.connect(db_path)
    old.executescript(OLD_SCHEMA)
    old.execute(
        "INSERT INTO documents (path, root, rel_path, name, ext, size, mtime,"
        " needs_ocr, status, indexed_at) VALUES"
        " ('C:/a/скан.pdf','ПТО','скан.pdf','скан.pdf','.pdf',10,1.0,1,'needs_ocr',1.0)"
    )
    old.commit()
    old.close()

    conn = db.connect(str(db_path))
    try:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(documents)")}
        assert {"ocr_status", "ocr_at", "ocr_chars"} <= columns
        # и данные на месте
        assert conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"] == 1
        assert len(db.docs_for_ocr(conn)) == 1
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_path: Path):
    db_path = str(tmp_path / "index.db")
    conn = db.connect(db_path)
    try:
        assert db.migrate(conn) == []      # свежая база уже полная
    finally:
        conn.close()


def test_reset_all_ocr_requeues_recognized(tmp_path: Path):
    conn = db.connect(str(tmp_path / "index.db"))
    try:
        conn.execute(
            "INSERT INTO documents (path, root, rel_path, name, ext, size, mtime,"
            " needs_ocr, status, indexed_at, ocr_status) VALUES"
            " ('C:/a/скан.pdf','ПТО','скан.pdf','скан.pdf','.pdf',10,1.0,1,"
            "'ok',1.0,'done')"
        )
        conn.commit()
        assert db.docs_for_ocr(conn) == []
        assert db.reset_all_ocr(conn) == 1
        assert len(db.docs_for_ocr(conn)) == 1
    finally:
        conn.close()


def _add_scan(conn, path: str, ext: str) -> None:
    conn.execute(
        "INSERT INTO documents (path, root, rel_path, name, ext, size, mtime,"
        " needs_ocr, status, indexed_at) VALUES (?,?,?,?,?,?,?,1,'ok',1.0)",
        (path, "ПТО", path, path, ext, 10, 1.0),
    )


def test_ocr_queue_can_be_limited_by_extension(tmp_path: Path):
    """Фотографии с объекта не должны попадать в очередь распознавания."""
    conn = db.connect(str(tmp_path / "index.db"))
    try:
        _add_scan(conn, "письмо.pdf", ".pdf")
        _add_scan(conn, "фото стены.jpg", ".jpg")
        _add_scan(conn, "фото плиты.png", ".png")
        conn.commit()

        assert len(db.docs_for_ocr(conn)) == 3
        only_pdf = db.docs_for_ocr(conn, exts=[".pdf"])
        assert [r["ext"] for r in only_pdf] == [".pdf"]
        # расширение принимается и без точки
        assert len(db.docs_for_ocr(conn, exts=["pdf"])) == 1
    finally:
        conn.close()
