"""Генератор исходящих писем.

Смысл делать это именно здесь, а не в отдельной программе: индекс уже
знает архив. Из него берутся следующий свободный номер, список
контрагентов и ссылки на прежнюю переписку — то, что в Word пришлось бы
искать руками.

Результат — .docx, а не PDF. Письмо почти всегда правят перед отправкой,
потом печатают, подписывают и сканируют обратно в архив.
"""
from __future__ import annotations

import io
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from . import db

# «РТП-175», «Исх. № 12/ПТО» — из номера вытаскиваем префикс и цифру
RE_NUMBER = re.compile(r"^\s*(?P<prefix>[^\d\s]*?)[\s-]*(?P<digits>\d+)")

MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


@dataclass
class Letterhead:
    """Бланк организации. Берётся из конфига целиком."""
    name: str = ""
    legal_address: str = ""
    actual_address: str = ""
    ogrn: str = ""
    inn: str = ""
    kpp: str = ""
    fax: str = ""
    phone: str = ""
    email: str = ""
    signer_position: str = ""
    signer_name: str = ""
    number_prefix: str = ""
    template: str = ""
    extra_lines: list = field(default_factory=list)

    @classmethod
    def from_config(cls, raw: dict | None) -> "Letterhead":
        raw = raw or {}
        return cls(
            name=raw.get("name", ""),
            legal_address=raw.get("legal_address", ""),
            actual_address=raw.get("actual_address", ""),
            ogrn=str(raw.get("ogrn", "")),
            inn=str(raw.get("inn", "")),
            kpp=str(raw.get("kpp", "")),
            fax=raw.get("fax", ""),
            phone=raw.get("phone", ""),
            email=raw.get("email", ""),
            signer_position=raw.get("signer_position", ""),
            signer_name=raw.get("signer_name", ""),
            number_prefix=raw.get("number_prefix", ""),
            template=raw.get("template", ""),
            extra_lines=list(raw.get("extra_lines", [])),
        )

    def header_lines(self) -> list[str]:
        """Строки шапки сверху листа, пустые отбрасываем."""
        lines = [self.name]
        if self.legal_address:
            lines.append(f"Юр. адрес: {self.legal_address}")
        if self.actual_address and self.actual_address != self.legal_address:
            lines.append(f"Факт. адрес: {self.actual_address}")
        requisites = " ".join(
            part for part in (f"ОГРН {self.ogrn}" if self.ogrn else "",
                              f"ИНН {self.inn}" if self.inn else "",
                              f"КПП {self.kpp}" if self.kpp else "") if part
        )
        if requisites:
            lines.append(requisites)
        contacts = "   ".join(
            part for part in (f"Тел.: {self.phone}" if self.phone else "",
                              f"Факс: {self.fax}" if self.fax else "",
                              self.email) if part
        )
        if contacts:
            lines.append(contacts)
        lines.extend(self.extra_lines)
        return [line for line in lines if line]


def parse_number(value: str) -> tuple[str, int] | None:
    """«РТП-175» -> («РТП», 175). Нужен, чтобы продолжить нумерацию."""
    if not value:
        return None
    match = RE_NUMBER.match(value)
    if not match:
        return None
    prefix = match.group("prefix").strip(" .№-")
    return prefix, int(match.group("digits"))


# Один документ с кривым номером не должен задирать нумерацию: в архиве
# есть сканы, где распознавание приписало лишнюю цифру. Номер считаем
# выбросом, если до ближайшего снизу больше этого разрыва.
MAX_GAP = 100
# По двум-трём номерам выброс не определить: редкая нумерация с большими
# разрывами — тоже нормальная нумерация
MIN_SAMPLE = 5


def numbers_for(conn: sqlite3.Connection, prefix: str) -> list[int]:
    """Все номера с этим префиксом, по возрастанию."""
    wanted = prefix.strip().lower()
    found = []
    for row in conn.execute(
        "SELECT doc_number FROM documents"
        " WHERE doc_number IS NOT NULL AND doc_number != ''"
    ):
        parsed = parse_number(row["doc_number"])
        if not parsed:
            continue
        found_prefix, number = parsed
        if found_prefix.lower() == wanted:
            found.append(number)
    return sorted(found)


