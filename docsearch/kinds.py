"""Какие документы лежат в папке: виды, сколько каждого, где свежий образец.

Нужно перед тем, как делать шаблоны. В папке «Акты» лежат не одни акты
одного вида: передача документации, приёмка, разбивка осей, допуск —
и по именам файлов этого не понять, они названы как попало. Здесь вид
берётся из заголовка в самом документе: первая строка, где сказано, что
это такое, с отброшенными номерами и датами.

Выдаются только заголовки и пути, без содержимого: отчёт можно вынести
с рабочей машины и показать, не вынося сами документы.
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePath

# с чего начинается заголовок документа
HEADS = ("акт", "протокол", "реестр", "опись", "ведомость", "справка",
         "журнал", "заключение", "предписание", "уведомление", "приказ",
         "перечень", "спецификация", "накладная", "схема", "заявка")

HEAD_LINE = re.compile(r"^\s*(" + "|".join(HEADS) + r")\b", re.IGNORECASE)
# хвост заголовка, который у каждого документа свой
NUMBER = re.compile(r"(№|n[o°]?\.?)\s*[\w\-/.]*", re.IGNORECASE)
DATE = re.compile(r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b")
YEAR = re.compile(r"\b(19|20)\d{2}\s*(г\.?|года)?")
MONTHS = ("января|февраля|марта|апреля|мая|июня|июля|августа|сентября|"
          "октября|ноября|декабря")
WORD_DATE = re.compile(r"«?\s*\d{1,2}\s*»?\s*(" + MONTHS + r")", re.IGNORECASE)
DIGITS = re.compile(r"\d+")
JUNK = re.compile(r"[«»\"'“”„()\[\]_]+")
SPACES = re.compile(r"\s+")

# заголовок длиннее — это уже не заголовок, а абзац
MAX_TITLE = 90
LOOK_LINES = 25


@dataclass
class Kind:
    title: str
    count: int = 0
    no_text: int = 0
    exts: Counter = field(default_factory=Counter)
    first: str | None = None
    last: str | None = None
    example: str | None = None
    example_when: str = ""

    def add(self, row: dict, when: str, has_text: bool) -> None:
        self.count += 1
        self.exts[row["ext"]] += 1
        if not has_text:
            self.no_text += 1
        if when:
            self.first = min(self.first or when, when)
            self.last = max(self.last or when, when)
        # образец — самый свежий из тех, где есть текст: по нему и
        # делать шаблон, старые бланки могли смениться
        if has_text and when >= self.example_when:
            self.example, self.example_when = row["rel_path"], when


def _clean(text: str) -> str:
    text = text.replace("ё", "е").replace("Ё", "Е")
    for pattern in (NUMBER, DATE, WORD_DATE, YEAR):
        text = pattern.sub(" ", text)
    text = DIGITS.sub(" ", JUNK.sub(" ", text))
    text = SPACES.sub(" ", text).strip(" .,:;-–—")
    # «акт от» после вырезанной даты
    text = re.sub(r"\s+(от|г)$", "", text)
    return text.lower()


def title_from_text(text: str) -> str | None:
    """Вид документа по его заголовку.

    Заголовок часто разбит на строки: «АКТ» на одной, «приёма-передачи
    документации» на следующей. Короткую строку склеиваем со следующей.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for i, line in enumerate(lines[:LOOK_LINES]):
        if not HEAD_LINE.match(line):
            continue
        title = line
        rest = lines[i + 1:i + 3]
        # «АКТ №» или «АКТ» — продолжение на следующей строке
        while rest and len(_clean(title).split()) < 3:
            title = f"{title} {rest.pop(0)}"
        cleaned = _clean(title)
        if cleaned and len(cleaned) <= MAX_TITLE:
            return cleaned
    return None


def title_from_name(name: str) -> str:
    stem = PurePath(name).stem.replace("_", " ")
    cleaned = _clean(stem)[:MAX_TITLE].strip()
    return cleaned or "(без названия)"


def collect(conn: sqlite3.Connection, folder: str) -> tuple[list[Kind], Counter, int]:
    """Виды документов в папке, число в подпапках и сколько всего."""
    pattern = f"%{folder.lower()}%"
    rows = conn.execute(
        "SELECT d.id, d.rel_path, d.name, d.ext, d.doc_date, d.mtime, "
        "       f.body AS body "
        "FROM documents d LEFT JOIN doc_fts f ON f.rowid = d.id "
        "WHERE ru_lower(d.rel_path) LIKE ?",
        (pattern,),
    ).fetchall()

    kinds: dict[str, Kind] = {}
    folders: Counter = Counter()
    for row in rows:
        row = dict(row)
        body = row.pop("body") or ""
        title = title_from_text(body)
        has_text = bool(body.strip())
        if not title:
            title = title_from_name(row["name"])
        when = row["doc_date"] or datetime.fromtimestamp(row["mtime"]).date().isoformat()
        kinds.setdefault(title, Kind(title)).add(row, when, has_text)
        folders[_subfolder(row["rel_path"], folder)] += 1

    ordered = sorted(kinds.values(), key=lambda k: (-k.count, k.title))
    return ordered, folders, len(rows)


def _subfolder(rel_path: str, folder: str) -> str:
    """Подпапка сразу под искомой — чтобы увидеть, как папка устроена."""
    parts = PurePath(rel_path).parts[:-1]
    for i, part in enumerate(parts):
        if folder.lower() in part.lower():
            below = parts[i + 1:i + 2]
            return below[0] if below else "(в самой папке)"
    return "/".join(parts[:2]) or "(в корне)"


def _files(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} файл"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} файла"
    return f"{n} файлов"


def report(kinds: list[Kind], folders: Counter, total: int, folder: str,
           limit: int = 40) -> str:
    if not total:
        return (f"Неуспех: в индексе нет файлов, в пути которых есть «{folder}». "
                "Проверьте написание — достаточно части названия папки")

    lines = [f"Папка «{folder}»: {_files(total)}, видов документов {len(kinds)}.", ""]
    lines.append("Подпапки:")
    for name, count in folders.most_common(15):
        lines.append(f"  {count:>6}  {name}")
    if len(folders) > 15:
        lines.append(f"  …и ещё {len(folders) - 15}")
    lines.append("")
    lines.append("Виды документов, от частых к редким:")
    for kind in kinds[:limit]:
        exts = ", ".join(f"{e} {n}" for e, n in kind.exts.most_common(3))
        span = ""
        if kind.first and kind.last:
            span = kind.first[:4] if kind.first[:4] == kind.last[:4] \
                else f"{kind.first[:4]}–{kind.last[:4]}"
        lines.append(f"  {kind.count:>6}  {kind.title}")
        details = [d for d in (exts, span) if d]
        if kind.no_text:
            details.append(f"без текста {kind.no_text}")
        lines.append(f"          {' · '.join(details)}")
        if kind.example:
            lines.append(f"          образец: {kind.example}")
    if len(kinds) > limit:
        rest = sum(k.count for k in kinds[limit:])
        lines.append(f"  …и ещё {len(kinds) - limit} видов, в них {_files(rest)}."
                     " Больше — с флагом -n")
    return "\n".join(lines)
