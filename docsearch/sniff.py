"""Определение настоящего типа файла по первым байтам.

Расширение врёт: в архиве регулярно попадаются файлы, переименованные
вручную. Сигнатура в начале файла говорит правду, и по ней видно, чем
файл является на самом деле.
"""
from __future__ import annotations

from pathlib import Path

# (смещение, сигнатура, что это, какое расширение подошло бы)
SIGNATURES: list[tuple[int, bytes, str, str | None]] = [
    (0, b"%PDF", "PDF", ".pdf"),
    (0, b"PK\x03\x04", "ZIP-контейнер (docx, xlsx, pptx или архив)", None),
    (0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "OLE — старый Word, Excel или .msg", None),
    (0, b"{\rtf", "RTF", ".rtf"),
    (0, b"\x89PNG", "PNG", ".png"),
    (0, b"\xff\xd8\xff", "JPEG", ".jpg"),
    (0, b"II*\x00", "TIFF", ".tif"),
    (0, b"MM\x00*", "TIFF", ".tif"),
    (0, b"AC10", "AutoCAD DWG", ".dwg"),
    (0, b"Rar!", "RAR", ".rar"),
    (0, b"7z\xbc\xaf\x27\x1c", "7-Zip", ".7z"),
    (0, b"L\x00\x00\x00\x01\x14\x02\x00", "Ярлык Windows (.lnk)", ".lnk"),
    (0, b"\x30\x82", "DER/PKCS — подпись или сертификат", ".p7s"),
    (0, b"<?xml", "XML", ".xml"),
    (0, b"<!DOC", "HTML", ".html"),
    (0, b"MSCF", "CAB-архив", ".cab"),
    (0, b"\x1f\x8b", "GZIP", ".gz"),
]

PREVIEW_BYTES = 32


def identify(head: bytes) -> tuple[str, str | None]:
    """Вернуть описание типа и расширение, которое ему соответствует."""
    for offset, magic, label, ext in SIGNATURES:
        if head[offset:offset + len(magic)] == magic:
            return label, ext
    if not head:
        return "пустой файл", None
    return "не опознан", None


def printable(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


def inspect(path: Path) -> dict:
    """Размер, сигнатура и предполагаемый настоящий тип файла."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(PREVIEW_BYTES)
    except OSError as exc:
        return {"path": str(path), "readable": False,
                "error": f"{type(exc).__name__}: {exc}"}

    label, ext = identify(head)
    return {
        "path": str(path),
        "readable": True,
        "size": size,
        "hex": head[:16].hex(" "),
        "ascii": printable(head[:16]),
        "type": label,
        "suggested_ext": ext,
        "actual_ext": path.suffix.lower(),
        # расширение врёт, если сигнатура указывает на другой формат
        "mismatch": bool(ext and ext != path.suffix.lower()),
    }