def highest_sane(numbers: list[int], max_gap: int = MAX_GAP) -> int:
    """Наибольший номер, вокруг которого есть соседи.

    Идём сверху вниз и пропускаем значения, оторвавшиеся от остальных:
    одинокая 19095 среди номеров около 1300 — это испорченная цифра, а не
    достигнутый рубеж нумерации.
    """
    if not numbers:
        return 0
    if len(numbers) < MIN_SAMPLE:
        return numbers[-1]
    for i in range(len(numbers) - 1, 0, -1):
        if numbers[i] - numbers[i - 1] <= max_gap:
            return numbers[i]
    return numbers[0]


def next_number(conn: sqlite3.Connection, prefix: str) -> str:
    """Следующий свободный номер по этому префиксу.

    Максимум берём из самого архива: журнал исходящих вести отдельно
    никто не станет, а письма в папке — это и есть журнал.
    """
    highest = highest_sane(numbers_for(conn, prefix))
    return f"{prefix}-{highest + 1}" if prefix else str(highest + 1)


def previous_number(conn: sqlite3.Connection, prefix: str) -> str:
    """От какого номера считается следующий — чтобы ошибку было видно сразу."""
    highest = highest_sane(numbers_for(conn, prefix))
    if not highest:
        return ""
    return f"{prefix}-{highest}" if prefix else str(highest)


def known_recipients(conn: sqlite3.Connection, limit: int = 100) -> list[str]:
    """Контрагенты, которым уже писали, — по убыванию переписки."""
    rows = conn.execute(
        "SELECT counterparty, COUNT(*) c FROM documents"
        " WHERE counterparty IS NOT NULL AND counterparty != ''"
        " GROUP BY ru_lower(counterparty) ORDER BY c DESC LIMIT ?",
        (limit,),
    )
    return [r["counterparty"] for r in rows]


def ru_date(value: str | None = None) -> str:
    """ГГГГ-ММ-ДД -> «19 марта 2024 г.»"""
    today = date.today()
    if value:
        try:
            year, month, day = (int(part) for part in value.split("-"))
            today = date(year, month, day)
        except (ValueError, TypeError):
            pass
    return f"{today.day} {MONTHS_GENITIVE[today.month - 1]} {today.year} г."


def build_docx(letter: dict, head: Letterhead) -> bytes:
    """Собрать .docx. Без шаблона-бланка: верстаем программно.

    Когда появится настоящий бланк организации в Word, сюда подставится
    он, а поля останутся теми же.
    """
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    document = docx.Document()
    style = document.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)

    def paragraph(text: str = "", *, align=None, bold=False, size=None,
                  space_after=6):
        item = document.add_paragraph()
        item.paragraph_format.space_after = Pt(space_after)
        if align is not None:
            item.alignment = align
        run = item.add_run(text)
        run.bold = bold
        if size:
            run.font.size = Pt(size)
        return item

    for line in head.header_lines():
        paragraph(line, align=WD_ALIGN_PARAGRAPH.CENTER, size=10,
                  bold=line == head.name, space_after=0)
    paragraph(space_after=12)

    number_line = []
    if letter.get("number"):
        number_line.append(f"Исх. № {letter['number']}")
    number_line.append(f"от {ru_date(letter.get('date'))}")
    paragraph("   ".join(number_line), space_after=0)
    if letter.get("reference"):
        paragraph(f"На № {letter['reference']}", space_after=12)
    else:
        paragraph(space_after=12)

    for line in (letter.get("recipient_position"), letter.get("recipient_org"),
                 letter.get("recipient_person")):
        if line:
            paragraph(line, align=WD_ALIGN_PARAGRAPH.RIGHT, space_after=0)
    paragraph(space_after=12)

    if letter.get("subject"):
        paragraph(f"Тема: {letter['subject']}", bold=True, space_after=12)

    greeting = letter.get("greeting") or "Уважаемые коллеги!"
    paragraph(greeting, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=12)

    for block in (letter.get("body") or "").split("\n"):
        paragraph(block.strip(), align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                  space_after=6)

    paragraph(space_after=18)
    position = letter.get("signer_position") or head.signer_position
    signer = letter.get("signer_name") or head.signer_name
    if position or signer:
        line = document.add_paragraph()
        line.add_run(position)
        line.add_run("\t\t" + signer)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def file_name(letter: dict) -> str:
    """Имя файла по тем же правилам, по каким названы письма в архиве."""
    parts = []
    if letter.get("number"):
        parts.append(f"Исх {letter['number']}")
    if letter.get("date"):
        year, month, day = letter["date"].split("-")
        parts.append(f"от {day}.{month}.{year}")
    if letter.get("subject"):
        parts.append(letter["subject"][:60])
    name = " ".join(parts) or "Письмо"
    for bad in ('/', chr(92), ':', '*', '?', '"', '<', '>', '|'):
        name = name.replace(bad, "-")
    return name.strip() + ".docx"


