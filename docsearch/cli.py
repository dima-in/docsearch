"""Командная строка: survey / index / search / stats."""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

from . import config as config_mod
from . import db, extract, morph
from . import search as search_mod
from .indexer import run as run_index
from .walker import walk


def _fix_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _human(size: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ТБ"


# --------------------------------------------------------------------- survey

def cmd_survey(args) -> int:
    """Разведка: что вообще лежит в папке, до всякой индексации."""
    cfg = config_mod.load(args.config)
    roots = [r for r in cfg.roots if not args.root or r.label == args.root]
    if not roots:
        print(f"Неуспех: в конфиге нет корня «{args.root}»")
        return 1

    for root in roots:
        if not Path(root.path).exists():
            print(f"Неуспех: папка недоступна — {root.path}")
            return 1

        print(f"\nРазведка: {root.label} ({root.path})")
        counts: Counter = Counter()
        sizes: Counter = Counter()
        dir_counts: Counter = Counter()
        dir_sizes: Counter = Counter()
        pdfs: list[Path] = []
        total = 0
        root_path = Path(root.path)

        for path in walk(root.path, cfg):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            ext = path.suffix.lower() or "(без расширения)"
            counts[ext] += 1
            sizes[ext] += size
            # верхняя папка от корня: по ней выбирают, с чего начать
            try:
                parts = path.relative_to(root_path).parts
            except ValueError:
                parts = ()
            top = parts[0] if len(parts) > 1 else "(в корне)"
            dir_counts[top] += 1
            dir_sizes[top] += size
            total += 1
            if ext == ".pdf":
                pdfs.append(path)
            if total % 2000 == 0:
                print(f"  ...просмотрено {total}", end="\r", flush=True)

        print(f"  Файлов: {total}, объём: {_human(sum(sizes.values()))}    ")
        print(f"  {'расширение':<16}{'штук':>8}{'объём':>12}   индексация")
        for ext, cnt in counts.most_common(args.top):
            if ext in extract.HANDLERS:
                mode = "текст"
            elif ext in extract.NAME_ONLY:
                mode = "только имя"
            else:
                mode = "-"
            print(f"  {ext:<16}{cnt:>8}{_human(sizes[ext]):>12}   {mode}")

        if args.dirs and dir_counts:
            print()
            header = f"  {'папка верхнего уровня':<40}{'штук':>8}{'объём':>12}"
            print(header)
            for name, cnt in dir_counts.most_common(args.dirs):
                shown = name if len(name) <= 38 else name[:37] + "…"
                print(f"  {shown:<40}{cnt:>8}{_human(dir_sizes[name]):>12}")

        if pdfs and args.sample_pdf:
            sample = random.sample(pdfs, min(args.sample_pdf, len(pdfs)))
            need_ocr = 0
            failed = 0
            for path in sample:
                result = extract.extract(path)
                if result.status == "error":
                    failed += 1
                elif result.needs_ocr:
                    need_ocr += 1
            share = need_ocr / len(sample) * 100
            expected = int(len(pdfs) * need_ocr / len(sample))
            print(f"\n  PDF-проба ({len(sample)} шт.): без текстового слоя "
                  f"{need_ocr} ({share:.0f}%), не открылось {failed}")
            print(f"  => ожидаемо сканов среди всех PDF: ~{expected} из {len(pdfs)}")

    print("\nУспех: разведка закончена")
    return 0


# ---------------------------------------------------------------------- index

def cmd_index(args) -> int:
    cfg = config_mod.load(args.config)
    if not morph.available():
        print("Внимание: pymorphy3 не установлен — поиск будет строгим "
              "по словоформе (pip install pymorphy3 pymorphy3-dicts-ru)")
    conn = db.connect(cfg.db)
    print(f"Задача: проиндексировать корней {len(cfg.roots)} в {cfg.db}")

    def progress(st):
        print(f"  просмотрено {st.scanned}, разобрано {st.added + st.updated}, "
              f"без изменений {st.skipped}", end="\r", flush=True)

    try:
        stats = run_index(conn, cfg, progress=progress)
    except FileNotFoundError as exc:
        print(f"\nНеуспех: {exc}")
        return 1
    finally:
        conn.close()

    print(" " * 90, end="\r")
    print(f"Сделал: просмотрено {stats.scanned} файлов за {stats.seconds:.0f} с")
    print(f"  новых {stats.added}, обновлено {stats.updated}, "
          f"без изменений {stats.skipped}, удалено из индекса {stats.removed}")
    print(f"  пропущено: формат не поддержан {stats.unsupported}, "
          f"слишком большие {stats.too_big}")
    if stats.by_status:
        detail = ", ".join(f"{k} {v}" for k, v in sorted(stats.by_status.items()))
        print(f"  разбор: {detail}")
    if stats.needs_ocr:
        print(f"  требуют OCR (скан без текста): {stats.needs_ocr}")
    if stats.errors:
        print(f"Успех с оговоркой: {stats.errors} файл(ов) не открылись")
    else:
        print("Успех: индекс обновлён")
    return 0


# --------------------------------------------------------------------- search

def cmd_search(args) -> int:
    cfg = config_mod.load(args.config)
    conn = db.connect(cfg.db)
    filters = search_mod.Filters(
        ext=args.ext,
        root=args.root,
        doc_type=args.type,
        date_from=getattr(args, "from"),
        date_to=args.to,
    )
    rows = search_mod.search(conn, args.query, filters, limit=args.limit)
    if not rows:
        print(f"Неуспех: по запросу «{args.query}» ничего не найдено")
        conn.close()
        return 1

    print(f"Найдено (показаны {len(rows)}):\n")
    for i, row in enumerate(rows, 1):
        number = f"№{row['doc_number']}" if row["doc_number"] else None
        head = " · ".join(x for x in (row["doc_type"], number, row["doc_date"]) if x)
        print(f"{i}. {row['name']}")
        if head:
            print(f"   {head}")
        print(f"   {row['root']} / {row['rel_path']}")
        snippet = (row["snippet"] or "").replace("\n", " ").strip()
        if snippet:
            print(f"   {snippet}")
        if row["needs_ocr"]:
            print("   [скан без текстового слоя — найдено по имени и пути]")
        print()
    conn.close()
    return 0


# ---------------------------------------------------------------------- stats

def cmd_stats(args) -> int:
    cfg = config_mod.load(args.config)
    conn = db.connect(cfg.db)
    st = db.stats(conn)
    print(f"Документов в индексе: {st['total']}")
    print(f"Требуют OCR: {st['needs_ocr']}")
    print("\nПо статусу разбора:")
    for status, cnt in st["by_status"].items():
        print(f"  {status:<14}{cnt:>8}")
    print("\nПо расширению:")
    for ext, cnt in st["by_ext"]:
        print(f"  {ext:<14}{cnt:>8}")
    conn.close()
    return 0


# ------------------------------------------------------------------- problems

def cmd_problems(args) -> int:
    """Что поиск сейчас не видит и почему."""
    cfg = config_mod.load(args.config)
    conn = db.connect(cfg.db)
    rep = db.problems(conn, limit=args.limit)
    total = sum(rep["counts"].values())
    if not total:
        print("Индекс пуст — сначала docsearch index")
        conn.close()
        return 1

    ok = rep["counts"].get("ok", 0)
    print(f"Всего в индексе: {total}, с извлечённым текстом: {ok} "
          f"({ok / total * 100:.0f}%)")

    if rep["ocr_by_ext"]:
        print()
        print("Сканы без текстового слоя (нужен OCR):")
        for ext, cnt in rep["ocr_by_ext"]:
            print(f"  {ext:<10}{cnt:>7}")
        for row in rep["needs_ocr"]:
            print(f"    {_human(row['size']):>9}  {row['root']} / {row['rel_path']}")

    if rep["errors"]:
        print()
        print(f"Не открылись ({rep['counts'].get('error', 0)}):")
        for row in rep["errors"]:
            print(f"  {row['root']} / {row['rel_path']}")
            print(f"    {row['error']}")

    if rep["empty"]:
        print()
        print(f"Пустые после разбора ({rep['counts'].get('empty', 0)}):")
        for row in rep["empty"]:
            print(f"  {_human(row['size']):>9}  {row['root']} / {row['rel_path']}")

    name_only = rep["counts"].get("name_only", 0)
    if name_only:
        print()
        print(f"Только по имени и пути: {name_only} "
              f"(dwg, doc, xls, изображения, архивы)")

    conn.close()
    return 0

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="docsearch", description="Поиск по архиву документов"
    )
    p.add_argument("-c", "--config", default=None, help="путь к config.yaml")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("survey", help="разведка папки: что и в каких форматах лежит")
    s.add_argument("--root", help="метка корня из конфига")
    s.add_argument("--top", type=int, default=20, help="сколько расширений показать")
    s.add_argument("--sample-pdf", type=int, default=30,
                   help="сколько PDF проверить на текстовый слой (0 — не проверять)")
    s.add_argument("--dirs", type=int, default=15,
                   help="сколько папок верхнего уровня показать")
    s.set_defaults(func=cmd_survey)

    s = sub.add_parser("index", help="построить или обновить индекс")
    s.set_defaults(func=cmd_index)

    s = sub.add_parser("search", help="искать по индексу")
    s.add_argument("query", help="слова или фраза в кавычках")
    s.add_argument("--ext", help="фильтр по расширению, например .pdf")
    s.add_argument("--root", help="фильтр по корню")
    s.add_argument("--type", help="фильтр по типу документа, например акт")
    s.add_argument("--from", help="дата документа от, ГГГГ-ММ-ДД")
    s.add_argument("--to", help="дата документа до, ГГГГ-ММ-ДД")
    s.add_argument("-n", "--limit", type=int, default=20)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("stats", help="что сейчас в индексе")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("problems", help="что поиск не видит и почему")
    s.add_argument("-n", "--limit", type=int, default=15,
                   help="сколько файлов показать в каждой категории")
    s.set_defaults(func=cmd_problems)
    return p


def main(argv: list[str] | None = None) -> int:
    _fix_console()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
