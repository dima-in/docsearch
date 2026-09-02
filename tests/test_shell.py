"""Интерактивный поиск: разбор команд и вывод."""
from __future__ import annotations

from pathlib import Path

from docsearch import shell


def test_open_by_latin_and_cyrillic():
    assert shell.parse_action("o3") == ("open", 3)
    assert shell.parse_action("о3") == ("open", 3)      # русская «о»


def test_text_and_folder_actions():
    assert shell.parse_action("t12") == ("text", 12)
    assert shell.parse_action("т12") == ("text", 12)
    assert shell.parse_action("p1") == ("folder", 1)
    assert shell.parse_action("п1") == ("folder", 1)


def test_spaces_and_case_are_tolerated():
    assert shell.parse_action("О 3") == ("open", 3)
    assert shell.parse_action("  T 7  ") == ("text", 7)


def test_plain_query_is_not_an_action():
    assert shell.parse_action("огнезащита") is None
    assert shell.parse_action("акт 15") is None
    assert shell.parse_action("о") is None


def test_open_missing_file_reports_reason(tmp_path: Path):
    error = shell.open_path(tmp_path / "нет такого.pdf")
    assert error and "больше нет" in error


def test_quit_words_cover_both_layouts():
    assert "q" in shell.QUIT_WORDS
    assert "в" in shell.QUIT_WORDS
    assert "выход" in shell.QUIT_WORDS