def register(conn: sqlite3.Connection, path: str, letter: dict) -> None:
    """Запомнить атрибуты сгенерированного письма.

    Когда файл попадёт в архив и его подберёт обход, атрибуты будут не
    угаданы разбором, а взяты ровно те, что человек ввёл.
    """
    db.set_override(conn, path, {
        "section": "переписка",
        "doc_type": "письмо",
        "doc_number": letter.get("number"),
        "doc_date": letter.get("date"),
        "counterparty": letter.get("recipient_org"),
        "note": letter.get("subject"),
    }, author=letter.get("author"))


# ---------------------------------------------------------------- шаблон

PLACEHOLDER = re.compile(r"{{\s*(\w+)\s*}}")


def _set_text(paragraph, text: str) -> None:
    """Заменить текст абзаца, сохранив оформление.

    Word дробит текст на прогоны где попало, поэтому заменять по месту
    нельзя: подстановка может оказаться разрезанной пополам. Пишем всё в
    первый прогон, остальные опустошаем — оформление берётся от первого.
    """
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(text)
        return
    runs[0].text = text
    for extra in runs[1:]:
        extra.text = ""


def _fill(paragraph, context: dict) -> None:
    text = paragraph.text
    if "{{" not in text:
        return
    filled = PLACEHOLDER.sub(lambda m: str(context.get(m.group(1), "") or ""),
                             text)
    _set_text(paragraph, filled)


def _expand_body(paragraph, body: str) -> None:
    """Многострочный текст письма — несколько абзацев с тем же оформлением."""
    import copy

    lines = [line.strip() for line in (body or "").split(chr(10))]
    lines = [line for line in lines if line] or [""]

    _set_text(paragraph, lines[0])
    anchor = paragraph._element
    for line in lines[1:]:
        clone = copy.deepcopy(paragraph._element)
        anchor.addnext(clone)
        anchor = clone
        from docx.text.paragraph import Paragraph

        _set_text(Paragraph(clone, paragraph._parent), line)


def render_template(template_path: str, letter: dict, head: Letterhead) -> bytes:
    """Заполнить бланк организации. Вёрстка, логотип и поля берутся из него."""
    import docx
    from docx.text.paragraph import Paragraph

    document = docx.Document(template_path)
    context = dict(letter)
    context.setdefault("greeting", "Уважаемые коллеги!")
    context["date"] = ru_date(letter.get("date"))
    context.setdefault("signer_position", head.signer_position)
    context.setdefault("signer_name", head.signer_name)
    for key in ("signer_position", "signer_name"):
        context[key] = context.get(key) or getattr(head, key)

    body_text = context.pop("body", "")

    def walk(parent):
        for paragraph in parent.paragraphs:
            if "{{body}}" in paragraph.text or "{{ body }}" in paragraph.text:
                _expand_body(paragraph, body_text)
            else:
                _fill(paragraph, context)
        for table in parent.tables:
            for row in table.rows:
                for cell in row.cells:
                    walk(cell)

    walk(document)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def render(letter: dict, head: Letterhead) -> bytes:
    """Письмо на бланке, если он задан, иначе простая программная вёрстка."""
    from pathlib import Path

    if head.template and Path(head.template).exists():
        return render_template(head.template, letter, head)
    return build_docx(letter, head)


