"""Извлечение текста из файлов. Один диспетчер, по обработчику на формат.

Каждый обработчик получает путь и возвращает Extracted. Если формат
поддерживается в принципе, но текста нет (скан без текстового слоя) —
ставим needs_ocr, чтобы потом прицельно прогнать OCR.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..textnorm import normalize


@dataclass
class Extracted:
    text: str = ""
    meta: dict = field(default_factory=dict)
    page_count: int | None = None
    needs_ocr: bool = False
    status: str = "ok"        # ok | empty | unsupported | error
    error: str | None = None


def _lazy(module: str, func: str):
    def call(path: Path) -> Extracted:
        import importlib

        mod = importlib.import_module(f"docsearch.extract.{module}")
        return getattr(mod, func)(path)

    return call


# Расширения, по которым текст достаём.
HANDLERS = {
    ".docx": _lazy("word", "extract_docx"),
    ".xlsx": _lazy("excel", "extract_xlsx"),
    ".xlsm": _lazy("excel", "extract_xlsx"),
    ".pdf": _lazy("pdf", "extract_pdf"),
    ".txt": _lazy("plain", "extract_txt"),
    ".csv": _lazy("plain", "extract_txt"),
    ".md": _lazy("plain", "extract_txt"),
    ".rtf": _lazy("plain", "extract_rtf"),
    ".msg": _lazy("mail", "extract_msg"),
}

# Индексируем только по имени и пути: содержимое пока не читаем,
# но найти файл по шифру или номеру всё равно можно.
NAME_ONLY = {
    ".dwg", ".dxf", ".doc", ".xls", ".ppt", ".pptx", ".eml",
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".zip", ".rar", ".7z",
}


def supported(ext: str) -> bool:
    ext = ext.lower()
    return ext in HANDLERS or ext in NAME_ONLY


def extract(path: Path) -> Extracted:
    ext = path.suffix.lower()
    handler = HANDLERS.get(ext)
    if handler is None:
        if ext in NAME_ONLY:
            # сканы-картинки честно помечаем как кандидатов на OCR
            needs_ocr = ext in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
            return Extracted(status="name_only", needs_ocr=needs_ocr)
        return Extracted(status="unsupported")
    try:
        result = handler(path)
    except Exception as exc:  # битые файлы в архиве — норма, не роняем обход
        return Extracted(status="error", error=f"{type(exc).__name__}: {exc}"[:500])
    result.text = normalize(result.text)
    if result.status == "ok" and not result.text:
        result.status = "empty"
    return result
