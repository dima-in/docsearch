"""Дообработка документов: распознавание сканов и чтение старых форматов.

Индексация только помечает такие файлы — их содержимое достаётся дольше
и отдельными средствами. Здесь собрано то, что одинаково нужно и консоли,
и кнопке в браузере: как сохранить добытый текст и пересчитать по нему
атрибуты.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

from . import db, homoglyph, meta, morph, textnorm
from .config import Config

OFFICE_EXTS = (".doc", ".xls")


def _attributes(cfg: Config, row: dict, text: str, overrides: dict) -> dict:
    attrs = meta.guess(Path(row["path"]), row["rel_path"], text,
                       cfg.own_org, cfg.section_rules)
    attrs.pop("organizations", None)
    return db.apply_override(attrs, overrides.get(row["path"], {}))


def _searchable(row: dict, text: str) -> str:
    return chr(10).join([row["name"], row["rel_path"], text])


def store_ocr_text(conn: sqlite3.Connection, cfg: Config, row: dict,
                   raw: str) -> bool:
    """Сохранить распознанный текст. False — если распозналось пусто."""
    text = homoglyph.fix(textnorm.normalize(raw))[: cfg.max_text_chars]
    if not text:
        db.fail_ocr(conn, row["id"], "распознано пусто")
        return False
    db.save_ocr(conn, row["id"], row["name"], text,
                morph.lemmatize(_searchable(row, text)))
    return True


def store_office_text(conn: sqlite3.Connection, cfg: Config, row: dict,
                      raw: str, overrides: dict) -> bool:
    """Сохранить текст из старого формата вместе с атрибутами по нему."""
    text = textnorm.normalize(raw)[: cfg.max_text_chars]
    if not text:
        db.fail_office(conn, row["id"], "текста в файле нет")
        return False
    attrs = _attributes(cfg, row, text, overrides)
    db.save_office(conn, row["id"], row["name"], text,
                   morph.lemmatize(_searchable(row, text)), attrs)
    return True


def pending(conn: sqlite3.Connection) -> dict:
    """Сколько документов ждут распознавания и чтения через Office."""
    scans = len(db.docs_for_ocr(conn, exts=[".pdf"]))
    legacy = len(db.docs_for_office(conn, list(OFFICE_EXTS)))
    return {"ocr": scans, "office": legacy, "total": scans + legacy}


def process_office(conn: sqlite3.Connection, cfg: Config,
                   limit: int = 20) -> dict:
    """Прочитать порцию старых форматов через установленный Office."""
    from . import office

    rows = db.docs_for_office(conn, list(OFFICE_EXTS), limit=limit)
    if not rows:
        return {"done": 0, "failed": 0}

    kinds = {office.kind_for(r["ext"]) for r in rows} - {None}
    office.check(kinds)

    meta.set_aliases(cfg.org_aliases)
    overrides = db.overrides_map(conn)
    work = Path(tempfile.mkdtemp(prefix="docsearch-web-office-"))
    done = failed = 0
    try:
        for kind in kinds:
            batch = [r for r in rows if office.kind_for(r["ext"]) == kind]
            items = [{
                "id": r["id"], "src": r["path"],
                "dst": str(work / f"{r['id']}{office.CONVERTED[r['ext']]}"),
            } for r in batch]
            results = office.convert_batch(items, kind)

            for row in batch:
                target = work / f"{row['id']}{office.CONVERTED[row['ext']]}"
                outcome = results.get(row["id"], {})
                if not outcome.get("ok") or not target.exists():
                    db.fail_office(conn, row["id"],
                                   outcome.get("error") or "Office не открыл файл")
                    failed += 1
                    continue
                if store_office_text(conn, cfg, row,
                                     office.extract_converted(target), overrides):
                    done += 1
                else:
                    failed += 1
                target.unlink(missing_ok=True)
        conn.commit()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"done": done, "failed": failed}


def process_ocr(conn: sqlite3.Connection, cfg: Config,
                limit: int = 10) -> dict:
    """Распознать порцию сканов. Порция маленькая: это долго."""
    from . import ocr as ocr_mod

    rows = db.docs_for_ocr(conn, limit=limit, exts=[".pdf"])
    if not rows:
        return {"done": 0, "failed": 0}

    lang = cfg.ocr.get("lang") or ocr_mod.DEFAULT_LANG
    dpi = int(cfg.ocr.get("dpi") or ocr_mod.DEFAULT_DPI)
    max_pages = int(cfg.ocr.get("max_pages") or 40)
    cmd = ocr_mod.check(lang)

    done = failed = 0
    for row in rows:
        result = ocr_mod.recognize(Path(row["path"]), cmd, lang=lang, dpi=dpi,
                                   max_pages=max_pages)
        if result.error:
            db.fail_ocr(conn, row["id"], result.error)
            failed += 1
        elif store_ocr_text(conn, cfg, row, result.text):
            done += 1
        else:
            failed += 1
    conn.commit()
    return {"done": done, "failed": failed}
