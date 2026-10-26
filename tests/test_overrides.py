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


def test_refresh_reports_what_still_has_no_text(env):
    """Кнопка «Проверить папку» должна честно говорить про сканы и .doc."""
    conn, cfg, doc_id, tmp_path = env
    client = TestClient(create_app(cfg))
    (tmp_path / "arc" / "Письма" / "Исх 300.doc").write_bytes(b"\xd0\xcf\x11\xe0")

    result = client.post("/api/refresh").json()
    assert result["added"] == 1
    assert result["pending"]["office"] == 1
    assert result["pending"]["total"] >= 1


def test_pending_endpoint(env):
    conn, cfg, doc_id, tmp_path = env
    client = TestClient(create_app(cfg))
    data = client.get("/api/pending").json()
    assert set(data) == {"ocr", "office", "total"}


def test_process_survives_missing_office(env, monkeypatch):
    """Office или Tesseract может не стоять — обработка не должна падать."""
    from docsearch import pipeline

    conn, cfg, doc_id, tmp_path = env
    (tmp_path / "arc" / "Письма" / "Исх 301.doc").write_bytes(b"\xd0\xcf\x11\xe0")
    client = TestClient(create_app(cfg))
    client.post("/api/refresh")

    def unavailable(*args, **kwargs):
        raise RuntimeError("Microsoft Word не запускается")

    monkeypatch.setattr(pipeline, "process_office", unavailable)
    monkeypatch.setattr(pipeline, "process_ocr", unavailable)

    result = client.post("/api/process").json()
    assert result["errors"]
    assert "Word" in result["errors"][0]
    assert result["office"]["done"] == 0


def test_refresh_updates_the_directory(env):
    """Новое письмо даёт нового адресата — справочник не должен устаревать."""
    conn, cfg, doc_id, tmp_path = env
    client = TestClient(create_app(cfg))
    (tmp_path / "arc" / "Письма" / "Исх 302.txt").write_text(
        chr(10).join(["Генеральному директору", "ООО «Высота»",
                      "Иванову И.И.", "Уважаемый Иван Иванович!"]),
        encoding="utf-8")

    client.post("/api/refresh")
    orgs = [r["org"] for r in db.contacts(conn)]
    assert "ООО «Высота»" in orgs
