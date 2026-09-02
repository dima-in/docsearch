"""Распознавание текста на сканах через Tesseract.

Отдельный шаг, а не часть индексации: распознавание идёт на порядки
дольше разбора и должно запускаться отдельно, с возможностью прервать и
продолжить. Индексатор только помечает файлы, которым нужен OCR.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Куда установщики обычно кладут tesseract.exe на Windows
COMMON_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

# Только русский: с "rus+eng" Tesseract на неоднозначных буквах
# выбирает латиницу, и РТП-161 превращается в PIIT-161
DEFAULT_LANG = "rus"
DEFAULT_DPI = 300
DEFAULT_TIMEOUT = 180
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


class OcrUnavailable(RuntimeError):
    """Tesseract не найден или не умеет нужный язык."""


@dataclass
class OcrResult:
    text: str = ""
    pages: int = 0
    error: str | None = None


def find_tesseract() -> str | None:
    """Путь к tesseract.exe: переменная окружения, PATH, обычные места."""
    explicit = os.environ.get("TESSERACT_CMD")
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in COMMON_PATHS:
        if Path(candidate).exists():
            return candidate
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe"
    return str(local) if local.exists() else None


def languages(cmd: str | None = None) -> list[str]:
    cmd = cmd or find_tesseract()
    if not cmd:
        return []
    try:
        out = subprocess.run([cmd, "--list-langs"], capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    lines = (out.stdout or "").splitlines()
    return [l.strip() for l in lines[1:] if l.strip()]


def check(lang: str = DEFAULT_LANG) -> str:
    """Убедиться, что распознавание вообще возможно. Иначе — внятная причина."""
    cmd = find_tesseract()
    if not cmd:
        raise OcrUnavailable(
            "Tesseract не найден. Установите его (сборка UB-Mannheim, отметьте "
            "компонент Cyrillic) или укажите путь в переменной TESSERACT_CMD"
        )
    installed = languages(cmd)
    missing = [part for part in lang.split("+") if part not in installed]
    if missing:
        raise OcrUnavailable(
            f"Tesseract найден ({cmd}), но нет языков: {', '.join(missing)}. "
            f"Установлены: {', '.join(installed) or 'нет'}. "
            "Переустановите Tesseract с компонентом Cyrillic"
        )
    return cmd


def run_tesseract(image: bytes, cmd: str, lang: str = DEFAULT_LANG,
                  timeout: int = DEFAULT_TIMEOUT) -> str:
    """Отдать картинку на stdin и забрать текст со stdout — без временных файлов."""
    proc = subprocess.run(
        [cmd, "stdin", "stdout", "-l", lang],
        input=image, capture_output=True, timeout=timeout,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(detail[:300] or f"tesseract вернул код {proc.returncode}")
    return proc.stdout.decode("utf-8", "replace")


def _pdf_page_images(path: Path, dpi: int, max_pages: int):
    from .extract.pdf import open_pdf

    doc = open_pdf(path)
    try:
        for number, page in enumerate(doc):
            if number >= max_pages:
                break
            yield page.get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()


def _docx_images(path: Path):
    """Картинки, вставленные в Word: сканы часто вклеивают прямо в документ."""
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist()
                 if n.startswith("word/media/")
                 and Path(n).suffix.lower() in IMAGE_SUFFIXES]
        for name in sorted(names):
            yield archive.read(name)


def recognize(path: Path, cmd: str, lang: str = DEFAULT_LANG,
              dpi: int = DEFAULT_DPI, max_pages: int = 40,
              timeout: int = DEFAULT_TIMEOUT) -> OcrResult:
    """Распознать скан: PDF постранично, Word — по вставленным картинкам."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            images = _pdf_page_images(path, dpi, max_pages)
        elif suffix == ".docx":
            images = _docx_images(path)
        elif suffix in IMAGE_SUFFIXES:
            images = [path.read_bytes()]
        else:
            return OcrResult(error=f"нечего распознавать в {suffix}")

        parts: list[str] = []
        pages = 0
        for image in images:
            if pages >= max_pages:
                break
            parts.append(run_tesseract(image, cmd, lang, timeout))
            pages += 1
        return OcrResult(text="\n".join(parts), pages=pages)
    except subprocess.TimeoutExpired:
        return OcrResult(error=f"tesseract не уложился в {timeout} с")
    except Exception as exc:
        return OcrResult(error=f"{type(exc).__name__}: {exc}"[:300])
