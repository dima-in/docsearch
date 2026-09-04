"""Извлечение атрибутов документа: тип, номер, дата, контрагент, шифр.

Работаем по правилам, а не по модели: имя файла, путь и шапка документа
дают на типовых бланках ПТО большую часть попаданий, при этом всё
считается локально и ничего никуда не отправляется.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import morph

# Смотрим только в шапку: дальше пойдут даты из тела и номера пунктов
HEAD_CHARS = 1500

# Типы документов. Порядок важен: сначала узкие, потом общие, иначе
# «акт о приёмке выполненных работ» станет просто актом, а не КС-2.
# Сравнение идёт по леммам, поэтому «акта» и «акты» опознаются, а «факт»
# и «фактический» — нет.
DOC_TYPES = [
    ("КС-2", ("кс-2", "акт о приемке выполненных работ",
              "акт о приёмке выполненных работ")),
    ("КС-3", ("кс-3", "справка о стоимости выполненных работ")),
    ("акт скрытых работ", ("акт освидетельствования скрытых работ", "аоср")),
    ("доп. соглашение", ("дополнительное соглашение", "допсоглашение")),
    ("техзадание", ("техническое задание", "тз на")),
    ("записка", ("пояснительная записка",)),
    ("ППР", ("проект производства работ", "ппр")),
    ("сертификат", ("сертификат соответствия", "сертификат")),
    ("паспорт", ("паспорт качества", "паспорт изделия", "технический паспорт")),
    ("декларация", ("декларация о соответствии", "декларация соответствия")),
    ("протокол испытаний", ("протокол испытаний", "протокол сертификационных испытаний")),
    ("счет", ("счет-фактура", "счёт-фактура", "счет на оплату",
              "универсальный передаточный документ")),
    ("график", ("график производства работ", "календарный график",
                "график выполнения")),
    ("журнал", ("журнал работ", "общий журнал работ")),
    ("смета", ("смета", "сметный расчет", "сметный расчёт",
               "локальный сметный")),
    ("предписание", ("предписание",)),
    ("претензия", ("претензия",)),
    ("уведомление", ("уведомление",)),
    ("приказ", ("приказ",)),
    ("распоряжение", ("распоряжение",)),
    ("заключение", ("заключение",)),
    ("спецификация", ("спецификация",)),
    ("накладная", ("накладная",)),
    ("ведомость", ("ведомость",)),
    ("регламент", ("регламент", "технологический регламент")),
    ("инструкция", ("инструкция",)),
    ("отчет", ("отчет", "отчёт")),
    ("реестр", ("реестр",)),
    ("договор", ("договор", "контракт")),
    ("протокол", ("протокол",)),
    ("справка", ("справка",)),
    ("акт", ("акт",)),
    # «исх» и «вх» — так подписано большинство писем в именах файлов
    ("письмо", ("письмо", "исх", "вх", "исходящий", "входящий", "уважаемый")),
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

# Организация в шапке документа: ООО «ФБ-СТРОЙ», АО МостСтрой.
# Форма в кавычках надёжнее — её и проверяем первой.
FORMS = "ООО|ОАО|ЗАО|ПАО|АО|ИП|ГУП|МУП|ФГУП|ФГБУ|АНО|НКО"

# Между формой и названием бывает аббревиатура: ООО КБ «Маренго»
RE_ORG_QUOTED = re.compile(
    r"\b(" + FORMS + r")\s*(?:[А-ЯЁ]{2,4}\s*)?[«\"']([^»\"']{2,60})[»\"']", re.IGNORECASE
)
# Название не переносится на другую строку: иначе «ООО ТеплоСети» плюс
# следующая строка «Объект:» склеиваются в несуществующую организацию
RE_ORG_PLAIN = re.compile(
    r"\b(" + FORMS + r")[ \t]+([А-ЯЁ][\w\-]{1,30}(?:[ \t]+[А-ЯЁ][\w\-]{1,30}){0,2})"
)
RE_ORG = re.compile(r"\b(" + FORMS + r")\b", re.IGNORECASE)

# Слова, которые идут сразу за формой собственности и организацией не являются
ORG_NOISE = {"и", "в", "от", "на", "по", "для", "при"}


# Типографские тире и минусы, которые встречаются вместо обычного дефиса
DASHES = {0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-",
          0x2212: "-"}


def normalize_org(form: str, name: str) -> str:
    """Привести к единому виду: ООО «Маренго».

    Тире выравниваем: «ПД‐ПРОЕКТ» с типографским дефисом и «ПД-ПРОЕКТ» с
    обычным — одна организация, а в отчёте выглядели как две.
    """
    name = " ".join(name.translate(DASHES).split()).strip(" .,;:-")
    return f"{form.upper()} «{name}»"


def find_organizations(text: str, limit: int = 6) -> list[str]:
    """Организации, упомянутые в шапке документа, в порядке появления.

    Первой обычно идёт та, чей это бланк, дальше — адресат. Дубликаты
    убираем, сохраняя порядок.
    """
    found: list[str] = []
    for match in RE_ORG_QUOTED.finditer(text):
        org = normalize_org(match.group(1), match.group(2))
        if org not in found:
            found.append(org)
    for match in RE_ORG_PLAIN.finditer(text):
        # «ООО КБ «Маренго»» уже разобран формой в кавычках — не плодим
        # из его начала отдельную организацию «ООО КБ»
        tail = text[match.end():match.end() + 2].lstrip()
        if tail[:1] in ("«", chr(34), "'"):
            continue
        name = match.group(2)
        if name.split()[0].lower() in ORG_NOISE:
            continue
        org = normalize_org(match.group(1), name)
        # без кавычек название могло уже попасться в кавычках
        if org not in found and not any(org.split("«")[1][:8] in f for f in found):
            found.append(org)
    return found[:limit]


def pick_counterparty(orgs: list[str], own: str | None) -> str | None:
    """Контрагент — первая организация, которая не наша.

    В исходящем письме собственный бланк стоит первым, и без этого
    отсева контрагентом у половины архива оказались бы мы сами.
    """
    if not orgs:
        return None
    if not own:
        return orgs[0]
    needle = own.strip().lower()
    for org in orgs:
        if needle and needle in org.lower():
            continue
        return org
    return None


def find_counterparty(rel_path: str) -> str | None:
    """Контрагент — папка с признаком организации, иначе ближайшая
    неслужебная папка выше файла."""
    parts = [p for p in Path(rel_path).parent.parts if p not in (".", "")]
    for part in reversed(parts):
        if RE_ORG.search(part):
            # приводим к тому же виду, что и организации из текста, иначе
            # «ООО СтройМонтаж» и «ООО «СтройМонтаж»» будут двумя разными
            found = find_organizations(part)
            return found[0] if found else part
    # Прежде здесь возвращалась «последняя неслужебная папка», и в отчёт
    # попадали «Новая папка», «DWG», «Фото», «Балки». Лучше честно ничего,
    # чем мусор, который выглядит как контрагент
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


_type_rules: list[tuple[str, list[list[str]]]] = []


def _rules() -> list[tuple[str, list[list[str]]]]:
    """Ключевые слова в начальных формах. Считаем один раз: словари
    морфологии поднимаются небыстро."""
    global _type_rules
    if not _type_rules:
        _type_rules = [
            (label, [morph.lemmatize(key).split() for key in keys])
            for label, keys in DOC_TYPES
        ]
    return _type_rules


def _contains(haystack: list[str], needle: list[str]) -> bool:
    """Идёт ли последовательность слов подряд внутри другой."""
    if not needle:
        return False
    span = len(needle)
    return any(haystack[i:i + span] == needle
               for i in range(len(haystack) - span + 1))


def find_doc_type(*sources: str) -> str | None:
    """Тип документа по ключевым словам.

    Сравниваем по леммам, а не по подстроке: «акт» — подстрока слова
    «факт», и «Факт. адрес» в шапке письма делал из него акт.
    """
    for source in sources:
        if not source:
            continue
        words = morph.lemmatize(source).split()
        if not words:
            continue
        for label, keys in _rules():
            if any(_contains(words, key) for key in keys):
                return label
    return None


def find_object_code(text: str) -> str | None:
    m = RE_OBJECT.search(text)
    return m.group(1) if m else None


def guess(path: Path, rel_path: str, text: str,
          own_org: str | None = None) -> dict:
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
        # организация из шапки документа надёжнее имени папки: папки в
        # архиве названы по фамилиям и разделам, а не по контрагентам
        "counterparty": (pick_counterparty(find_organizations(head), own_org)
                         or find_counterparty(rel_path)),
        "organizations": find_organizations(head),
    }
