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
