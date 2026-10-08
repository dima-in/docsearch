"""Веб-интерфейс: строка поиска плюс отбор по категориям слева.

Приложение живёт в одном месте, остальные открывают ссылку в браузере —
ставить ничего никому не надо. База открывается только на чтение: писать
в неё имеет право один индексатор.

Файл отдаётся самим приложением по HTTP. Ссылка вида file://\\\\сервер\\...
из веб-страницы не откроется — браузеры это запрещают, — поэтому мы
стримим содержимое, а сетевой путь показываем рядом для копирования.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import quote

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               Response)

from . import db, indexer, letters
from . import search as search_mod
from .config import Config

PAGE = Path(__file__).resolve().parent / "static" / "index.html"

# Что показывать в браузере, а что отдавать на скачивание
INLINE_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".txt": "text/plain; charset=utf-8",
}


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="Поиск по архиву документов", docs_url=None,
                  redoc_url=None)

    def connect() -> sqlite3.Connection:
        # каждое обращение — своя связь: sqlite не любит хождения между потоками
        return db.connect(cfg.db)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE.read_text(encoding="utf-8")

    @app.get("/api/search")
    def api_search(
        q: str = "",
        section: str = "",
        type: str = "",
        org: str = "",
        year: str = "",
        ext: str = "",
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=100),
    ) -> JSONResponse:
        filters = search_mod.Filters(
            section=section or None,
            doc_type=type or None,
            counterparty=org or None,
            year=year or None,
            ext=ext or None,
        )
        conn = connect()
        try:
            if not search_mod.has_criteria(q, filters):
                source, where, params = search_mod.conditions("", None)
                return JSONResponse({
                    "total": db.stats(conn)["total"],
                    "results": [],
                    "facets": db.facets(conn, source, where, params),
                    "empty": True,
                })

            offset = (page - 1) * per_page
            total = search_mod.count(conn, q, filters)
            rows = search_mod.search(conn, q, filters, limit=per_page,
                                     offset=offset)
            source, where, params = search_mod.conditions(q, filters)
            return JSONResponse({
                "total": total,
                "page": page,
                "per_page": per_page,
                "results": rows,
                "facets": db.facets(conn, source, where, params),
                "empty": False,
            })
        finally:
            conn.close()

    @app.get("/api/doc/{doc_id}")
    def api_doc(doc_id: int) -> JSONResponse:
        conn = connect()
        try:
            card = db.card(conn, doc_id)
            if not card:
                raise HTTPException(404, "Документа нет в индексе")
            card["text"] = db.body(conn, doc_id)[:20000]
            return JSONResponse(card)
        finally:
            conn.close()

    @app.get("/file/{doc_id}")
    def file(doc_id: int, download: int = 0):
        """Отдать сам файл. Путь берём из индекса, а не из запроса — так
        через этот адрес нельзя вытащить ничего постороннего."""
        conn = connect()
        try:
            card = db.card(conn, doc_id)
        finally:
            conn.close()
        if not card:
            raise HTTPException(404, "Документа нет в индексе")

        path = Path(card["path"])
        if not path.exists():
            raise HTTPException(410, "Файл удалён или переименован")

        suffix = path.suffix.lower()
        media = INLINE_TYPES.get(suffix, "application/octet-stream")
        disposition = "attachment" if download or suffix not in INLINE_TYPES \
            else "inline"
        return FileResponse(path, media_type=media, filename=path.name,
                            content_disposition_type=disposition)

    @app.patch("/api/doc/{doc_id}")
    def api_edit(doc_id: int, values: dict = Body(...)) -> JSONResponse:
        """Ручная правка атрибутов. Она сильнее автоматического разбора и
        переживает переиндексацию: хранится отдельно, по пути файла."""
        conn = connect()
        try:
            card = db.card(conn, doc_id)
            if not card:
                raise HTTPException(404, "Документа нет в индексе")
            author = values.pop("edited_by", None)
            saved = db.set_override(conn, card["path"], values, author)
            if not saved:
                raise HTTPException(400, "Нечего сохранять")
            return JSONResponse(db.card(conn, doc_id))
        finally:
            conn.close()

    @app.delete("/api/doc/{doc_id}/override")
    def api_clear_override(doc_id: int) -> JSONResponse:
        """Снять ручную правку — атрибуты вернутся к разобранным."""
        conn = connect()
        try:
            card = db.card(conn, doc_id)
            if not card:
                raise HTTPException(404, "Документа нет в индексе")
            db.clear_override(conn, card["path"])
            indexer.reparse_one(conn, cfg, doc_id)
            return JSONResponse(db.card(conn, doc_id))
        finally:
            conn.close()

    @app.post("/api/refresh")
    def api_refresh() -> JSONResponse:
        """Проверить папку на новые и изменившиеся файлы.

        Обход инкрементальный: неизменившееся не перечитывается, поэтому
        по большому архиву это минуты, а не час.
        """
        conn = connect()
        try:
            stats = indexer.run(conn, cfg)
            return JSONResponse({
                "scanned": stats.scanned,
                "added": stats.added,
                "updated": stats.updated,
                "removed": stats.removed,
                "needs_ocr": stats.needs_ocr,
                "seconds": round(stats.seconds),
            })
        except FileNotFoundError as exc:
            raise HTTPException(503, f"Папка недоступна: {exc}")
        finally:
            conn.close()

    @app.get("/api/recent")
    def api_recent(limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
        """Недавно добавленные документы — очередь на проверку атрибутов."""
        conn = connect()
        try:
            return JSONResponse({"results": db.recent(conn, limit)})
        finally:
            conn.close()

    @app.get("/api/letter/draft")
    def api_letter_draft() -> JSONResponse:
        """Заготовка нового письма: номер и список адресатов из архива."""
        head = letters.Letterhead.from_config(cfg.letterhead)
        conn = connect()
        try:
            return JSONResponse({
                "number": letters.next_number(conn, head.number_prefix,
                                              head.number_folder),
                "number_after": letters.previous_number(
                    conn, head.number_prefix, head.number_folder),
                "date": date.today().isoformat(),
                "recipients": letters.recipients(conn),
                "signer_position": head.signer_position,
                "signer_name": head.signer_name,
                "letterhead": head.header_lines(),
                "intro_template": head.intro,
                "own_org": cfg.own_org or head.name,
                "object": head.object,
            })
        finally:
            conn.close()

    @app.post("/api/letter/contacts")
    def api_rebuild_contacts() -> JSONResponse:
        """Пересобрать справочник адресатов по переписке."""
        conn = connect()
        try:
            rows = letters.rebuild_contacts(conn)
            return JSONResponse({"found": len(rows)})
        finally:
            conn.close()

    @app.post("/api/letter")
    def api_letter(letter: dict = Body(...)) -> Response:
        """Собрать .docx и отдать на скачивание.

        В архив ничего не пишем: куда класть письмо, решает человек. Файл
        скачивается, правится и сохраняется в нужную папку обычным
        способом — следующий обход подхватит его сам.
        """
        head = letters.Letterhead.from_config(cfg.letterhead)
        if not head.name:
            raise HTTPException(400, "В конфиге не заполнен раздел letterhead")
        blob = letters.render(letter, head)
        name = letters.file_name(letter)
        quoted = quote(name)
        return Response(
            content=blob,
            media_type="application/vnd.openxmlformats-officedocument"
                       ".wordprocessingml.document",
            headers={"Content-Disposition":
                     f"attachment; filename*=UTF-8''{quoted}"},
        )

    @app.get("/api/stats")
    def api_stats() -> JSONResponse:
        conn = connect()
        try:
            return JSONResponse(db.stats(conn))
        finally:
            conn.close()

    return app
