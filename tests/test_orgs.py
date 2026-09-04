"""Организации: извлечение из шапки, свой бланк, фильтр по части названия."""
from __future__ import annotations

from pathlib import Path

from docsearch import db, indexer, meta
from docsearch import search as search_mod

LETTERHEAD = """ООО «ФБ-СТРОЙ»
Юр. адрес: 141014, Московская область, г. Мытищи

Генеральному директору
ООО «Конструкторское Бюро Маренго»

Между ООО «ФБ-СТРОЙ» и ООО КБ «Маренго» заключен договор подряда.
"""


def test_finds_organizations_in_order():
    orgs = meta.find_organizations(LETTERHEAD)
    assert orgs[0] == "ООО «ФБ-СТРОЙ»"
    assert "ООО «Конструкторское Бюро Маренго»" in orgs


def test_abbreviation_before_name_does_not_create_ghost():
    """«ООО КБ «Маренго»» не должно превращаться в организацию «ООО КБ»."""
    assert "ООО «КБ»" not in meta.find_organizations(LETTERHEAD)


def test_name_does_not_run_onto_next_line():
    text = "Подрядчик: ООО ТеплоСети" + chr(10) + "Объект: Котельная-3"
    assert meta.find_organizations(text) == ["ООО «ТеплоСети»"]


def test_own_organization_is_skipped():
    orgs = meta.find_organizations(LETTERHEAD)
    assert meta.pick_counterparty(orgs, "ФБ-СТРОЙ").startswith("ООО «Конструкторское")
    assert meta.pick_counterparty(orgs, None) == "ООО «ФБ-СТРОЙ»"


def test_quotes_of_any_kind():
    assert meta.find_organizations('ЗАО "ПромГеоТех"') == ["ЗАО «ПромГеоТех»"]


def test_folder_name_normalized_to_same_form():
    """Организация из папки и из текста должны выглядеть одинаково,
    иначе в отчёте они будут двумя разными строками."""
    from_path = meta.find_counterparty(chr(92).join(["2025", "ООО СтройМонтаж", "Письма", "Исх 5.docx"]))
    from_text = meta.find_organizations("Подрядчик: ООО «СтройМонтаж»")[0]
    assert from_path == from_text


def test_no_organization_in_plain_text():
    assert meta.find_organizations("получено от ООО и передано далее") == []


def test_typographic_dash_is_unified():
    """«ПД‐ПРОЕКТ» с типографским дефисом и «ПД-ПРОЕКТ» — одна организация."""
    typographic = meta.find_organizations("ООО " + chr(171) + "ПД" + chr(0x2010) + "ПРОЕКТ" + chr(187))
    ordinary = meta.find_organizations("ООО " + chr(171) + "ПД-ПРОЕКТ" + chr(187))
    assert typographic == ordinary


def test_folder_without_org_marker_gives_nothing():
    assert meta.find_counterparty(chr(92).join(["Фото", "Гор", "снимок.jpg"])) is None
