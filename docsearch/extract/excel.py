from __future__ import annotations

import warnings
from pathlib import Path

from . import Extracted

MAX_CELLS_PER_SHEET = 50_000


def extract_xlsx(path: Path) -> Extracted:
    import openpyxl

    # openpyxl предупреждает о колонтитулах и расширениях, которые не смог
    # разобрать. На содержимое ячеек это не влияет, а консоль засоряет.
    # В режиме read_only разбор идёт при обходе строк, поэтому глушить
    # предупреждения надо вокруг всей работы с книгой, а не вокруг открытия
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        try:
            parts: list[str] = []
            for sheet in wb.worksheets:
                parts.append(f"[лист] {sheet.title}")
                seen = 0
                for row in sheet.iter_rows(values_only=True):
                    values = [str(v).strip() for v in row if v is not None and str(v).strip()]
                    seen += len(row)
                    if values:
                        parts.append(" | ".join(values))
                    if seen > MAX_CELLS_PER_SHEET:
                        parts.append("[...лист обрезан...]")
                        break
            return Extracted(text="\n".join(parts), page_count=len(wb.worksheets))
        finally:
            wb.close()
