"""Ручные правки атрибутов: приоритет и живучесть."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docsearch import db, indexer
from docsearch.config import Config, Root
from docsearch.web import create_app

LETTER = """Исх. № 270/ПТО от 14.08.2025

Подрядчик: ООО «СтройМонтаж»
О поставке щебня.
"""


@pytest.fixture
def env(tmp_path: Path):
    root = tmp_path / "arc" / "Письма"
    root.mkdir(parents=True)
    (root / "Исх 270.txt").write_text(LETTER, encoding="utf-8")
    cfg = Config(roots=[Root(label="ПТО", path=str(tmp_path / "arc"))],
                 db=str(tmp_path / "index.db"))
    conn = db.connect(cfg.db)
    indexer.run(conn, cfg)
    doc_id = conn.execute("SELECT id FROM documents").fetchone()["id"]
    yield conn, cfg, doc_id, tmp_path
    conn.close()


def test_override_beats_automatic_parsing(env):
    conn, cfg, doc_id, _ = env
    path = db.card(conn, doc_id)["path"]
    db.set_override(conn, path, {"counterparty": "ООО «СКМ»",
                                 "doc_type": "акт передачи"})
    card = db.card(conn, doc_id)
    assert card["counterparty"] == "ООО «СКМ»"
    assert card["doc_type"] == "акт передачи"


def test_override_survives_reparse(env):
    """Главное свойство: пересчёт правил не затирает правку человека."""
    conn, cfg, doc_id, _ = env
    path = db.card(conn, doc_id)["path"]
    db.set_override(conn, path, {"counterparty": "ООО «СКМ»"})
    indexer.reparse(conn, cfg)
    assert db.card(conn, doc_id)["counterparty"] == "ООО «СКМ»"


def test_override_survives_full_reindex(env):
    conn, cfg, doc_id, _ = env
    path = db.card(conn, doc_id)["path"]
    db.set_override(conn, path, {"doc_type": "акт передачи"})
    indexer.run(conn, cfg, force=True)
    assert db.card(conn, doc_id)["doc_type"] == "акт передачи"


def test_untouched_fields_stay_automatic(env):
    """Правим организацию — дата остаётся разобранной автоматически."""
    conn, cfg, doc_id, _ = env
    path = db.card(conn, doc_id)["path"]
    db.set_override(conn, path, {"counterparty": "ООО «СКМ»"})
    indexer.reparse(conn, cfg)
    assert db.card(conn, doc_id)["doc_date"] == "2025-08-14"


def test_empty_value_means_deliberately_cleared(env):
    conn, cfg, doc_id, _ = env
    path = db.card(conn, doc_id)["path"]
    db.set_override(conn, path, {"doc_number": ""})
    indexer.reparse(conn, cfg)
    assert db.card(conn, doc_id)["doc_number"] is None


def test_clearing_override_restores_automatic(env):
    conn, cfg, doc_id, _ = env
    path = db.card(conn, doc_id)["path"]
    db.set_override(conn, path, {"counterparty": "ООО «СКМ»"})
    assert db.clear_override(conn, path)
    indexer.reparse(conn, cfg)
    assert db.card(conn, doc_id)["counterparty"] == "ООО «СтройМонтаж»"


def test_edit_through_api(env):
    conn, cfg, doc_id, _ = env
    client = TestClient(create_app(cfg))
    response = client.patch(f"/api/doc/{doc_id}",
                            json={"counterparty": "ООО «СКМ»",
                                  "edited_by": "Иноземцев"})
    assert response.status_code == 200
    assert response.json()["counterparty"] == "ООО «СКМ»"

    restored = client.delete(f"/api/doc/{doc_id}/override")
    assert restored.status_code == 200
    assert restored.json()["counterparty"] == "ООО «СтройМонтаж»"


def test_refresh_picks_up_new_file(env):
    conn, cfg, doc_id, tmp_path = env
    client = TestClient(create_app(cfg))
    (tmp_path / "arc" / "Письма" / "Исх 271.txt").write_text(
        "Исх. № 271 от 15.08.2025\nПодрядчик: ООО «Высота»", encoding="utf-8")

    result = client.post("/api/refresh").json()
    assert result["added"] == 1

    recent = client.get("/api/recent").json()["results"]
    assert recent[0]["name"] == "Исх 271.txt"
    assert recent[0]["counterparty"] == "ООО «Высота»"
    assert recent[0]["edited"] == 0


def test_recent_marks_checked_documents(env):
    conn, cfg, doc_id, _ = env
    client = TestClient(create_app(cfg))
    client.patch(f"/api/doc/{doc_id}", json={"note": "проверено"})
    recent = client.get("/api/recent").json()["results"]
    assert recent[0]["edited"] == 1
