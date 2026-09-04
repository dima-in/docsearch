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
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import db
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
        type: str = "",
        org: str = "",
        year: str = "",
        ext: str = "",
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=100),
    ) -> JSONResponse:
        filters = search_mod.Filters(
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

    @app.get("/api/stats")
    def api_stats() -> JSONResponse:
        conn = connect()
        try:
            return JSONResponse(db.stats(conn))
        finally:
            conn.close()

    return app
