"""Веб-интерфейс: поиск, категории, выдача файла."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docsearch import db, indexer
from docsearch.config import Config, Root
from docsearch.web import create_app

LETTER = """Исх. № 270/ПТО от 14.08.2025

Подрядчик: ООО «СтройМонтаж»

О поставке щебня фр. 20-40 на объект.
"""

ACT = """АКТ освидетельствования скрытых работ № 15
г. Москва, 03.02.2024

Подрядчик: АО «МостСтрой»
Выполнены работы: гидроизоляция фундаментов.
"""


@pytest.fixture
def client(tmp_path: Path):
    root = tmp_path / "arc"
    (root / "Письма").mkdir(parents=True)
    (root / "Акты").mkdir(parents=True)
    (root / "Письма" / "Исх 270.txt").write_text(LETTER, encoding="utf-8")
    (root / "Акты" / "Акт 15.txt").write_text(ACT, encoding="utf-8")

    cfg = Config(roots=[Root(label="ПТО", path=str(root))],
                 db=str(tmp_path / "index.db"))
    conn = db.connect(cfg.db)
    indexer.run(conn, cfg)
    conn.close()
    return TestClient(create_app(cfg))


def test_page_opens(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Архив документов" in response.text


def test_empty_request_offers_categories(client):
    data = client.get("/api/search").json()
    assert data["empty"] is True
    assert data["total"] == 2
    assert data["facets"]["type"]          # категории показаны сразу


def test_search_finds_by_word_form(client):
    data = client.get("/api/search", params={"q": "поставка щебня"}).json()
    assert data["total"] == 1
    assert data["results"][0]["name"] == "Исх 270.txt"
    assert "щебн" in data["results"][0]["snippet"]


def test_filter_without_query_is_browsing(client):
    """Категория без запроса — это просмотр архива, а не поиск."""
    # тип берётся из имени файла раньше, чем из текста: «Акт 15.txt» — «акт»
    data = client.get("/api/search", params={"type": "акт"}).json()
    assert data["empty"] is False
    assert data["total"] == 1
    assert data["results"][0]["name"] == "Акт 15.txt"


def test_facet_counts_follow_filters(client):
    data = client.get("/api/search", params={"org": "мостстрой"}).json()
    assert data["total"] == 1
    types = {item["value"] for item in data["facets"]["type"]}
    assert types == {"акт"}


def test_organization_filter_is_case_insensitive(client):
    lower = client.get("/api/search", params={"org": "стройм"}).json()
    upper = client.get("/api/search", params={"org": "СТРОЙМ"}).json()
    assert lower["total"] == upper["total"] == 1


def test_document_text_is_available(client):
    found = client.get("/api/search", params={"q": "гидроизоляция"}).json()
    doc_id = found["results"][0]["id"]
    data = client.get(f"/api/doc/{doc_id}").json()
    assert "гидроизоляция" in data["text"]


def test_file_is_served(client):
    found = client.get("/api/search", params={"q": "гидроизоляция"}).json()
    doc_id = found["results"][0]["id"]
    response = client.get(f"/file/{doc_id}")
    assert response.status_code == 200
    assert "АКТ освидетельствования" in response.text


def test_unknown_document_gives_404(client):
    assert client.get("/api/doc/99999").status_code == 404
    assert client.get("/file/99999").status_code == 404


def test_paging(client):
    first = client.get("/api/search", params={"q": "подрядчик", "per_page": 1}).json()
    second = client.get("/api/search",
                        params={"q": "подрядчик", "per_page": 1, "page": 2}).json()
    assert first["total"] == 2
    assert first["results"][0]["id"] != second["results"][0]["id"]
