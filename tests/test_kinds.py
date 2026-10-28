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


def test_place_and_date_line_is_not_the_subject():
    """Под «АКТ №» в бланке стоит «г. Москва» и дата — это не вид акта.
    На реальном архиве так в одну кучу ушли 163 разных акта."""
    body = text("АКТ № 46", "г. Москва                    «12» мая 2025 г.",
                "передачи строительной площадки", "Мы, нижеподписавшиеся")
    assert kinds.title_from_text(body) == "акт передачи строительной площадки"


def test_blank_date_in_template():
    body = text("АКТ № ___", "г. Москва «__» мая 2025 г.", "об устранении замечаний")
    assert kinds.title_from_text(body) == "акт об устранении замечаний"


def test_item_number_before_heading():
    body = text("(16.3) Акт приемки АИИСКУЭ", "Заключение: вышеуказанное "
                "оборудование смонтировано в соответствии с проектом")
    assert kinds.title_from_text(body) == "акт приемки аиискуэ"


def test_act_wins_over_its_own_conclusion():
    body = text("Заключение: оборудование смонтировано", "Акт приемки фасада")
    assert kinds.title_from_text(body) == "акт приемки фасада"


def test_certificate_number_leaves_no_crumbs():
    title = kinds.title_from_text(
        "Сертификат соответствия №РОСС RU.32437.04ЛБК0.ОС04.00469 от 30.09.2024")
    assert title == "сертификат соответствия"
    # и когда текста нет — то же по имени файла
    assert kinds.title_from_name("Сертификат соответствия №РОСС "
                                 "RU.32437.04ЛБК0.ОС04.00469 от 30.09.2024.pdf")         == "сертификат соответствия"


def test_dump_writes_texts_grouped_and_without_repeats(tmp_path: Path):
    acts = tmp_path / "arc" / "АКТЫ"
    (acts / "Подписаные").mkdir(parents=True)
    site = text("АКТ № {n}", "г. Москва", "передачи строительной площадки",
                "Подрядчик: ООО «{org}»")
    (acts / "Акт 1.txt").write_text(site.format(n=1, org="Арктик"), encoding="utf-8")
    (acts / "Акт 11.txt").write_text(site.format(n=11, org="Дизант"), encoding="utf-8")
    # тот же акт ещё раз, в подписанных
    (acts / "Подписаные" / "Акт 11.txt").write_text(
        site.format(n=11, org="Дизант"), encoding="utf-8")
    (acts / "Акт 30.txt").write_text(
        text("АКТ № 30", "об устранении замечаний", "Замечания устранены"),
        encoding="utf-8")

    cfg = Config(roots=[Root(label="ПТО", path=str(tmp_path / "arc"))],
                 db=str(tmp_path / "index.db"))
    conn = db.connect(cfg.db)
    indexer.run(conn, cfg)

    everything = kinds.dump(conn, "акты")
    assert everything.written == 3
    assert everything.duplicates == 1
    # акты одного бланка идут подряд, между ними чужих нет
    body = everything.text
    first, second = sorted((body.index("Арктик"), body.index("Дизант")))
    assert "устранены" not in body[first:second]

    only_site = kinds.dump(conn, "акты", kind="площадки")
    conn.close()
    assert only_site.written == 2
    assert "устранены" not in only_site.text


def test_dump_cuts_long_documents(tmp_path: Path):
    acts = tmp_path / "arc" / "АКТЫ"
    acts.mkdir(parents=True)
    (acts / "Акт 5.txt").write_text(
        text("АКТ № 5", "приемки фасада", "слово " * 3000), encoding="utf-8")
    cfg = Config(roots=[Root(label="ПТО", path=str(tmp_path / "arc"))],
                 db=str(tmp_path / "index.db"))
    conn = db.connect(cfg.db)
    indexer.run(conn, cfg)
    result = kinds.dump(conn, "акты", chars=500)
    conn.close()
    assert "обрезано" in result.text
    assert len(result.text) < 2000
