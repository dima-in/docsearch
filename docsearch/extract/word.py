from __future__ import annotations

from pathlib import Path

from . import Extracted


def _rows(table) -> list[str]:
    lines = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
        if cells:
            lines.append(" | ".join(cells))
    return lines


def extract_docx(path: Path) -> Extracted:
    """Текст документа в том порядке, в каком он идёт в самом документе.

    Абзацы и таблицы нельзя читать по отдельности: в бланке письма номер
    и адресат лежат в таблице сверху, и при раздельном чтении они
    оказываются в самом конце текста — за пределами шапки, по которой
    разбираются номер, дата и получатель.
    """
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(str(path))
    parts: list[str] = []
    for child in document.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            text = Paragraph(child, document).text.strip()
            if text:
                parts.append(text)
        elif tag == "tbl":
            # в актах и протоколах основное живёт в таблицах, а не в абзацах
            parts.extend(_rows(Table(child, document)))
    return Extracted(text="\n".join(parts))
