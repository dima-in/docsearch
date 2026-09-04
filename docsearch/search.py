"""Поиск по индексу.

Запрос лемматизируется и уходит в колонку lemmas, поэтому «поставка щебня»
находит «поставку щебня» и «поставок щебня». Текст в кавычках ищется как
точная фраза по исходному тексту.

Запрос может быть и пустым: тогда работают одни фильтры, и это просмотр
архива по категориям, а не поиск.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from . import morph, snippet as snippet_mod

RE_PHRASE = re.compile(r'"([^"]+)"')

# Имя файла весит больше текста: попадание в название почти всегда точнее
BM25_WEIGHTS = "10.0, 1.0, 3.0"

WITH_QUERY = "doc_fts JOIN documents d ON d.id = doc_fts.rowid"
WITHOUT_QUERY = "documents d"

FIELDS = ("d.id, d.path, d.rel_path, d.name, d.ext, d.size, d.root,"
          " d.doc_type, d.doc_number, d.doc_date, d.counterparty,"
          " d.object_code, d.status, d.needs_ocr")


@dataclass
class Filters:
    ext: str | None = None
    root: str | None = None
    doc_type: str | None = None
    counterparty: str | None = None
    year: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    include_ocr_pending: bool = True


def _quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def build_match_query(user_query: str) -> str:
    """Пользовательский запрос -> выражение для FTS5 MATCH."""
    phrases = RE_PHRASE.findall(user_query)
    rest = RE_PHRASE.sub(" ", user_query)

    clauses = []
    words = morph.tokenize(rest)
    if words:
        lemmas = " AND ".join(_quote(morph.lemma(w)) for w in words)
        clauses.append(f"lemmas : ({lemmas})")
    for phrase in phrases:
        if phrase.strip():
            clauses.append(f"body : ({_quote(phrase.strip())})")
    return " AND ".join(clauses)


def conditions(query: str, filters: Filters | None = None) -> tuple[str, str, list]:
    """Источник, условия отбора и параметры к ним.

    Один код для выдачи, счётчика и подсчёта по категориям — иначе
    «найдено», показанное и цифры в боковой панели разойдутся.
    """
    filters = filters or Filters()
    where: list[str] = []
    params: list = []

    match = build_match_query(query) if query and query.strip() else ""
    if match:
        source = WITH_QUERY
        where.append("doc_fts MATCH ?")
        params.append(match)
    else:
        source = WITHOUT_QUERY

    if filters.ext:
        where.append("d.ext = ?")
        params.append(filters.ext.lower())
    if filters.root:
        where.append("d.root = ?")
        params.append(filters.root)
    if filters.doc_type:
        where.append("d.doc_type = ?")
        params.append(filters.doc_type)
    if filters.counterparty:
        # по части названия: «маренго» должно находить «ООО «КБ Маренго»»
        where.append("ru_lower(d.counterparty) LIKE ?")
        params.append(f"%{filters.counterparty.lower()}%")
    if filters.year:
        where.append("substr(d.doc_date, 1, 4) = ?")
        params.append(str(filters.year))
    if filters.date_from:
        where.append("d.doc_date >= ?")
        params.append(filters.date_from)
    if filters.date_to:
        where.append("d.doc_date <= ?")
        params.append(filters.date_to)

    return source, " AND ".join(where) if where else "1 = 1", params


def has_criteria(query: str, filters: Filters | None = None) -> bool:
    """Есть ли вообще что отбирать: пустой запрос без фильтров — не поиск."""
    source, where, _ = conditions(query, filters)
    return not (source == WITHOUT_QUERY and where == "1 = 1")


def search(
    conn: sqlite3.Connection,
    query: str,
    filters: Filters | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    if not has_criteria(query, filters):
        return []
    source, where, params = conditions(query, filters)

    if source == WITH_QUERY:
        order = f"bm25(doc_fts, {BM25_WEIGHTS})"
        extra = f", doc_fts.body AS body, {order} AS score"
    else:
        # без поискового запроса ранжировать нечем — свежее идёт первым
        order = "d.doc_date DESC, d.name"
        extra = ""

    sql = f"""
        SELECT {FIELDS}{extra}
        FROM {source}
        WHERE {where}
        ORDER BY {order}
        LIMIT ? OFFSET ?
    """
    rows = []
    for record in conn.execute(sql, params + [limit, offset]):
        row = dict(record)
        # сниппет считаем сами: FTS5 показал бы совпадение в колонке лемм
        body = row.pop("body", None)
        row["snippet"] = snippet_mod.make(body or "", query) if body else ""
        row.pop("score", None)
        rows.append(row)
    return rows


def count(conn: sqlite3.Connection, query: str,
          filters: Filters | None = None) -> int:
    """Сколько всего документов подходит — с учётом тех же фильтров."""
    if not has_criteria(query, filters):
        return 0
    source, where, params = conditions(query, filters)
    row = conn.execute(
        f"SELECT COUNT(*) c FROM {source} WHERE {where}", params
    ).fetchone()
    return row["c"]
