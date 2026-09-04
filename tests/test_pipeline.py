"""Сквозной тест: индексация временной папки, поиск, инкрементальность."""
from __future__ import annotations

from pathlib import Path

import pytest

from docsearch import db, indexer
from docsearch import search as search_mod
from docsearch.config import Config, Root

LETTER = """Исх. № 270/ПТО от 14.08.2025

Объект: КНС-4

Направляем уведомление о необходимости поставки щебня фр. 20-40
в объёме 150 т. Задержка поставки влечёт смещение сроков.
"""

ACT = """АКТ освидетельствования скрытых работ № 15
г. Екатеринбург, 03.02.2024

Выполнены работы: гидроизоляция фундаментов.
"""


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    root = tmp_path / "arc"
    (root / "2025" / "ООО СтройМонтаж" / "Письма").mkdir(parents=True)
    (root / "2024" / "АО МостСтрой" / "Акты").mkdir(parents=True)
    (root / "2025" / "ООО СтройМонтаж" / "Письма" / "Исх 270.txt").write_text(
        LETTER, encoding="utf-8"
    )
    (root / "2024" / "АО МостСтрой" / "Акты" / "Акт 15.txt").write_text(
        ACT, encoding="utf-8"
    )
    (root / "2025" / "ООО СтройМонтаж" / "КНС-4 план сетей.dwg").write_bytes(b"AC1032")
    return root


@pytest.fixture
def conn(tmp_path: Path, archive: Path):
    cfg = Config(
        roots=[Root(label="Тест", path=str(archive))],
        db=str(tmp_path / "index.db"),
    )
    connection = db.connect(cfg.db)
    yield connection, cfg
    connection.close()


def test_index_counts(conn):
    connection, cfg = conn
    stats = indexer.run(connection, cfg)
    assert stats.scanned == 3
    assert stats.added == 3
    assert db.stats(connection)["total"] == 3


def test_search_matches_other_word_form(conn):
    connection, cfg = conn
    indexer.run(connection, cfg)
    rows = search_mod.search(connection, "поставка щебня")
    assert len(rows) == 1
    assert rows[0]["name"] == "Исх 270.txt"
    assert "щебня" in rows[0]["snippet"]


def test_attributes_are_extracted(conn):
    connection, cfg = conn
    indexer.run(connection, cfg)
    row = search_mod.search(connection, "поставка щебня")[0]
    assert row["doc_type"] == "письмо"
    assert row["doc_number"] == "270/ПТО"
    assert row["doc_date"] == "2025-08-14"
    assert row["counterparty"] == "ООО «СтройМонтаж»"


def test_filters_narrow_results(conn):
    connection, cfg = conn
    indexer.run(connection, cfg)
    assert search_mod.search(connection, "работы", search_mod.Filters(doc_type="акт"))
    assert not search_mod.search(
        connection, "работы", search_mod.Filters(date_from="2030-01-01")
    )


def test_dwg_found_by_name_only(conn):
    connection, cfg = conn
    indexer.run(connection, cfg)
    rows = search_mod.search(connection, "план сетей", search_mod.Filters(ext=".dwg"))
    assert len(rows) == 1
    assert rows[0]["status"] == "name_only"


def test_phrase_search_is_exact(conn):
    connection, cfg = conn
    indexer.run(connection, cfg)
    assert search_mod.search(connection, '"скрытых работ"')
    assert not search_mod.search(connection, '"скрытых поставок"')


def test_second_run_skips_unchanged(conn):
    connection, cfg = conn
    indexer.run(connection, cfg)
    stats = indexer.run(connection, cfg)
    assert stats.skipped == 3
    assert stats.added == 0
    assert stats.updated == 0


def test_edited_file_is_reindexed(conn, archive: Path):
    connection, cfg = conn
    indexer.run(connection, cfg)
    target = archive / "2024" / "АО МостСтрой" / "Акты" / "Акт 15.txt"
    target.write_text(ACT + "\nДополнительно: монтаж металлоконструкций.\n",
                      encoding="utf-8")
    stats = indexer.run(connection, cfg)
    assert stats.updated == 1
    assert search_mod.search(connection, "монтаж металлоконструкций")


def test_deleted_file_leaves_index(conn, archive: Path):
    connection, cfg = conn
    indexer.run(connection, cfg)
    (archive / "2024" / "АО МостСтрой" / "Акты" / "Акт 15.txt").unlink()
    stats = indexer.run(connection, cfg)
    assert stats.removed == 1
    assert db.stats(connection)["total"] == 2
    assert not search_mod.search(connection, '"скрытых работ"')


def test_empty_query_returns_nothing(conn):
    connection, cfg = conn
    indexer.run(connection, cfg)
    assert search_mod.search(connection, "   ") == []


