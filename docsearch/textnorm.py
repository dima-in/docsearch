"""Нормализация текста после извлечения.

PDF и Word отдают текст с неразрывными пробелами, мягкими переносами и
невидимыми служебными символами. Если их не убрать, поиск фразы и
подсветка совпадений начинают беспричинно промахиваться.
"""
from __future__ import annotations

import re
import unicodedata

# Символы, которые не несут смысла, но ломают сравнение строк
INVISIBLE = dict.fromkeys(
    [
        0x00AD,  # мягкий перенос
        0x200B,  # zero-width space
        0x200C,  # zero-width non-joiner
        0x200D,  # zero-width joiner
        0xFEFF,  # BOM
    ]
)

RE_SPACES = re.compile(r"[^\S\n]+")   # любые пробельные, кроме перевода строки
RE_BLANK_LINES = re.compile(r"\n{3,}")


def normalize(text: str) -> str:
    if not text:
        return ""
    text = text.translate(INVISIBLE)
    # NFKC схлопывает совместимые формы: лигатуры, неразрывные пробелы
    text = unicodedata.normalize("NFKC", text)
    text = RE_SPACES.sub(" ", text)
    text = RE_BLANK_LINES.sub("\n\n", text)
    return text.strip()
