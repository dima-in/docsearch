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
    orgs = [item["org"] for item in draft["recipients"]]
    assert "ООО «Маренго»" in orgs


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


def make_template(path: Path) -> Path:
    """Бланк для теста: своего в репозитории нет и быть не должно."""
    import docx

    document = docx.Document()
    document.add_paragraph("ООО «Образец»")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].paragraphs[0].text = "Исх. {{number}} от {{date}}"
    right = table.rows[0].cells[1]
    right.paragraphs[0].text = "{{recipient_position}}"
    right.add_paragraph("{{recipient_org}}")
    right.add_paragraph("{{recipient_person}}")
    document.add_paragraph("Тема: «{{subject}}»")
    document.add_paragraph("{{greeting}}")
    document.add_paragraph("{{body}}")
    document.add_paragraph("{{signer_position}}\t\t{{signer_name}}")
    document.save(str(path))
    return path


def read_all(blob: bytes) -> list[str]:
    import docx

    document = docx.Document(BytesIO(blob))
    lines = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                lines += [p.text.strip() for p in cell.paragraphs if p.text.strip()]
    return lines


def test_template_is_filled(tmp_path: Path):
    template = make_template(tmp_path / "бланк.docx")
    head = letters.Letterhead.from_config({**HEAD, "template": str(template)})
    blob = letters.render({
        "number": "РТП-1336", "date": "2026-10-07",
        "recipient_position": "Генеральному директору",
        "recipient_org": "ООО «Мосренстрой-6»",
        "recipient_person": "Севрюкову Е. В.",
        "subject": "Ответ на УКМ-300", "greeting": "Уважаемый Евгений Владимирович!",
        "body": "Первый абзац.",
    }, head)
    lines = read_all(blob)
    assert "Исх. РТП-1336 от 7 октября 2026 г." in lines
    assert "ООО «Мосренстрой-6»" in lines
    assert "Тема: «Ответ на УКМ-300»" in lines
    assert "Первый абзац." in lines
    assert not any("{{" in line for line in lines)


def test_multiline_body_becomes_several_paragraphs(tmp_path: Path):
    template = make_template(tmp_path / "бланк.docx")
    head = letters.Letterhead.from_config({**HEAD, "template": str(template)})
    blob = letters.render({"recipient_org": "ООО «Х»",
                           "body": "Первый.\nВторой.\nТретий."}, head)
    lines = read_all(blob)
    for expected in ("Первый.", "Второй.", "Третий."):
        assert expected in lines


def test_signer_falls_back_to_letterhead(tmp_path: Path):
    template = make_template(tmp_path / "бланк.docx")
    head = letters.Letterhead.from_config({**HEAD, "template": str(template)})
    lines = read_all(letters.render({"recipient_org": "ООО «Х»"}, head))
    assert any("Иноземцев Д. А." in line for line in lines)


def test_missing_fields_leave_no_placeholders(tmp_path: Path):
    """Незаполненное поле должно исчезнуть, а не остаться скобками в письме."""
    template = make_template(tmp_path / "бланк.docx")
    head = letters.Letterhead.from_config({**HEAD, "template": str(template)})
    lines = read_all(letters.render({"recipient_org": "ООО «Х»"}, head))
    assert not any("{{" in line or "}}" in line for line in lines)


def test_falls_back_when_template_missing(tmp_path: Path):
    head = letters.Letterhead.from_config(
        {**HEAD, "template": str(tmp_path / "нет.docx")})
    lines = read_all(letters.render({"recipient_org": "ООО «Х»",
                                     "body": "Текст."}, head))
    assert "ООО «ФБ-СТРОЙ»" in lines     # программная вёрстка сработала


def test_template_builder_marks_the_places(tmp_path: Path):
    """Инструмент из tools/ размечает отправленное письмо в шаблон."""
    import importlib.util

    source = tmp_path / "письмо.docx"
    import docx

    document = docx.Document()
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].paragraphs[0].text = "Исх. РТП-1335 от 06.10.2026 г."
    right = table.rows[0].cells[1]
    right.paragraphs[0].text = "Генеральному директору"
    right.add_paragraph("ООО «Мосренстрой-6»")
    right.add_paragraph("Севрюкову Е.В.")
    document.add_paragraph("Тема: «Ответ на письмо»")
    document.add_paragraph("Уважаемый Евгений Владимирович!")
    document.add_paragraph("Между сторонами заключен договор подряда.")
    document.add_paragraph("Второй абзац письма.")
    document.add_paragraph("С уважением,")
    document.add_paragraph("Руководитель проекта\t\tСтерхов Д.А.")
    document.save(str(source))

    spec = importlib.util.spec_from_file_location(
        "make_template",
        Path(__file__).resolve().parent.parent / "tools" / "make_template.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    target = tmp_path / "шаблон.docx"
    module.build(str(source), str(target))

    result = docx.Document(str(target))
    lines = [p.text.strip() for p in result.paragraphs if p.text.strip()]
    assert "Тема: «{{subject}}»" in lines
    assert "{{greeting}}" in lines
    assert "{{body}}" in lines
    assert "Второй абзац письма." not in lines     # содержание выброшено
    assert any("{{signer_name}}" in line for line in lines)


def test_addressee_parsed_from_letter_body():
    """Блок «кому» в исходящем — это готовая карточка адресата."""
    text = (chr(10).join([
        "Исх. РТП-1335 от 06.10.2026 г.",
        "Генеральному директору",
        "ООО «Мосренстрой-6»",
        "Севрюкову Е.В.",
        "Тема: «Ответ»",
    ]))
    found = letters.parse_addressee(text)
    assert found["position"] == "Генеральному директору"
    assert found["org"] == "ООО «Мосренстрой-6»"
    assert found["person"] == "Севрюкову Е.В."


def test_addressee_absent():
    assert letters.parse_addressee("Просто текст без адресата") is None
    assert letters.parse_addressee("") is None


def test_contacts_are_built_from_correspondence(env):
    conn, cfg = env
    conn.execute(
        "UPDATE documents SET section = 'переписка', doc_type = 'письмо'")
    conn.commit()
    conn.execute(
        "DELETE FROM doc_fts WHERE rowid = (SELECT MIN(id) FROM documents)")
    doc_id = conn.execute("SELECT MIN(id) id FROM documents").fetchone()["id"]
    body = chr(10).join(["Генеральному директору", "ООО «Маренго»",
                         "Белякову А. В."])
    conn.execute("INSERT INTO doc_fts (rowid, name, body, lemmas)"
                 " VALUES (?,?,?,?)", (doc_id, "письмо", body, body))
    conn.commit()

    rows = letters.rebuild_contacts(conn)
    found = {r["org"]: r for r in rows}
    assert found["ООО «Маренго»"]["person"] == "Беляков А. В." or            found["ООО «Маренго»"]["person"] == "Белякову А. В."
    assert found["ООО «Маренго»"]["position"] == "Генеральному директору"


def test_contacts_endpoint(env):
    conn, cfg = env
    client = TestClient(create_app(cfg))
    assert client.post("/api/letter/contacts").status_code == 200
