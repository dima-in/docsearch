"""Починка слов, где кириллица подменилась похожей латиницей.

Tesseract на русских документах путает неотличимые по начертанию буквы:
РТП превращается в PTП, ВОДА в ВОDА. Для поиска это фатально — номер
письма «РТП-161» перестаёт находиться. Чиним только там, где сомнений
нет: слово преимущественно кириллическое, а вся латиница в нём —
двойники, у которых есть однозначная кириллическая пара.
"""
from __future__ import annotations

import re

# Латинские буквы, неотличимые по начертанию от кириллических
TWINS = {
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
}

WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+")
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
LATIN_RE = re.compile(r"[A-Za-z]")


def fix_word(word: str) -> str:
    latin = LATIN_RE.findall(word)
    if not latin:
        return word
    cyrillic = CYRILLIC_RE.findall(word)
    if not cyrillic:
        # слово целиком латинское — возможно, оно таким и задумано
        return word
    if len(cyrillic) <= len(latin):
        return word
    # если хоть одна латинская буква не двойник, слово настоящее смешанное
    if any(ch not in TWINS for ch in latin):
        return word
    return "".join(TWINS.get(ch, ch) for ch in word)


def fix(text: str) -> str:
    """Привести смешанные слова к кириллице."""
    if not text:
        return ""
    return WORD_RE.sub(lambda m: fix_word(m.group(0)), text)
