from __future__ import annotations

from pathlib import Path

from . import Extracted

# Меньше этого на страницу — считаем, что текстового слоя нет и нужен OCR
MIN_CHARS_PER_PAGE = 40


def extract_pdf(path: Path) -> Extracted:
    try:
        import pymupdf as fitz
    except ImportError:  # PyMuPDF < 1.24.3
        import fitz

    doc = fitz.open(str(path))
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
