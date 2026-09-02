"""Интерактивный поиск: запрос за запросом, без перезапуска.

Каждый запуск командной строки заново поднимает словари морфологии —
это пара секунд, и при работе «поискал, посмотрел, поискал ещё» они
складываются в раздражение. Здесь словари грузятся один раз.

Отсюда же документ открывается в своей программе: путь к файлу на
сетевой папке руками не набирают.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from . import db
from . import search as search_mod

HELP = """
Команды:
  <слова>        искать; фраза в кавычках ищется точно
  о3  или  o3    открыть третий документ из выдачи
  т3  или  t3    показать текст третьего документа
  п3  или  p3    показать папку с третьим документом
  ещё  или  +    следующая страница выдачи
  ?              эта справка
  в  или  q      выход

Примеры:
  задержка поставки арматуры
  "акт освидетельствования скрытых работ"
  огнезащита ГКМ
"""

# латиница и кириллица: раскладку переключать ради одной буквы не станут
OPEN_KEYS = ("o", "о")
TEXT_KEYS = ("t", "т")
FOLDER_KEYS = ("p", "п")
QUIT_WORDS = {"q", "в", "quit", "exit", "выход"}
MORE_WORDS = {"ещё", "еще", "more", "+", "далее"}


def parse_action(line: str) -> tuple[str, int] | None:
    """Разобрать «о3» / «t 12» в действие и номер результата."""
    text = line.strip().lower().replace(" ", "")
    if len(text) < 2:
        return None
    head, tail = text[0], text[1:]
    if not tail.isdigit():
        return None
    if head in OPEN_KEYS:
        return "open", int(tail)
    if head in TEXT_KEYS:
        return "text", int(tail)
    if head in FOLDER_KEYS:
        return "folder", int(tail)
    return None


def open_path(path: Path) -> str | None:
    """Открыть файл в программе по умолчанию. Возвращает описание ошибки."""
    if not path.exists():
        return "файла больше нет по этому пути"
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(path))            # Windows
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
        return None
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"


def show_folder(path: Path) -> str | None:
    """Открыть проводник на папке с файлом и выделить его."""
    try:
        if sys.platform == "win32":
            subprocess.run(["explorer", "/select,", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path.parent)], check=False)
        return None
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"


def print_results(rows: list[dict], start: int = 1) -> None:
    for i, row in enumerate(rows, start):
        number = f"№{row['doc_number']}" if row["doc_number"] else None
        head = " · ".join(
            x for x in (row["doc_type"], number, row["doc_date"],
                        row["counterparty"]) if x
        )
        mark = " [скан]" if row["needs_ocr"] else ""
        print(f"{i}. {row['name']}{mark}")
        if head:
            print(f"   {head}")
        print(f"   {row['root']} / {row['rel_path']}")
        snippet = (row["snippet"] or "").replace("\n", " ").strip()
        if snippet:
            print(f"   {snippet}")
        print()


def run(conn: sqlite3.Connection, limit: int = 10) -> int:
    print("Поиск по архиву. «?» — справка, «в» — выход.")
    total_docs = db.stats(conn)["total"]
    print(f"В индексе документов: {total_docs}")

    rows: list[dict] = []
    query = ""
    shown = 0
    found = 0

    def report() -> None:
        """Сколько всего нашлось и сколько из этого видно — без этой строки
        человек думает, что документов в архиве всего десяток."""
        if found <= shown:
            print(f"Найдено: {found}")
        else:
            print(f"Найдено: {found}, показаны {shown - len(rows) + 1}–{shown}. "
                  f"«ещё» — следующие {limit}")

    while True:
        try:
            line = input("\nпоиск> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not line:
            continue
        if line.lower() in QUIT_WORDS:
            return 0
        if line in ("?", "help", "справка"):
            print(HELP)
            continue

        if line.lower() in MORE_WORDS:
            if not query:
                print("Сначала что-нибудь найдите")
                continue
            if shown >= found:
                print("Это была последняя страница")
                continue
            rows = search_mod.search(conn, query, limit=limit, offset=shown)
            shown += len(rows)
            print()
            print_results(rows, start=shown - len(rows) + 1)
            report()
            continue

        action = parse_action(line)
        if action:
            what, number = action
            if not rows:
                print("Сначала что-нибудь найдите")
                continue
            first = shown - len(rows) + 1
            if not first <= number <= shown:
                print(f"На экране номера {first}–{shown}, {number} не подходит")
                continue
            row = rows[number - first]
            path = Path(row["path"])
            if what == "open":
                error = open_path(path)
                print(f"Неуспех: {error}" if error else f"Открываю: {row['name']}")
            elif what == "folder":
                error = show_folder(path)
                print(f"Неуспех: {error}" if error
                      else f"Показываю в проводнике: {path.parent}")
            else:
                body = db.body(conn, row["id"])
                print("-" * 70)
                print(body[:4000] if body else "(текста нет)")
                if len(body) > 4000:
                    print(f"... ещё {len(body) - 4000} символов")
            continue

        query = line
        found = search_mod.count(conn, query)
        rows = search_mod.search(conn, query, limit=limit)
        shown = len(rows)
        if not rows:
            print(f"Ничего не найдено по запросу «{query}»")
            continue
        print()
        print_results(rows, start=1)
        report()