def test_missing_root_is_reported(tmp_path: Path):
    cfg = Config(
        roots=[Root(label="Нет", path=str(tmp_path / "missing"))],
        db=str(tmp_path / "index.db"),
    )
    connection = db.connect(cfg.db)
    try:
        with pytest.raises(FileNotFoundError):
            indexer.run(connection, cfg)
    finally:
        connection.close()


def test_problems_report_counts_parsed_share(conn):
    connection, cfg = conn
    indexer.run(connection, cfg)
    report = db.problems(connection)
    assert report["counts"]["ok"] == 2          # два txt
    assert report["counts"]["name_only"] == 1   # dwg
    assert report["errors"] == []


def test_problems_lists_unreadable_file(conn, archive: Path):
    connection, cfg = conn
    # docx-расширение при не-docx содержимом: ровно то, что встречается
    # в реальном архиве после ручного переименования
    (archive / "битый.docx").write_bytes(b"not a real docx")
    indexer.run(connection, cfg)
    report = db.problems(connection)
    assert report["counts"]["error"] == 1
    assert report["errors"][0]["name"] == "битый.docx"
    assert report["errors"][0]["error"]


def test_recycle_bin_is_not_indexed(conn, archive: Path):
    """Файл из корзины NAS не должен попадать в поиск."""
    recycle = archive / "#recycle" / "2024"
    recycle.mkdir(parents=True)
    (recycle / "Удалённый акт 99.txt").write_text(
        "АКТ освидетельствования скрытых работ № 99", encoding="utf-8"
    )
    stats = indexer.run(connection_and_cfg := conn[0], conn[1])
    assert stats.scanned == 3
    assert not search_mod.search(connection_and_cfg, "удалённый акт")


def test_changed_file_clears_stale_ocr_mark(conn, archive: Path):
    """Файл изменился — прежнее распознавание устарело, отметка снимается."""
    connection, cfg = conn
    indexer.run(connection, cfg)
    doc_id = search_mod.search(connection, "поставка щебня")[0]["id"]
    connection.execute(
        "UPDATE documents SET ocr_status = 'done', ocr_chars = 100 WHERE id = ?",
        (doc_id,),
    )
    connection.commit()

    target = archive / "2025" / "ООО СтройМонтаж" / "Письма" / "Исх 270.txt"
    target.write_text(LETTER + chr(10) + "Дополнение к письму.", encoding="utf-8")
    indexer.run(connection, cfg)

    card = db.card(connection, doc_id)
    assert card["ocr_status"] is None
    assert card["ocr_chars"] is None


def test_force_reindexes_everything(conn):
    connection, cfg = conn
    indexer.run(connection, cfg)
    stats = indexer.run(connection, cfg, force=True)
    assert stats.skipped == 0
    assert stats.updated == 3


def test_count_respects_filters(conn):
    """Счётчик и выдача должны считаться по одним правилам."""
    connection, cfg = conn
    indexer.run(connection, cfg)
    # «СтройМонтаж» есть в пути и письма, и чертежа
    assert search_mod.count(connection, "СтройМонтаж") == 2
    only_letters = search_mod.Filters(doc_type="письмо")
    assert search_mod.count(connection, "СтройМонтаж", only_letters) == 1
    assert len(search_mod.search(connection, "СтройМонтаж", only_letters)) == 1


def test_count_matches_unpaged_result(conn):
    connection, cfg = conn
    indexer.run(connection, cfg)
    total = search_mod.count(connection, "СтройМонтаж")
    assert len(search_mod.search(connection, "СтройМонтаж", limit=100)) == total


def test_paging_returns_different_documents(conn):
    connection, cfg = conn
    indexer.run(connection, cfg)
    first = search_mod.search(connection, "СтройМонтаж", limit=1)
    second = search_mod.search(connection, "СтройМонтаж", limit=1, offset=1)
    assert first and second
    assert first[0]["id"] != second[0]["id"]


def test_offset_past_end_is_empty(conn):
    connection, cfg = conn
    indexer.run(connection, cfg)
    assert search_mod.search(connection, "СтройМонтаж", limit=10, offset=99) == []


def test_retry_errors_reprocesses_only_failed(conn, archive: Path):
    """Сбой сети — не приговор: такие файлы должны разбираться повторно."""
    connection, cfg = conn
    broken = archive / "сорвался.docx"
    broken.write_bytes(b"not a real docx")
    indexer.run(connection, cfg)
    assert db.problems(connection)["counts"]["error"] == 1

    # файл стал читаемым, но размер и дата совпадают с прежними
    stats = indexer.run(connection, cfg)
    assert stats.updated == 0          # обычный прогон его не тронет

    stats = indexer.run(connection, cfg, retry_errors=True)
    assert stats.updated == 1          # а с флагом — повторит
