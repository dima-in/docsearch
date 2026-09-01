"""Извлечение атрибутов документа: тип, номер, дата, контрагент, шифр.

Работаем по правилам, а не по модели: имя файла, путь и шапка документа
дают на типовых бланках ПТО большую часть попаданий, при этом всё
считается локально и ничего никуда не отправляется.
"""
from __future__ import annotations

import re
from pathlib import Path

# Смотрим только в шапку: дальше пойдут даты из тела и номера пунктов
HEAD_CHARS = 1500

DOC_TYPES = [
    ("акт", ("акт",)),
    ("протокол", ("протокол",)),
    ("письмо", ("письмо", "исх.", "вх.", "уважаем")),
    ("договор", ("договор", "контракт")),
    ("доп. соглашение", ("дополнительное соглашение", "допсоглашение")),
    ("смета", ("смета", "сметный расчет", "сметный расчёт")),
    ("ведомость", ("ведомость",)),
    ("справка", ("справка",)),
    ("приказ", ("приказ",)),
    ("распоряжение", ("распоряжение",)),
    ("заключение", ("заключение",)),
    ("спецификация", ("спецификация",)),
    ("накладная", ("накладная",)),
    ("счет", ("счет-фактура", "счёт-фактура", "счет на оплату")),
    ("техзадание", ("техническое задание", "тех. задание", "тз на")),
    ("записка", ("пояснительная записка",)),
    ("график", ("график производства", "календарный график")),
    ("журнал", ("журнал работ", "общий журнал")),
]

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11,
    "декабря": 12,
}

RE_NUM_LABELLED = re.compile(
    r"(?:исх|вх|рег)\.?\s*(?:№|N[oº]?|#)\s*([0-9][^\s,;]{0,24})", re.IGNORECASE
)
RE_NUM_PLAIN = re.compile(r"(?:№|N[oº])\s*([0-9][^\s,;]{0,24})")
RE_DATE_NUM = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})\b")
RE_DATE_WORD = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", re.IGNORECASE
)
RE_OBJECT = re.compile(
    r"шифр\w*\s*[:\-]?\s*([A-ZА-Я0-9][\w\-./]{2,30})", re.IGNORECASE
)

# Папки, которые заведомо не контрагент, а раздел делопроизводства
GENERIC_FOLDERS = {
    "письма", "акты", "протоколы", "договоры", "сметы", "чертежи", "входящие",
    "исходящие", "документы", "прочее", "разное", "архив", "сканы", "отчеты",
    "отчёты", "переписка", "приказы", "справки", "ведомости",
}

RE_ORG = re.compile(r"\b(ООО|АО|ЗАО|ПАО|ОАО|ИП|ГУП|МУП|ФГУП)\b", re.IGNORECASE)


def find_counterparty(rel_path: str) -> str | None:
    """Контрагент — папка с признаком организации, иначе ближайшая
    неслужебная папка выше файла."""
    parts = [p for p in Path(rel_path).parent.parts if p not in (".", "")]
    for part in reversed(parts):
        if RE_ORG.search(part):
            return part
    for part in reversed(parts):
        if part.lower() not in GENERIC_FOLDERS and not part.isdigit():
            return part
    return None


def _norm_date(day: str, month: str, year: str) -> str | None:
    d, m = int(day), int(month)
    y = int(year)
    if y < 100:
        y += 2000 if y < 70 else 1900
    if not (1 <= d <= 31 and 1 <= m <= 12 and 1900 <= y <= 2100):
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def find_date(text: str) -> str | None:
    m = RE_DATE_WORD.search(text)
    if m:
        return _norm_date(m.group(1), str(MONTHS[m.group(2).lower()]), m.group(3))
    m = RE_DATE_NUM.search(text)
    if m:
        return _norm_date(m.group(1), m.group(2), m.group(3))
    return None


def find_number(text: str) -> str | None:
    m = RE_NUM_LABELLED.search(text) or RE_NUM_PLAIN.search(text)
    return m.group(1).rstrip(".,;") if m else None


def find_doc_type(*sources: str) -> str | None:
    for source in sources:
        low = source.lower()
        for label, keys in DOC_TYPES:
            if any(k in low for k in keys):
                return label
    return None


def find_object_code(text: str) -> str | None:
    m = RE_OBJECT.search(text)
    return m.group(1) if m else None


def guess(path: Path, rel_path: str, text: str) -> dict:
    """Собрать атрибуты из имени файла, пути и шапки текста."""
    head = text[:HEAD_CHARS]
    name = path.stem
    folders = str(Path(rel_path).parent).replace("\\", " / ")

    return {
        # тип ищем сначала в имени файла — оно обычно честнее шапки
        "doc_type": find_doc_type(name, folders, head),
        "doc_number": find_number(name) or find_number(head),
        "doc_date": find_date(name) or find_date(head),
        "object_code": find_object_code(head) or find_object_code(folders),
        "counterparty": find_counterparty(rel_path),
    }
