"""Сделать шаблон письма из любого вашего исходящего.

Берём отправленное письмо, выбрасываем его содержание и оставляем
вёрстку: логотип, шапку, таблицу «номер — адресат», подпись. Переменные
места помечаются подстановками вида {{number}}.

    python tools/make_template.py "Исх. РТП-1335.docx" templates/письмо.docx

Старый .doc сначала пересохраните в .docx — Word умеет это сам.

Получившийся шаблон правится в Word как обычный документ: подстановки —
это просто текст. Главное не трогать фигурные скобки.
"""
from __future__ import annotations

import sys
from pathlib import Path

PLACEHOLDERS = {
    "number": "номер исходящего",
    "date": "дата",
    "recipient_position": "кому, должность",
    "recipient_org": "организация адресата",
    "recipient_person": "фамилия адресата",
    "subject": "тема",
    "greeting": "обращение",
    "body": "текст письма",
    "signer_position": "должность подписанта",
    "signer_name": "фамилия подписанта",
}


def set_text(paragraph, text: str) -> None:
    """Заменить текст абзаца, сохранив оформление первого прогона."""
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(text)
        return
    runs[0].text = text
    for extra in runs[1:]:
        extra.text = ""


def drop(element) -> None:
    element.getparent().remove(element)


def build(source: str, target: str) -> list[str]:
    import docx

    document = docx.Document(source)
    report: list[str] = []

    if document.tables:
        head = document.tables[0]
        cells = head.rows[0].cells
        set_text(cells[0].paragraphs[0], "Исх. {{number}} от {{date}}")
        report.append("таблица шапки: номер слева, адресат справа")

        if len(cells) > 1:
            wanted = ["{{recipient_position}}", "{{recipient_org}}",
                      "{{recipient_person}}"]
            paragraphs = cells[1].paragraphs
            for i, placeholder in enumerate(wanted):
                if i < len(paragraphs):
                    set_text(paragraphs[i], placeholder)
                else:
                    cells[1].add_paragraph(placeholder)
            for extra in paragraphs[len(wanted):]:
                drop(extra._element)

    # Остальные таблицы — приложения конкретного письма, в бланке лишние
    for table in document.tables[1:]:
        drop(table._element)
        report.append("удалена таблица приложения")

    state = "before"
    for paragraph in list(document.paragraphs):
        text = paragraph.text.strip()
        low = text.lower()

        if low.startswith("тема"):
            set_text(paragraph, "Тема: «{{subject}}»")
            report.append("тема")
        elif low.startswith("уважаем"):
            set_text(paragraph, "{{greeting}}")
            state = "body"
            report.append("обращение")
        elif low.startswith("с уважением"):
            state = "signature"
        elif state == "signature" and text:
            set_text(paragraph, "{{signer_position}}\t\t{{signer_name}}")
            state = "done"
            report.append("подпись")
        elif state == "body" and text:
            set_text(paragraph, "{{body}}")
            state = "body_done"
            report.append("текст письма")
        elif state == "body_done" and text:
            drop(paragraph._element)

    if state == "body_done":
        report.append("подпись не найдена — допишите {{signer_position}} вручную")

    Path(target).parent.mkdir(parents=True, exist_ok=True)
    document.save(target)
    return report


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    source, target = sys.argv[1], sys.argv[2]
    if not Path(source).exists():
        print(f"Неуспех: нет файла {source}")
        return 1
    if Path(source).suffix.lower() != ".docx":
        print("Неуспех: нужен .docx. Старый .doc пересохраните в Word")
        return 1

    report = build(source, target)
    print(f"Сделал: шаблон {target}")
    for line in report:
        print(f"  размечено: {line}")
    print()
    print("Пропишите его в конфиг:")
    print(f"  letterhead:\n    template: \"{target}\"")
    print()
    print("Доступные подстановки:")
    for key, meaning in PLACEHOLDERS.items():
        print(f"  {{{{{key}}}}}".ljust(28) + meaning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
