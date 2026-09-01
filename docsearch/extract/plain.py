from __future__ import annotations

from pathlib import Path

from . import Extracted

# В ПТО живут файлы всех эпох: utf-8, windows-1251 и вообще что угодно
ENCODINGS = ("utf-8-sig", "cp1251", "utf-16", "koi8-r")


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_txt(path: Path) -> Extracted:
    return Extracted(text=_read_text(path))


def extract_rtf(path: Path) -> Extracted:
    from striprtf.striprtf import rtf_to_text

    return Extracted(text=rtf_to_text(_read_text(path), errors="ignore"))
