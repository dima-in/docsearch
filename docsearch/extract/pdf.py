from __future__ import annotations

from pathlib import Path

from . import Extracted

# Меньше этого на страницу — считаем, что текстового слоя нет и нужен OCR
MIN_CHARS_PER_PAGE = 40


_quieted = False


def open_pdf(path: Path):
    """Открыть PDF, не давая MuPDF сыпать диагностику в stderr.

    Библиотека пишет «format error: object is not a stream» напрямую из
    си-кода, мимо предупреждений Python. На битых, но читаемых файлах это
    сотни строк в логе. Настоящие сбои всё равно приходят исключением.
    """
    global _quieted
    try:
        import pymupdf as fitz
    except ImportError:  # PyMuPDF < 1.24.3
        import fitz

    if not _quieted:
        try:
            fitz.TOOLS.mupdf_display_errors(False)
            fitz.TOOLS.mupdf_display_warnings(False)
        except Exception:
            pass
        _quieted = True
    return fitz.open(str(path))


def extract_pdf(path: Path) -> Extracted:

    doc = open_pdf(path)
    try:
        pages = [page.get_text("text") for page in doc]
        page_count = doc.page_count
    finally:
        doc.close()

    text = "\n".join(pages)
    density = len(text.strip()) / max(page_count, 1)
    needs_ocr = density < MIN_CHARS_PER_PAGE
    return Extracted(
        text=text,
        page_count=page_count,
        needs_ocr=needs_ocr,
        # скан без текста — это не ошибка, это работа для фазы OCR
        status="needs_ocr" if needs_ocr else "ok",
    )
