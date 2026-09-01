"""Поиск по индексу.

Запрос лемматизируется и уходит в колонку lemmas, поэтому «поставка щебня»
находит «поставку щебня» и «поставок щебня». Текст в кавычках ищется как
точная фраза по исходному тексту.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from . import morph, snippet as snippet_mod

RE_PHRASE = re.compile(r'"([^"]+)"')

# Имя файла весит больше текста: попадание в название почти всегда точнее
BM25_WEIGHTS = "10.0, 1.0, 3.0"


@dataclass
class Filters:
    ext: str | None = None
    root: str | None = None
    doc_type: str | None = None
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


def search(
    conn: sqlite3.Connection,
    query: str,
    filters: Filters | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    filters = filters or Filters()
    match = build_match_query(query)
    if not match:
        return []

    where = ["doc_fts MATCH ?"]
    params: list = [match]
    if filters.ext:
        where.append("d.ext = ?")
        params.append(filters.ext.lower())
    if filters.root:
        where.append("d.root = ?")
        params.append(filters.root)
    if filters.doc_type:
        where.append("d.doc_type = ?")
        params.append(filters.doc_type)
    if filters.date_from:
        where.append("d.doc_date >= ?")
        params.append(filters.date_from)
    if filters.date_to:
        where.append("d.doc_date <= ?")
        params.append(filters.date_to)

    sql = f"""
        SELECT d.id, d.path, d.rel_path, d.name, d.ext, d.size, d.root,
               d.doc_type, d.doc_number, d.doc_date, d.counterparty,
               d.object_code, d.status, d.needs_ocr,
               doc_fts.body AS body,
               bm25(doc_fts, {BM25_WEIGHTS}) AS score
        FROM doc_fts
        JOIN documents d ON d.id = doc_fts.rowid
        WHERE {' AND '.join(where)}
        ORDER BY score
        LIMIT ? OFFSET ?
    """
    params += [limit, offset]

    rows = []
    for record in conn.execute(sql, params):
        row = dict(record)
        # сниппет считаем сами: FTS5 показал бы совпадение в колонке лемм
        row["snippet"] = snippet_mod.make(row.pop("body") or "", query)
        rows.append(row)
    return rows


def count(conn: sqlite3.Connection, query: str, filters: Filters | None = None) -> int:
    match = build_match_query(query)
    if not match:
        return 0
    row = conn.execute(
        "SELECT COUNT(*) c FROM doc_fts JOIN documents d ON d.id = doc_fts.rowid"
        " WHERE doc_fts MATCH ?",
        (match,),
    ).fetchone()
    return row["c"]