# ------------------------------------------------------- справочник адресатов

# «Генеральному директору», «Начальнику ПТО», «Главному инженеру»
RE_POSITION = re.compile(
    r"^\s*(?:(?:Вр\.?\s*и\.?\s*о\.?|И\.?\s*о\.?)\s*)?"
    r"(Генеральному|Исполнительному|Техническому|Финансовому|Коммерческому|"
    r"Главному|Первому|Заместителю|Директору|Руководителю|Начальнику|"
    r"Управляющему)\b.{0,60}$",
    re.IGNORECASE,
)

# «Севрюкову Е.В.» — фамилия в дательном падеже и инициалы
RE_PERSON = re.compile(
    r"^\s*([А-ЯЁ][а-яё\-]{2,30})\s+([А-ЯЁ]\.\s?[А-ЯЁ]\.?)\s*$"
)

LOOKAHEAD = 4   # сколько строк просматривать вокруг должности


def parse_addressee(text: str) -> dict | None:
    """Вытащить блок «кому» из текста письма.

    В исходящих он стоит справа сверху тремя строками: должность,
    организация, фамилия с инициалами. Это и есть готовая карточка
    адресата — заводить справочник руками не нужно.
    """
    from . import meta

    lines = [line.strip() for line in (text or "")[:HEAD_LIMIT].split(chr(10))]
    lines = [line for line in lines if line]

    for i, line in enumerate(lines):
        if not RE_POSITION.match(line):
            continue
        window = lines[i:i + LOOKAHEAD]
        org = None
        person = None
        for candidate in window[1:]:
            if org is None:
                found = meta.find_organizations(candidate)
                if found:
                    org = found[0]
                    continue
            match = RE_PERSON.match(candidate)
            if match:
                person = f"{match.group(1)} {match.group(2)}"
                break
        if org:
            return {"position": line, "org": org, "person": person}
    return None


HEAD_LIMIT = 1500


def rebuild_contacts(conn, progress=None) -> list[dict]:
    """Собрать справочник адресатов, пройдя по переписке.

    Побеждает самое свежее письмо: должности меняются, и писать надо
    тому, кто занимает её сейчас.
    """
    found: dict[str, dict] = {}
    seen = 0
    for row in db.correspondence_bodies(conn):
        seen += 1
        if progress and seen % 500 == 0:
            progress(seen, len(found))
        parsed = parse_addressee(row["body"] or "")
        if not parsed:
            continue
        org = parsed["org"]
        entry = found.setdefault(org, {
            "org": org, "position": None, "person": None,
            "letters": 0, "last_date": None,
        })
        entry["letters"] += 1
        # письма идут от свежих к старым, поэтому первое и есть актуальное
        if entry["position"] is None:
            entry["position"] = parsed["position"]
            entry["person"] = parsed["person"]
            entry["last_date"] = row["doc_date"]

    rows = sorted(found.values(), key=lambda e: -e["letters"])
    db.save_contacts(conn, rows)
    return rows


def recipients(conn) -> list[dict]:
    """Адресаты для формы письма. Если справочник пуст — собрать на месте."""
    known = db.contacts(conn)
    if not known:
        rebuild_contacts(conn)
        known = db.contacts(conn)
    if known:
        return known
    # переписки ещё нет — предложим хотя бы контрагентов из архива
    return [{"org": org, "position": None, "person": None, "letters": 0}
            for org in known_recipients(conn)]
