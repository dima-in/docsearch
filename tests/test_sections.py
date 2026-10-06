"""Разделы архива: крупная группировка поверх типов документов."""
from __future__ import annotations

from pathlib import Path

from docsearch import sections


def test_type_decides_first():
    """Письмо в папке проекта остаётся перепиской."""
    assert sections.classify(
        "письмо", "01. Проекты (П и РД)/ГКМ/Исх 12.pdf", ".pdf"
    ) == sections.CORRESPONDENCE


def test_path_decides_when_type_unknown():
    assert sections.classify(
        None, "01. Проекты (П и РД)/АР/208-1121-АР4.pdf", ".pdf"
    ) == sections.PROJECT
    assert sections.classify(
        None, "02 .Переписка (Письма)/Входящие/скан.pdf", ".pdf"
    ) == sections.CORRESPONDENCE


def test_extension_is_the_last_resort():
    assert sections.classify(None, "Туйгун/что-то.dwg", ".dwg") == sections.PROJECT
    assert sections.classify(None, "Объект/снимок.jpg", ".jpg") == sections.PHOTOS


def test_unknown_falls_back_to_other():
    assert sections.classify(None, "Яяя (для обмена)/файл.zip", ".zip") == sections.OTHER


def test_quality_section():
    assert sections.classify("сертификат", "ИД/x.pdf", ".pdf") == sections.QUALITY
    assert sections.classify(
        None, "Паспорта и сертификаты/бетон.pdf", ".pdf") == sections.QUALITY


def test_executive_section():
    assert sections.classify("КС-2", "x/y.pdf", ".pdf") == sections.EXECUTIVE
    assert sections.classify("акт скрытых работ", "x/y.pdf", ".pdf") == sections.EXECUTIVE


def test_custom_rules_from_config_win_over_builtin():
    """Свои правила важнее встроенных: структура папок у всех своя."""
    custom = {"охрана труда": ["охрана труда"]}
    assert sections.classify(
        None, "Охрана труда/инструктаж.pdf", ".pdf", custom) == "охрана труда"


def test_order_puts_correspondence_first():
    assert sections.sort_key(sections.CORRESPONDENCE) < sections.sort_key(sections.PROJECT)
    assert sections.sort_key("выдуманный") > sections.sort_key(sections.OTHER) - 1


def test_guess_for_uses_extension_of_path():
    assert sections.guess_for(Path("a/b.dwg"), "a/b.dwg", None) == sections.PROJECT
