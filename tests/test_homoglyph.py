from docsearch import homoglyph


def test_fixes_latin_twins_in_cyrillic_word():
    assert homoglyph.fix_word("PТП") == "РТП"          # P латинская
    assert homoglyph.fix_word("BОДА") == "ВОДА"


def test_leaves_pure_latin_alone():
    assert homoglyph.fix_word("PDF") == "PDF"
    assert homoglyph.fix_word("info") == "info"


def test_leaves_pure_cyrillic_alone():
    assert homoglyph.fix_word("протокол") == "протокол"


def test_leaves_word_with_non_twin_latin():
    """В слове есть латинская буква без кириллической пары — не трогаем."""
    assert homoglyph.fix_word("СтройGrand") == "СтройGrand"


def test_leaves_latin_dominant_word():
    assert homoglyph.fix_word("Wоrd") == "Wоrd"


def test_fixes_inside_sentence():
    text = "Направляем письмо PТП-161 от 09.02.2024 в адрес ООО КБ"
    assert "РТП-161" in homoglyph.fix(text)


def test_does_not_touch_emails_and_urls():
    text = "info@fbstroy.ru"
    assert homoglyph.fix(text) == text


def test_empty():
    assert homoglyph.fix("") == ""
