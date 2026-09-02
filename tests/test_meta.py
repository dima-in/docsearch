from pathlib import Path

from docsearch import meta


def test_find_date_numeric():
    assert meta.find_date("г. Екатеринбург, 14.11.2025") == "2025-11-14"
    assert meta.find_date("от 05/09/25") == "2025-09-05"


def test_find_date_words():
    assert meta.find_date("от 3 марта 2024 г.") == "2024-03-03"


def test_find_date_rejects_nonsense():
    assert meta.find_date("пункт 45.99.2025") is None
    assert meta.find_date("текст без даты") is None


def test_find_number_prefers_labelled():
    text = "Исх. № 270/ПТО от 14.08.2025, договор № 5"
    assert meta.find_number(text) == "270/ПТО"


def test_find_number_plain():
    assert meta.find_number("ПРОТОКОЛ № 902 совещания") == "902"
    assert meta.find_number("без номера") is None


def test_doc_type_from_name_wins_over_body():
    assert meta.find_doc_type("Акт АОСР 12", "", "уважаемые коллеги") == "акт скрытых работ"


def test_doc_type_letter():
    assert meta.find_doc_type("Исх 15", "", "Уважаемые коллеги!") == "письмо"
    assert meta.find_doc_type("Вх 44", "", "") == "письмо"


def test_doc_type_ignores_lookalike_words():
    """«акт» — подстрока слова «факт»: сравнение идёт по леммам, не по буквам."""
    assert meta.find_doc_type("Факт. адрес: Мытищи") is None
    assert meta.find_doc_type("фактически выполненные работы") is None
    assert meta.find_doc_type("контакты подрядчика") is None


def test_specific_types_win_over_general():
    assert meta.find_doc_type("Акт о приемке выполненных работ") == "КС-2"
    assert meta.find_doc_type("Протокол сертификационных испытаний") == "протокол испытаний"
    assert meta.find_doc_type("Справка о стоимости выполненных работ") == "КС-3"


def test_inflected_forms_are_recognized():
    assert meta.find_doc_type("Реестр актов за 2025 год") == "реестр"
    assert meta.find_doc_type("Сертификаты на материалы") == "сертификат"


def test_construction_types():
    assert meta.find_doc_type("Предписание об устранении") == "предписание"
    assert meta.find_doc_type("Паспорт качества на бетон") == "паспорт"
    assert meta.find_doc_type("Технологический регламент по монтажу") == "регламент"


def test_object_code():
    assert meta.find_object_code("Шифр: 123-45-ПЗ") == "123-45-ПЗ"


def test_guess_uses_folder_as_counterparty():
    attrs = meta.guess(
        Path("C:/arc/2025/ООО СтройМонтаж/Акты/Акт АОСР 270 14.08.2025.pdf"),
        r"2025\ООО СтройМонтаж\Акты\Акт АОСР 270 14.08.2025.pdf",
        "АКТ освидетельствования скрытых работ № 270",
    )
    assert attrs["doc_type"] == "акт скрытых работ"
    assert attrs["doc_date"] == "2025-08-14"
    assert attrs["counterparty"] == "ООО «СтройМонтаж»"


def test_counterparty_skips_service_folders():
    assert meta.find_counterparty(r"2025\ООО СтройМонтаж\Письма\Исх 5.docx") == "ООО «СтройМонтаж»"


def test_counterparty_without_org_marker():
    assert meta.find_counterparty(r"2025\Северная площадка\Письма\Исх 5.docx") == "Северная площадка"


def test_counterparty_flat_path():
    assert meta.find_counterparty("Исх 5.docx") is None
