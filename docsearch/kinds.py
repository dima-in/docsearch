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

import hashlib
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePath

# с чего начинается заголовок документа
HEADS = ("акт", "протокол", "реестр", "опись", "ведомость", "справка",
         "журнал", "заключение", "предписание", "уведомление", "приказ",
         "перечень", "спецификация", "накладная", "схема", "заявка",
         "сертификат", "паспорт", "декларация")

# перед заголовком бывает номер пункта: «(16.3) Акт приёмки…»
HEAD_LINE = re.compile(r"^\s*(\(?[\d.]+\)?\.?\s*)?(" + "|".join(HEADS) + r")\b",
                       re.IGNORECASE)
# хвост заголовка, который у каждого документа свой. Латинское N — только
# перед цифрой, иначе съедается любая латиница
# «№РОСС RU.32437.04ЛБК0.ОС04.00469» — номер в несколько слов: берём
# следом все слова, где есть цифра
NUMBER = re.compile(r"(№|\bN[o°]?\.?(?=\s*\d))\s*\S*(?:\s+(?=\S*\d)\S+)*",
                    re.IGNORECASE)
# строка под заголовком «г. Москва  «12» мая 2025 г.» — место и дата,
# а не предмет акта
PLACE = re.compile(r"^(г\.|г\s|город\b|москва\b)", re.IGNORECASE)
DATE = re.compile(r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b")
YEAR = re.compile(r"\b(19|20)\d{2}\s*(г\.?|года)?")
MONTHS = ("января|февраля|марта|апреля|мая|июня|июля|августа|сентября|"
          "октября|ноября|декабря")
# «12» мая, и «__» мая в незаполненном бланке
WORD_DATE = re.compile(r"«?\s*[\d_]{0,2}\s*»?\s*\b(" + MONTHS + r")\b",
                       re.IGNORECASE)
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
    # точки и дефисы, оставшиеся от вырезанных номеров: «ru. . лбк .ос .»
    text = re.sub(r"(?<=\s)[.\-/,]+(?=\s|$)", " ", text)
    text = SPACES.sub(" ", text).strip(" .,:;-–—")
    text = re.sub(r"\s+(от|г)$", "", text)
    return text.lower()


def title_from_text(text: str) -> str | None:
    """Вид документа по его заголовку.

    Заголовок часто разбит на строки: «АКТ» на одной, «приёма-передачи
    документации» на следующей. Короткую строку склеиваем со следующей,
    пропуская место и дату. Акт ищем в первую очередь: «Заключение:»
    внизу акта приёмки — не заголовок документа, а его раздел.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    head = lines[:LOOK_LINES]
    matches = [(i, m.group(2).lower()) for i, line in enumerate(head)
               if (m := HEAD_LINE.match(line))]
    order = [i for i, word in matches if word == "акт"] + \
            [i for i, word in matches if word != "акт"]
    for i in order:
        title = HEAD_LINE.sub(lambda m: m.group(2), lines[i], count=1)
        # «Заключение: вышеуказанное оборудование…» — дальше уже текст
        title = title.split(":")[0]
        rest = [line for line in lines[i + 1:i + 5]
                if _clean(line) and not PLACE.match(_clean(line))][:2]
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


# — выгрузка текстов ———————————————————————————————————————————

DUMP_CHARS = 8000           # акт — страница-три; дальше обычно приложения
RULE = "=" * 72


@dataclass
class Dumped:
    text: str
    written: int = 0
    duplicates: int = 0
    no_text: int = 0
    kinds: Counter = field(default_factory=Counter)


def _fingerprint(body: str) -> str:
    """Один и тот же акт часто лежит дважды: в папке и в «Подписанных».
    Сравниваем текст без пробелов и регистра."""
    return hashlib.sha1(SPACES.sub("", body).lower().encode("utf-8")).hexdigest()


def dump(conn: sqlite3.Connection, folder: str, kind: str | None = None,
         exts: list[str] | None = None, limit: int | None = None,
         chars: int = DUMP_CHARS) -> Dumped:
    """Тексты документов из папки одним файлом — читать подряд и сравнивать.

    Порядок — по виду, внутри вида по дате: так рядом оказываются акты
    одного бланка, и видно, что в них меняется, а что стоит постоянно.
    """
    pattern = f"%{folder.lower()}%"
    rows = conn.execute(
        "SELECT d.rel_path, d.name, d.ext, d.doc_date, d.mtime, f.body AS body "
        "FROM documents d LEFT JOIN doc_fts f ON f.rowid = d.id "
        "WHERE ru_lower(d.rel_path) LIKE ?",
        (pattern,),
    ).fetchall()

    wanted_exts = {e.lower() if e.startswith(".") else f".{e.lower()}"
                   for e in exts or []}
    wanted_kind = (kind or "").lower().replace("ё", "е").strip()
    result = Dumped(text="")
    picked = []
    seen: set[str] = set()
    for row in rows:
        if wanted_exts and row["ext"].lower() not in wanted_exts:
            continue
        body = (row["body"] or "").strip()
        title = title_from_text(body) or title_from_name(row["name"])
        if wanted_kind and wanted_kind not in title:
            continue
        if not body:
            result.no_text += 1
            continue
        mark = _fingerprint(body)
        if mark in seen:
            result.duplicates += 1
            continue
        seen.add(mark)
        when = row["doc_date"] or \
            datetime.fromtimestamp(row["mtime"]).date().isoformat()
        picked.append((title, when, row["rel_path"], body))

    picked.sort(key=lambda item: item[:3])
    if limit:
        picked = picked[:limit]

    parts = []
    for title, when, rel_path, body in picked:
        result.kinds[title] += 1
        cut = body[:chars]
        tail = f"\n[… обрезано, всего {len(body)} знаков]" if len(body) > chars else ""
        parts.append(f"{RULE}\nвид: {title}\nфайл: {rel_path}\nдата: {when}\n"
                     f"{RULE}\n{cut}{tail}\n")
    result.written = len(picked)

    head = [f"Папка «{folder}»"
            + (f", вид «{kind}»" if kind else "")
            + (f", форматы {', '.join(sorted(wanted_exts))}" if wanted_exts else "")
            + f": {_files(result.written)}.",
            f"Повторов пропущено: {result.duplicates}. "
            f"Без текста (не распознаны): {result.no_text}.",
            "",
            "Виды:"]
    head += [f"  {n:>5}  {t}" for t, n in result.kinds.most_common()]
    result.text = "\n".join(head) + "\n\n" + "\n".join(parts)
    return result
