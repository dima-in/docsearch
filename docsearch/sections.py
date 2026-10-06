"""Раздел архива — крупная группировка поверх мелких типов документов.

Тридцать три типа хороши для точного фильтра, но бесполезны, когда в
выдаче вперемешку лежат двухсотстраничный альбом РД и скан письма на
одну страницу. Раздел отвечает на вопрос «что это вообще за документ»,
и по нему выдачу можно развести одним щелчком.

Порядок решения важен: тип документа точнее пути, путь точнее
расширения. Письмо, лежащее в папке проекта, остаётся перепиской.
"""
from __future__ import annotations

from pathlib import Path

CORRESPONDENCE = "переписка"
PROJECT = "проектная документация"
EXECUTIVE = "исполнительная"
QUALITY = "качество материалов"
CONTRACTS = "договоры и финансы"
ORGANIZATIONAL = "организационные"
PHOTOS = "фотоматериалы"
OTHER = "прочее"

ORDER = [CORRESPONDENCE, EXECUTIVE, PROJECT, QUALITY, CONTRACTS,
         ORGANIZATIONAL, PHOTOS, OTHER]

# Тип документа -> раздел
BY_TYPE = {
    "письмо": CORRESPONDENCE,
    "уведомление": CORRESPONDENCE,
    "претензия": CORRESPONDENCE,
    "предписание": CORRESPONDENCE,

    "акт": EXECUTIVE,
    "акт скрытых работ": EXECUTIVE,
    "КС-2": EXECUTIVE,
    "КС-3": EXECUTIVE,
    "журнал": EXECUTIVE,
    "ведомость": EXECUTIVE,
    "реестр": EXECUTIVE,

    "сертификат": QUALITY,
    "паспорт": QUALITY,
    "декларация": QUALITY,
    "протокол испытаний": QUALITY,

    "договор": CONTRACTS,
    "доп. соглашение": CONTRACTS,
    "смета": CONTRACTS,
    "счет": CONTRACTS,
    "накладная": CONTRACTS,
    "спецификация": CONTRACTS,

    "протокол": ORGANIZATIONAL,
    "приказ": ORGANIZATIONAL,
    "распоряжение": ORGANIZATIONAL,
    "заключение": ORGANIZATIONAL,
    "справка": ORGANIZATIONAL,
    "техзадание": ORGANIZATIONAL,
    "записка": ORGANIZATIONAL,
    "ППР": ORGANIZATIONAL,
    "график": ORGANIZATIONAL,
    "регламент": ORGANIZATIONAL,
    "инструкция": ORGANIZATIONAL,
    "отчет": ORGANIZATIONAL,
}

# Кусок пути -> раздел. Проверяется сверху вниз, первое совпадение
# побеждает, поэтому узкие правила стоят выше общих.
BY_PATH = [
    (CORRESPONDENCE, ("переписка", "письма", "входящие", "исходящие")),
    (QUALITY, ("сертификат", "паспорта и сертификат", "качеств")),
    (PROJECT, ("проекты", "п и рд", "проектная", "чертеж", "чертёж",
               "альбом", "изыскания")),
    (EXECUTIVE, ("исполнительн", "аоср", "акты", "кс-2", "кс-3")),
    (PHOTOS, ("фото", "фотофиксаци", "съемка", "съёмка")),
    (CONTRACTS, ("договор", "сметы", "счета", "финанс")),
]

BY_EXT = {
    ".dwg": PROJECT,
    ".dxf": PROJECT,
    ".jpg": PHOTOS,
    ".jpeg": PHOTOS,
    ".png": PHOTOS,
    ".tif": PHOTOS,
    ".tiff": PHOTOS,
    ".jfif": PHOTOS,
}


def from_path(rel_path: str) -> str | None:
    low = rel_path.lower().replace("\\", "/")
    for section, keys in BY_PATH:
        if any(key in low for key in keys):
            return section
    return None


def classify(doc_type: str | None, rel_path: str, ext: str,
             extra_rules: dict | None = None) -> str:
    """Раздел документа: сначала по типу, потом по пути, потом по формату."""
    if doc_type and doc_type in BY_TYPE:
        return BY_TYPE[doc_type]

    if extra_rules:
        low = rel_path.lower().replace("\\", "/")
        for section, keys in extra_rules.items():
            if any(str(key).lower() in low for key in keys):
                return section

    by_path = from_path(rel_path)
    if by_path:
        return by_path

    return BY_EXT.get(ext.lower(), OTHER)


def sort_key(section: str) -> int:
    """Порядок разделов в панели — по тому, как часто в них лезут."""
    return ORDER.index(section) if section in ORDER else len(ORDER)


def guess_for(path: Path, rel_path: str, doc_type: str | None,
              extra_rules: dict | None = None) -> str:
    return classify(doc_type, rel_path, path.suffix, extra_rules)
