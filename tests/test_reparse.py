"""Пересчёт атрибутов без перечитывания файлов и без потери распознавания."""
from __future__ import annotations

from pathlib import Path

import pytest

from docsearch import db, indexer, meta
from docsearch.config import Config, Root

LETTER = """Исх. № 270/ПТО от 14.08.2025

Подрядчик: ООО «СтройМонтаж»
О поставке щебня.
"""


@pytest.fixture
def prepared(tmp_path: Path):
    root = tmp_path / "arc" / "Письма"
    root.mkdir(parents=True)
    (root / "Исх 270.txt").write_text(LETTER, encoding="utf-8")
    cfg = Config(roots=[Root(label="ПТО", path=str(tmp_path / "arc"))],
                 db=str(tmp_path / "index.db"))
    conn = db.connect(cfg.db)
    indexer.run(conn, cfg)
    yield conn, cfg, tmp_path
    conn.close()


def test_reparse_restores_wrong_attributes(prepared):
    conn, cfg, _ = prepared
    doc_id = conn.execute("SELECT id FROM documents").fetchone()["id"]
    conn.execute(
        "UPDATE documents SET doc_type='ерунда', counterparty='Новая папка',"
        " doc_date=NULL WHERE id=?", (doc_id,))
    conn.commit()

    result = indexer.reparse(conn, cfg)
    assert result["changed"] == 1

    card = db.card(conn, doc_id)
    assert card["doc_type"] == "письмо"
    assert card["doc_date"] == "2025-08-14"
    assert card["counterparty"] == "ООО «СтройМонтаж»"


def test_reparse_keeps_ocr(prepared):
    """Главное свойство: распознанное не должно пропадать."""
    conn, cfg, _ = prepared
    doc_id = conn.execute("SELECT id FROM documents").fetchone()["id"]
    conn.execute(
        "UPDATE documents SET ocr_status='done', ocr_chars=42 WHERE id=?",
        (doc_id,))
    conn.commit()

    indexer.reparse(conn, cfg)
    card = db.card(conn, doc_id)
    assert card["ocr_status"] == "done"
    assert card["ocr_chars"] == 42
    assert db.body(conn, doc_id)          # текст на месте


def test_reparse_does_not_need_files(prepared):
    """Файлы могут быть недоступны: сеть отвалилась, шара размонтирована."""
    conn, cfg, tmp_path = prepared
    for item in (tmp_path / "arc" / "Письма").iterdir():
        item.unlink()

    doc_id = conn.execute("SELECT id FROM documents").fetchone()["id"]
    result = indexer.reparse(conn, cfg)
    assert result["seen"] == 1
    assert db.card(conn, doc_id)["doc_type"] == "письмо"


def test_reparse_is_idempotent(prepared):
    conn, cfg, _ = prepared
    indexer.reparse(conn, cfg)
    assert indexer.reparse(conn, cfg)["changed"] == 0


def test_own_organization_applies_on_reparse(tmp_path: Path):
    """Своя организация задаётся позже — пересчёт должен её учесть."""
    root = tmp_path / "arc"
    root.mkdir()
    (root / "Исх 5.txt").write_text(
        "ООО «ФБ-СТРОЙ»\nГенеральному директору ООО «Маренго»\n",
        encoding="utf-8")

    cfg = Config(roots=[Root(label="ПТО", path=str(root))],
                 db=str(tmp_path / "index.db"))
    conn = db.connect(cfg.db)
    try:
        indexer.run(conn, cfg)
        doc_id = conn.execute("SELECT id FROM documents").fetchone()["id"]
        assert db.card(conn, doc_id)["counterparty"] == "ООО «ФБ-СТРОЙ»"

        cfg.own_org = "ФБ-СТРОЙ"
        indexer.reparse(conn, cfg)
        assert db.card(conn, doc_id)["counterparty"] == "ООО «Маренго»"
    finally:
        conn.close()


def test_implausible_years_rejected():
    assert meta.find_date("от 12.03.2051") is None
    assert meta.find_date("версия 01.02.2029") is None
    assert meta.find_date("от 12.03.1985") is None
    assert meta.find_date("от 12.03.2024") == "2024-03-12"
