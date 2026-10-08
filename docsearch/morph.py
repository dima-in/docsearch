"""Лемматизация: приводим слова к начальной форме, чтобы запрос
«договор» находил «договоров», «договору» и так далее.

pymorphy3 необязателен: без него всё работает, но поиск становится
строгим по словоформе.
"""
from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)

_analyzer = None
_cache: dict[str, str] = {}
_unavailable = False


def _get_analyzer():
    global _analyzer, _unavailable
    if _analyzer is None and not _unavailable:
        try:
            import pymorphy3

            _analyzer = pymorphy3.MorphAnalyzer()
        except Exception:
            _unavailable = True
    return _analyzer


def available() -> bool:
    return _get_analyzer() is not None


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text) if len(t) > 1]


def lemma(word: str) -> str:
    hit = _cache.get(word)
    if hit is not None:
        return hit
    analyzer = _get_analyzer()
    if analyzer is None:
        result = word
    else:
        try:
            result = analyzer.parse(word)[0].normal_form
        except Exception:
            result = word
    # словарь запросто вырастает на большом архиве — держим в узде
    if len(_cache) < 200_000:
        _cache[word] = result
    return result


def lemmatize(text: str) -> str:
    """Строка исходного текста -> строка лемм через пробел."""
    return " ".join(lemma(t) for t in tokenize(text))


_surname_cache: dict[str, str] = {}


def surname(word: str) -> str:
    """Начальная форма фамилии.

    Обычная лемматизация тут промахивается: «Глоба» она принимает за
    прилагательное, «Давтяну» — за глагол. Поэтому среди разборов берём
    тот, что помечен фамилией, иначе существительное.
    """
    word = (word or "").lower().strip()
    if not word:
        return ""
    hit = _surname_cache.get(word)
    if hit is not None:
        return hit

    analyzer = _get_analyzer()
    result = word
    if analyzer is not None:
        try:
            parses = analyzer.parse(word)
            best = next((p for p in parses if "Surn" in p.tag), None)
            if best is None:
                best = next((p for p in parses if p.tag.POS == "NOUN"), None)
            if best is not None:
                result = best.normal_form
        except Exception:
            result = word
    if len(_surname_cache) < 50_000:
        _surname_cache[word] = result
    return result
