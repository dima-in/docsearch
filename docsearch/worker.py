"""Фоновая работа сервера: обход архива по расписанию и дочитывание остатка.

Нажимать кнопку и ждать — не работа для человека. Обход занимает минуты,
распознавание сканов — часы, и всё это время браузер должен был оставаться
открытым. Здесь то же самое делает сам сервер: раз в час проверяет папку,
а в остальное время разбирает очередь — сначала быстрое, потом долгое.

Порядок не случаен. Старый .doc читается секундами, скан — минутами. Если
мешать их в одну очередь, семьсот писем в .doc, которые разобрались бы за
полчаса, будут ждать тысячу сканов до утра. Поэтому сначала до конца
вычитываются старые форматы, и только потом начинается распознавание.

Поток один, и пишет в базу только он: SQLite не любит нескольких
пишущих, а запросы из браузера только читают.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from . import db, indexer, letters, pipeline
from .config import Config

OFFICE_CHUNK = 20
# по одному скану за раз: на время порции база занята, а человек в это
# время может нажать «Проверить папку» и ждать ответа
OCR_CHUNK = 1
IDLE_SLEEP = 5.0            # как часто просыпаться, когда делать нечего
DEFAULT_INTERVAL_MINUTES = 60


class Worker:
    """Обход и дочитывание в фоне. Состояние отдаётся наружу через status()."""

    def __init__(self, cfg: Config, interval_minutes: float | None = None):
        self.cfg = cfg
        if interval_minutes is None:
            interval_minutes = float(
                (cfg.serve or {}).get("auto_refresh_minutes",
                                      DEFAULT_INTERVAL_MINUTES))
        self.interval = max(0.0, interval_minutes) * 60
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        # пишет в базу либо фоновый поток, либо обход по кнопке — не оба
        self.db_lock = threading.Lock()
        self._walk_requested = False
        # чего не умеет эта машина: без Word или Tesseract долбиться
        # в очередь бессмысленно, но и ронять сервер незачем
        self._broken: dict[str, str] = {}
        self._state = {
            "state": "ждёт",
            "pending": {"ocr": 0, "office": 0, "total": 0},
            "last_walk": None,
            "last_walk_result": None,
            "read": 0,
            "failed": 0,
            "errors": [],
            "auto_minutes": self.interval / 60,
        }

    # — наружу ————————————————————————————————————————————————

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def walk_now(self) -> None:
        """Проверить папку, не дожидаясь расписания."""
        with self._lock:
            self._walk_requested = True
            # прошлая неудача могла быть из-за выключенного сервера
            self._broken.clear()
            self._state["errors"] = []
        self._wake.set()

    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="docsearch-worker",
                                        daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None

    # — внутри потока ——————————————————————————————————————————

    def _set(self, **values) -> None:
        with self._lock:
            self._state.update(values)

    def _due(self, last: float) -> bool:
        if self._walk_requested:
            return True
        return bool(self.interval) and (time.time() - last) >= self.interval

    def _run(self) -> None:
        conn = db.connect(self.cfg.db)
        last_walk = time.time() if self.interval else 0.0
        try:
            self._set(pending=pipeline.pending(conn))
            while not self._stop.is_set():
                if self._due(last_walk):
                    with self._lock:
                        self._walk_requested = False
                    with self.db_lock:
                        self._walk(conn)
                    last_walk = time.time()
                elif not self._read_a_chunk(conn):
                    self._set(state="ждёт")
                    self._wake.wait(IDLE_SLEEP)
                    self._wake.clear()
        finally:
            conn.close()

    def _walk(self, conn) -> None:
        self._set(state="проверяю папку")
        try:
            stats = indexer.run(conn, self.cfg)
        except Exception as exc:
            self._note(f"обход не удался: {exc}")
            self._set(state="ждёт")
            return
        if stats.added or stats.updated or stats.removed:
            # новые письма приносят новых адресатов
            letters.rebuild_contacts(conn, own_org=self.cfg.own_org,
                                     own_people=self.cfg.own_people)
        self._set(
            state="ждёт",
            last_walk=datetime.now().isoformat(timespec="seconds"),
            last_walk_result={"scanned": stats.scanned, "added": stats.added,
                              "updated": stats.updated, "removed": stats.removed,
                              "seconds": round(stats.seconds)},
            pending=pipeline.pending(conn),
        )

    def _read_a_chunk(self, conn) -> bool:
        """Разобрать одну порцию. False — очередь пуста или нечем читать."""
        left = pipeline.pending(conn)
        self._set(pending=left)

        for kind, label, run, chunk in (
            ("office", "читаю старые .doc", pipeline.process_office, OFFICE_CHUNK),
            ("ocr", "распознаю сканы", pipeline.process_ocr, OCR_CHUNK),
        ):
            if not left[kind] or kind in self._broken:
                continue
            self._set(state=label)
            try:
                with self.db_lock:
                    result = run(conn, self.cfg, chunk)
            except Exception as exc:
                # Word или Tesseract не установлены — больше не пробуем,
                # пока не нажмут «Проверить папку»
                self._broken[kind] = str(exc)
                self._note(f"{label}: {exc}")
                continue
            if not result["done"] and not result["failed"]:
                continue
            if result["done"]:
                with self.db_lock:
                    letters.rebuild_contacts(conn, own_org=self.cfg.own_org,
                                             own_people=self.cfg.own_people)
            with self._lock:
                self._state["read"] += result["done"]
                self._state["failed"] += result["failed"]
            self._set(pending=pipeline.pending(conn))
            return True
        return False

    def _note(self, message: str) -> None:
        with self._lock:
            errors = [e for e in self._state["errors"] if e != message]
            self._state["errors"] = (errors + [message])[-3:]
