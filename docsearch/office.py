"""Чтение старых форматов Office: .doc, .xls, .ppt.

Это форматы девяностых, и открыть их умеет только сам Office. В архиве
ПТО их много — переписка, сметы, акты, — и без них из поиска выпадают
целые подрядчики: письма к ним лежат в .doc, а значит текста у них нет
ни для поиска, ни для разбора организации и договора.

Конвертируем через установленный Word и Excel, партиями: запуск самого
Office занимает секунды, а перегонка файла — доли секунды, поэтому на
партию поднимаем приложение один раз.

Отдельной зависимости не требуется: COM вызывается через PowerShell,
который на Windows есть всегда.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# wdFormatDocumentDefault = 16, xlOpenXMLWorkbook = 51
WORD_FORMATS = {".doc", ".rtf", ".odt"}
EXCEL_FORMATS = {".xls", ".xlt"}
SUPPORTED = WORD_FORMATS | EXCEL_FORMATS

CONVERTED = {".doc": ".docx", ".rtf": ".docx", ".odt": ".docx",
             ".xls": ".xlsx", ".xlt": ".xlsx"}

SCRIPT = r'''
param([string]$ListFile, [string]$OutDir, [string]$Kind)
$ErrorActionPreference = 'Continue'
$items = Get-Content -LiteralPath $ListFile -Encoding UTF8 | ConvertFrom-Json
$app = $null
try {
    if ($Kind -eq 'word') {
        $app = New-Object -ComObject Word.Application
        $app.Visible = $false
        $app.DisplayAlerts = 0
    } else {
        $app = New-Object -ComObject Excel.Application
        $app.Visible = $false
        $app.DisplayAlerts = $false
    }
    # документы из архива могут нести макросы: выполнять их незачем
    try { $app.AutomationSecurity = 3 } catch {}

    foreach ($item in $items) {
        $result = @{ id = $item.id; ok = $false; error = '' }
        try {
            if ($Kind -eq 'word') {
                $doc = $app.Documents.Open($item.src, $false, $true)
                $doc.SaveAs2([ref]$item.dst, [ref]16)
                $doc.Close([ref]$false)
            } else {
                $book = $app.Workbooks.Open($item.src, 0, $true)
                $book.SaveAs($item.dst, 51)
                $book.Close($false)
            }
            $result.ok = $true
        } catch {
            $result.error = $_.Exception.Message
        }
        Write-Output ($result | ConvertTo-Json -Compress)
    }
} finally {
    if ($app -ne $null) {
        try { $app.Quit() } catch {}
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
    }
}
'''


class OfficeUnavailable(RuntimeError):
    """Word или Excel на этой машине недоступны."""


def available(kind: str = "word") -> bool:
    if sys.platform != "win32":
        return False
    program = "Word.Application" if kind == "word" else "Excel.Application"
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"$a = New-Object -ComObject {program};"
             f" $a.Quit();"
             f" [System.Runtime.InteropServices.Marshal]::ReleaseComObject($a)"
             f" | Out-Null; 'ok'"],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "ok" in (done.stdout or "")


def check(kinds: set[str]) -> None:
    """Убедиться, что нужные приложения есть. Иначе — внятная причина."""
    missing = [kind for kind in sorted(kinds) if not available(kind)]
    if missing:
        names = {"word": "Microsoft Word", "excel": "Microsoft Excel"}
        raise OfficeUnavailable(
            "не удалось запустить " + ", ".join(names[k] for k in missing)
            + ". Старые форматы открывает только сам Office; на машине, где"
              " идёт индексация, он должен быть установлен"
        )


def kind_for(suffix: str) -> str | None:
    suffix = suffix.lower()
    if suffix in WORD_FORMATS:
        return "word"
    if suffix in EXCEL_FORMATS:
        return "excel"
    return None


def convert_batch(items: list[dict], kind: str,
                  timeout: int = 1800) -> dict[int, dict]:
    """Перегнать партию файлов. items: [{id, src, dst}]. Возвращает id -> итог."""
    if not items:
        return {}

    work = Path(tempfile.mkdtemp(prefix="docsearch-office-"))
    try:
        list_file = work / "items.json"
        list_file.write_text(json.dumps(items, ensure_ascii=False),
                             encoding="utf-8")
        script = work / "convert.ps1"
        script.write_text(SCRIPT, encoding="utf-8")

        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(script),
             "-ListFile", str(list_file), "-OutDir", str(work), "-Kind", kind],
            capture_output=True, text=True, timeout=timeout,
        )
        results: dict[int, dict] = {}
        for line in (done.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            results[int(parsed["id"])] = {
                "ok": bool(parsed.get("ok")),
                "error": (parsed.get("error") or "")[:300],
            }
        return results
    finally:
        shutil.rmtree(work, ignore_errors=True)


def extract_converted(path: Path) -> str:
    """Достать текст из перегнанного файла обычными обработчиками."""
    from . import extract as extract_mod

    result = extract_mod.extract(path)
    return result.text if result.status in ("ok", "empty") else ""
