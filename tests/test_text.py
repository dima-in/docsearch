from docsearch import morph, snippet, textnorm


def test_normalize_removes_soft_hyphen():
    assert textnorm.normalize("Котельная­3") == "Котельная3"


def test_normalize_collapses_nbsp():
    assert textnorm.normalize("АКТ освидетельствования") == "АКТ освидетельствования"


def test_normalize_keeps_line_breaks():
    assert textnorm.normalize("строка 1\nстрока 2") == "строка 1\nстрока 2"


def test_normalize_squashes_blank_lines():
    assert textnorm.normalize("а\n\n\n\nб") == "а\n\nб"


def test_tokenize_drops_single_chars():
    assert morph.tokenize("акт о том, что") == ["акт", "том", "что"]


def test_lemma_normalizes_word_form():
    if not morph.available():
        return  # без pymorphy3 лемматизация вырождается в тождество
    assert morph.lemma("поставки") == "поставка"
    assert morph.lemma("фундаментов") == "фундамент"


def test_snippet_highlights_inflected_form():
    body = "Комиссия установила задержку поставки щебня на объект."
    result = snippet.make(body, "поставка щебня")
    assert "[поставки]" in result
    assert "[щебня]" in result


def test_snippet_falls_back_to_head_when_no_match_in_body():
    body = "Текст без искомых слов, найдено по имени файла."
    result = snippet.make(body, "асфальтоукладчик")
    assert result.startswith("Текст без искомых слов")


def test_snippet_on_empty_body():
    assert snippet.make("", "что угодно") == ""
