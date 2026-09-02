"""Вывод при перенаправлении в файл должен оставаться читаемым.

Ночной прогон смотрят по логу, и строки прогресса с возвратом каретки
превращают его в кашу. Дефект уже проскакивал дважды, поэтому проверяем
не флаг, а настоящий запуск с перенаправленным выводом.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from docsearch import scaffold

LETTER = "Исх. № 12 от 01.02.2025\n\nО поставке щебня фр. 20-40.\n"


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path]:
    archive = tmp_path / "arc" / "Письма"
    archive.mkdir(parents=True)
    for i in range(5):
        (archive / f"Исх {i}.txt").write_text(LETTER, encoding="utf-8")
    cfg = tmp_path / "config.local.yaml"
    scaffold.write(cfg, str(tmp_path / "arc"), db=str(tmp_path / "index.db"))
    return cfg, tmp_path


def run_cli(cfg: Path, *args: str) -> str:
    """Запуск отдельным процессом: только так stdout действительно не консоль."""
    result = subprocess.run(
        [sys.executable, "-m", "docsearch.cli", "-c", str(cfg), *args],
        capture_output=True, timeout=180,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8", "replace")


def bare_carriage_returns(text: str) -> int:
    """Возвраты каретки без перевода строки — это и есть строки прогресса.
    Обычные виндовые переводы 
 к делу не относятся."""
    return text.replace(chr(13) + chr(10), chr(10)).count(chr(13))


def test_index_log_has_no_carriage_returns(project):
    cfg, _ = project
    out = run_cli(cfg, "index")
    assert bare_carriage_returns(out) == 0
    # строка прогресса начинается с отступа, итоговая — со слова «Сделал»
    assert not any(l.startswith("  просмотрено") for l in out.split(chr(10)))
    assert "Успех" in out


def test_index_log_has_no_padding_lines(project):
    """Строка очистки прогресса — 90 пробелов — тоже не должна попадать в файл."""
    cfg, _ = project
    out = run_cli(cfg, "index")
    assert not any(line.strip() == "" and len(line) > 40 for line in out.split("\n"))


def test_log_lines_are_all_meaningful(project):
    cfg, _ = project
    out = run_cli(cfg, "index")
    lines = [l for l in out.split("\n") if l.strip()]
    assert 4 <= len(lines) <= 10
    assert all(len(l) < 200 for l in lines)
