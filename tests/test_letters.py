"""Генератор исходящих писем."""
from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docsearch import db, indexer, letters
from docsearch.config import Config, Root
from docsearch.web import create_app

HEAD = {
    "name": "ООО «ФБ-СТРОЙ»",
    "legal_address": "141014, г. Мытищи, ул. Веры Волошиной, д. 14",
    "inn": "5029172308", "kpp": "502901001",
    "phone": "8(499)649-00-50", "email": "info@fbstroy.ru",
    "signer_position": "Начальник ПТО", "signer_name": "Иноземцев Д. А.",
    "number_prefix": "РТП",
}


@pytest.fixture
def env(tmp_path: Path):
    root = tmp_path / "arc" / "Переписка"
    root.mkdir(parents=True)
    (root / "Исх РТП-175.txt").write_text(
        "Исх. РТП-175 от 19.03.2024 г.\nООО «Маренго»", encoding="utf-8")
    (root / "Исх РТП-9.txt").write_text(
        "Исх. РТП-9 от 01.02.2024 г.\nООО «Высота»", encoding="utf-8")
    cfg = Config(roots=[Root(label="ПТО", path=str(tmp_path / "arc"))],
                 db=str(tmp_path / "index.db"), letterhead=HEAD)
    conn = db.connect(cfg.db)
    indexer.run(conn, cfg)
    yield conn, cfg
    conn.close()


def test_parse_number():
    assert letters.parse_number("РТП-175") == ("РТП", 175)
    assert letters.parse_number("270/ПТО") == ("", 270)
    assert letters.parse_number("без цифр") is None
    assert letters.parse_number("") is None


def test_next_number_continues_the_archive(env):
    """Журнал исходящих никто не ведёт — максимум берём из самих писем."""
    conn, _ = env
    assert letters.next_number(conn, "РТП") == "РТП-176"


def test_next_number_ignores_other_prefixes(env):
    conn, _ = env
    assert letters.next_number(conn, "ВХ") == "ВХ-1"


def test_known_recipients_come_from_archive(env):
    conn, _ = env
    assert "ООО «Маренго»" in letters.known_recipients(conn)


def test_ru_date():
    assert letters.ru_date("2024-03-19") == "19 марта 2024 г."
    assert letters.ru_date("мусор").endswith("г.")


def test_letterhead_skips_empty_fields():
    head = letters.Letterhead.from_config({"name": "ООО «Тест»"})
    assert head.header_lines() == ["ООО «Тест»"]


def test_docx_contains_the_fields():
    head = letters.Letterhead.from_config(HEAD)
    blob = letters.build_docx({
        "number": "РТП-176", "date": "2026-10-06",
        "recipient_org": "ООО «Маренго»", "recipient_person": "Белякову А. В.",
        "subject": "Нарушение сроков", "reference": "РТП-145 от 18.01.2024",
        "body": "Просим устранить замечания.",
    }, head)
    with zipfile.ZipFile(BytesIO(blob)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    for expected in ("РТП-176", "ООО «Маренго»", "Белякову А. В.",
                     "Нарушение сроков", "Просим устранить замечания.",
                     "Начальник ПТО", "6 октября 2026 г.", "РТП-145"):
        assert expected in xml, expected


def test_file_name_is_safe_and_readable():
    name = letters.file_name({"number": "РТП-176", "date": "2026-10-06",
                              "subject": "Поставка арматуры А500С"})
    assert name == "Исх РТП-176 от 06.10.2026 Поставка арматуры А500С.docx"
    bad = letters.file_name({"subject": "Смета 1/2 по объекту"})
    assert "/" not in bad


def test_draft_endpoint(env):
    conn, cfg = env
    client = TestClient(create_app(cfg))
    draft = client.get("/api/letter/draft").json()
    assert draft["number"] == "РТП-176"
    assert draft["signer_name"] == "Иноземцев Д. А."
    assert "ООО «Маренго»" in draft["recipients"]


def test_build_endpoint_returns_docx(env):
    conn, cfg = env
    client = TestClient(create_app(cfg))
    response = client.post("/api/letter", json={
        "number": "РТП-176", "date": "2026-10-06",
        "recipient_org": "ООО «Маренго»", "subject": "Проверка",
        "body": "Текст письма.",
    })
    assert response.status_code == 200
    assert response.headers["content-type"].endswith("wordprocessingml.document")
    assert zipfile.ZipFile(BytesIO(response.content)).namelist()


def test_build_refuses_without_letterhead(tmp_path: Path):
    """Письмо без бланка отправлять нельзя, и молчать об этом тоже."""
    cfg = Config(roots=[], db=str(tmp_path / "index.db"))
    conn = db.connect(cfg.db)
    conn.close()
    client = TestClient(create_app(cfg))
    response = client.post("/api/letter", json={"recipient_org": "ООО «Х»"})
    assert response.status_code == 400
    assert "letterhead" in response.json()["detail"]


def test_register_writes_exact_attributes(env):
    """Атрибуты сгенерированного письма не угадываются, а берутся как есть."""
    conn, cfg = env
    path = str(Path(cfg.roots[0].path) / "Переписка" / "Исх РТП-176.docx")
    letters.register(conn, path, {
        "number": "РТП-176", "date": "2026-10-06",
        "recipient_org": "ООО «Маренго»", "subject": "Проверка",
    })
    saved = db.get_override(conn, path)
    assert saved["doc_number"] == "РТП-176"
    assert saved["counterparty"] == "ООО «Маренго»"
    assert saved["section"] == "переписка"
