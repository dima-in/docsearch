"""Виды документов в папке: по заголовку, а не по имени файла."""
from __future__ import annotations

from pathlib import Path

from docsearch import db, indexer, kinds
from docsearch.config import Config, Root

NL = chr(10)


def text(*lines: str) -> str:
    return NL.join(lines)


def test_title_split_over_two_lines():
    """«АКТ №» на одной строке, что за акт — на следующей."""
    body = text("ООО «Стройка»", "", "АКТ № 15", "приёма-передачи документации",
                "от 12.03.2025 г.", "Мы, нижеподписавшиеся…")
    assert kinds.title_from_text(body) == "акт приема-передачи документации"


def test_numbers_and_dates_do_not_split_kinds():
    """Акт № 3 от марта и акт № 17 от июня — один вид, а не два."""
    a = kinds.title_from_text(text("АКТ № 3 разбивки осей от 01.03.2025"))
    b = kinds.title_from_text(text("Акт №17 разбивки осей от «5» июня 2025 г."))
    assert a == b == "акт разбивки осей"


def test_fact_is_not_an_act():
    """«Факт. адрес» в шапке — не заголовок акта."""
    body = text("Факт. адрес: г. Москва", "Протокол совещания", "по объекту")
    assert kinds.title_from_text(body) == "протокол совещания по объекту"


def test_paragraph_is_not_a_title():
    long_line = "Акт составлен в том, что " + "работы выполнены " * 10
    assert kinds.title_from_text(long_line) is None


def test_name_is_used_when_there_is_no_text():
    assert kinds.title_from_name("Акт допуска 12.pdf") == "акт допуска"


def test_report_groups_a_folder(tmp_path: Path):
    acts = tmp_path / "arc" / "05 Акты" / "Передача"
    acts.mkdir(parents=True)
    for n in (1, 2, 3):
        (acts / f"скан {n}.txt").write_text(
            text("АКТ", f"приема-передачи документации № {n}", "от 01.02.2025"),
            encoding="utf-8")
    (acts.parent / "допуск.txt").write_text(
        text("АКТ-ДОПУСК", "для производства работ на территории"),
        encoding="utf-8")
    (tmp_path / "arc" / "Письма").mkdir()
    (tmp_path / "arc" / "Письма" / "акт в письме.txt").write_text(
        "Акт приема-передачи документации", encoding="utf-8")

    cfg = Config(roots=[Root(label="ПТО", path=str(tmp_path / "arc"))],
                 db=str(tmp_path / "index.db"))
    conn = db.connect(cfg.db)
    indexer.run(conn, cfg)
    found, folders, total = kinds.collect(conn, "акты")
    conn.close()

    assert total == 4                     # письмо из другой папки не считается
    assert found[0].title == "акт приема-передачи документации"
    assert found[0].count == 3
    assert folders["Передача"] == 3
    out = kinds.report(found, folders, total, "акты")
    assert "образец:" in out
    assert "Мы, нижеподписавшиеся" not in out    # содержимого в отчёте нет


def test_missing_folder_says_so(tmp_path: Path):
    out = kinds.report([], {}, 0, "Актыы")
    assert out.startswith("Неуспех")
