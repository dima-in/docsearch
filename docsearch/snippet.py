"""Сниппеты: кусок текста вокруг найденного слова.

Штатный snippet() из FTS5 здесь не помогает: совпадение происходит в
колонке лемм, а показывать надо исходный текст. Поэтому проходим по телу
документа сами и сравниваем леммы слов — тогда «щебень» из запроса
подсветит «щебня» в тексте, где обрезка основы уже не спасает.
"""
from __future__ import annotations

from . import morph

WINDOW = 120        # символов слева и справа от совпадения
MAX_SCAN = 30_000   # дальше по телу документа не ищем — незачем


def _match_spans(body: str, lemmas: set[str]) -> list[tuple[int, int]]:
    """Позиции слов, чья лемма есть в запросе."""
    spans = []
    for m in morph.TOKEN_RE.finditer(body):
        word = m.group(0).lower()
        if len(word) > 1 and morph.lemma(word) in lemmas:
            spans.append((m.start(), m.end()))
    return spans


def make(body: str, query: str, open_mark: str = "[", close_mark: str = "]") -> str:
    """Вернуть фрагмент вокруг первого совпадения с подсветкой всех совпадений."""
    if not body:
        return ""
    wanted = {morph.lemma(t) for t in morph.tokenize(query)}
    haystack = body[:MAX_SCAN]
    spans = _match_spans(haystack, wanted) if wanted else []

    if not spans:
        # совпало только по имени файла или пути — показываем начало документа
        return " ".join(body[: WINDOW * 2].split())

    start = max(0, spans[0][0] - WINDOW)
    end = min(len(haystack), spans[0][0] + WINDOW)

    # собираем фрагмент, вставляя подсветку по позициям
    parts = []
    cursor = start
    for span_start, span_end in spans:
        if span_start < cursor or span_end > end:
            continue
        parts.append(haystack[cursor:span_start])
        parts.append(open_mark + haystack[span_start:span_end] + close_mark)
        cursor = span_end
    parts.append(haystack[cursor:end])
    fragment = "".join(parts)

    # не рвём слова на краях
    if start > 0:
        cut = fragment.find(" ")
        if cut > 0:
            fragment = fragment[cut + 1:]
    if end < len(haystack):
        cut = fragment.rfind(" ")
        if cut > 0:
            fragment = fragment[:cut]

    text = " ".join(fragment.split())
    prefix = "… " if start > 0 else ""
    suffix = " …" if end < len(haystack) else ""
    return f"{prefix}{text}{suffix}"
