"""Модуль распознавания: поиск Tesseract, проверки, разбор источников картинок."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from docsearch import ocr


def test_finds_tesseract_via_env(tmp_path: Path, monkeypatch):
    fake = tmp_path / "tesseract.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv("TESSERACT_CMD", str(fake))
    assert ocr.find_tesseract() == str(fake)


def test_ignores_env_pointing_nowhere(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TESSERACT_CMD", str(tmp_path / "нет.exe"))
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    monkeypatch.setattr(ocr, "COMMON_PATHS", [])
    assert ocr.find_tesseract() is None


def test_check_explains_missing_tesseract(monkeypatch):
    monkeypatch.setattr(ocr, "find_tesseract", lambda: None)
    with pytest.raises(ocr.OcrUnavailable) as exc:
        ocr.check()
    assert "не найден" in str(exc.value)


def test_check_explains_missing_language(monkeypatch):
    monkeypatch.setattr(ocr, "find_tesseract", lambda: "tesseract")
    monkeypatch.setattr(ocr, "languages", lambda cmd=None: ["eng", "osd"])
    with pytest.raises(ocr.OcrUnavailable) as exc:
        ocr.check("rus+eng")
    message = str(exc.value)
    assert "rus" in message
    assert "Cyrillic" in message      # подсказка, что именно доустановить


def test_check_passes_when_language_present(monkeypatch):
    monkeypatch.setattr(ocr, "find_tesseract", lambda: "tesseract")
    monkeypatch.setattr(ocr, "languages", lambda cmd=None: ["eng", "rus", "osd"])
    assert ocr.check("rus+eng") == "tesseract"


def test_recognize_rejects_unsupported_format(tmp_path: Path):
    target = tmp_path / "чертёж.dwg"
    target.write_bytes(b"AC1032")
    result = ocr.recognize(target, cmd="tesseract")
    assert result.error
    assert result.text == ""


def test_docx_images_are_extracted(tmp_path: Path):
    """Скан, вклеенный в Word, достаётся из word/media."""
    target = tmp_path / "письмо.docx"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
        archive.writestr("word/media/image1.png", b"\x89PNG\r\n\x1a\n")
        archive.writestr("word/media/image2.jpg", b"\xff\xd8\xff\xe0")
        archive.writestr("word/media/notes.txt", "не картинка".encode("utf-8"))
    images = list(ocr._docx_images(target))
    assert len(images) == 2
    assert images[0].startswith(b"\x89PNG")


def test_recognize_collects_pages(tmp_path: Path, monkeypatch):
    """Текст со страниц склеивается, счётчик страниц верный."""
    target = tmp_path / "скан.docx"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("word/media/a.png", b"\x89PNG")
        archive.writestr("word/media/b.png", b"\x89PNG")
    monkeypatch.setattr(ocr, "run_tesseract",
                        lambda image, cmd, lang=None, timeout=None: "строка")
    result = ocr.recognize(target, cmd="tesseract")
    assert result.pages == 2
    assert result.text == "строка\nстрока"
    assert result.error is None


def test_recognize_reports_engine_failure(tmp_path: Path, monkeypatch):
    target = tmp_path / "скан.docx"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("word/media/a.png", b"\x89PNG")

    def boom(*a, **kw):
        raise RuntimeError("Error opening data file rus.traineddata")

    monkeypatch.setattr(ocr, "run_tesseract", boom)
    result = ocr.recognize(target, cmd="tesseract")
    assert "rus.traineddata" in result.error


def test_max_pages_limits_work(tmp_path: Path, monkeypatch):
    target = tmp_path / "скан.docx"
    with zipfile.ZipFile(target, "w") as archive:
        for i in range(10):
            archive.writestr(f"word/media/{i}.png", b"\x89PNG")
    monkeypatch.setattr(ocr, "run_tesseract",
                        lambda image, cmd, lang=None, timeout=None: "x")
    assert ocr.recognize(target, cmd="tesseract", max_pages=3).pages == 3
