"""Фоновая работа сервера: обход по расписанию и дочитывание остатка."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from docsearch import db, indexer, pipeline, worker as worker_mod
from docsearch.config import Config, Root

LETTER = """Исх. № {n}/ПТО от 14.08.2025

Генеральному директору
ООО «СтройМонтаж»
Петрову П.П.

Уважаемый Пётр Петрович!

О поставке щебня.
"""


@pytest.fixture
def arc(tmp_path: Path):
    root = tmp_path / "arc" / "Письма"
    root.mkdir(parents=True)
    (root / "Исх 700.txt").write_text(LETTER.format(n=700), encoding="utf-8")
    for i in range(3):
        (root / f"Исх {80 + i}.doc").write_bytes(b"\xd0\xcf\x11\xe0")
    cfg = Config(roots=[Root(label="ПТО", path=str(tmp_path / "arc"))],
                 db=str(tmp_path / "index.db"))
    return cfg, root


def read_office(conn, cfg, limit=20):
    """Вместо Word: отдать текст, но сохранить его настоящим путём."""
    rows = db.docs_for_office(conn, list(pipeline.OFFICE_EXTS), limit=limit)
    overrides = db.overrides_map(conn)
    done = 0
    for row in rows:
        if pipeline.store_office_text(conn, cfg, row, LETTER.format(n=900),
                                      overrides):
            done += 1
    conn.commit()
    return {"done": done, "failed": 0}


def wait_until(check, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return False


def test_worker_walks_the_folder_on_its_own(arc):
    """Главное: новый файл попадает в индекс без нажатия кнопки."""
    cfg, root = arc
    worker = worker_mod.Worker(cfg, interval_minutes=0.001)
    worker.start()
    try:
        assert wait_until(lambda: worker.status()["last_walk"])
        conn = db.connect(cfg.db)
        assert db.stats(conn)["total"] == 4
        conn.close()
    finally:
        worker.stop()


def test_worker_reads_the_queue_without_anybody_watching(arc, monkeypatch):
    cfg, root = arc
    monkeypatch.setattr(pipeline, "process_office", read_office)
    monkeypatch.setattr(pipeline, "process_ocr",
                        lambda conn, cfg, limit=1: {"done": 0, "failed": 0})

    worker = worker_mod.Worker(cfg, interval_minutes=0.001)
    worker.start()
    try:
        assert wait_until(lambda: worker.status()["read"] == 3)
        assert worker.status()["pending"]["office"] == 0
    finally:
        worker.stop()


def test_missing_word_stops_that_queue_but_not_the_server(arc, monkeypatch):
    """Word может быть не установлен — сервер от этого не падает и не
    крутит бесконечно один и тот же файл."""
    cfg, root = arc
    calls = []

    def no_word(conn, cfg, limit=20):
        calls.append(1)
        raise RuntimeError("Microsoft Word не установлен")

    monkeypatch.setattr(pipeline, "process_office", no_word)
    monkeypatch.setattr(pipeline, "process_ocr",
                        lambda conn, cfg, limit=1: {"done": 0, "failed": 0})

    worker = worker_mod.Worker(cfg, interval_minutes=0.001)
    worker.start()
    try:
        assert wait_until(lambda: worker.status()["errors"])
        assert "Word" in worker.status()["errors"][0]
        tried = len(calls)
        time.sleep(0.5)
        assert len(calls) == tried      # больше не пробуем
    finally:
        worker.stop()


def test_fast_formats_go_before_slow_scans(arc, monkeypatch):
    """Старый .doc читается секундами, скан — минутами. Если мешать их в
    одну очередь, быстрые файлы будут ждать медленных до утра."""
    cfg, root = arc
    order = []
    left = {"ocr": 5, "office": 3}

    def office(conn, c, limit=20):
        order.append("office")
        left["office"] -= 1
        return {"done": 1, "failed": 0}

    def ocr(conn, c, limit=1):
        order.append("ocr")
        left["ocr"] -= 1
        return {"done": 1, "failed": 0}

    monkeypatch.setattr(pipeline, "process_office", office)
    monkeypatch.setattr(pipeline, "process_ocr", ocr)
    monkeypatch.setattr(pipeline, "pending",
                        lambda conn: dict(left, total=left["ocr"] + left["office"]))

    worker = worker_mod.Worker(cfg, interval_minutes=0)
    conn = db.connect(cfg.db)
    indexer.run(conn, cfg)
    try:
        for _ in range(5):
            worker._read_a_chunk(conn)
    finally:
        conn.close()
    # сначала разобрано всё быстрое, и только потом взялись за сканы
    assert order == ["office", "office", "office", "ocr", "ocr"]


def test_walk_now_wakes_the_worker(arc):
    cfg, root = arc
    worker = worker_mod.Worker(cfg, interval_minutes=0)   # расписание выключено
    worker.start()
    try:
        time.sleep(0.2)
        assert worker.status()["last_walk"] is None
        worker.walk_now()
        assert wait_until(lambda: worker.status()["last_walk"])
    finally:
        worker.stop()
