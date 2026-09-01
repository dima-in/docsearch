"""Определение настоящего типа файла по сигнатуре."""
from __future__ import annotations

from pathlib import Path

from docsearch import sniff


def test_identifies_pdf():
    assert sniff.identify(b"%PDF-1.7\n...")[0] == "PDF"


def test_identifies_zip_container():
    label, ext = sniff.identify(b"PK\x03\x04\x14\x00")
    assert "ZIP" in label
    assert ext is None      # docx, xlsx и zip неразличимы по первым байтам


def test_identifies_old_office():
    label, _ = sniff.identify(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    assert "OLE" in label


def test_identifies_windows_shortcut():
    label, ext = sniff.identify(b"L\x00\x00\x00\x01\x14\x02\x00\x00\x00\x00\x00")
    assert ext == ".lnk"


def test_empty_file():
    assert sniff.identify(b"")[0] == "пустой файл"


def test_unknown_signature():
    assert sniff.identify(b"\x99\x98\x97\x96")[0] == "не опознан"


def test_inspect_flags_wrong_extension(tmp_path: Path):
    """Файл с расширением .pdf, а внутри ZIP — расширение врёт."""
    target = tmp_path / "РТП-1117.pdf"
    target.write_bytes(b"PK\x03\x04" + b"\x00" * 40)
    info = sniff.inspect(target)
    assert info["readable"]
    assert info["actual_ext"] == ".pdf"
    assert "ZIP" in info["type"]


def test_inspect_reports_matching_extension(tmp_path: Path):
    target = tmp_path / "письмо.pdf"
    target.write_bytes(b"%PDF-1.4" + b"\x00" * 40)
    info = sniff.inspect(target)
    assert info["mismatch"] is False


def test_inspect_missing_file(tmp_path: Path):
    info = sniff.inspect(tmp_path / "нет такого.pdf")
    assert info["readable"] is False
    assert info["error"]
