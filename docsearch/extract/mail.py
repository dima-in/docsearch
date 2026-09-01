from __future__ import annotations

from pathlib import Path

from . import Extracted


def extract_msg(path: Path) -> Extracted:
    import extract_msg as em

    msg = em.Message(str(path))
    try:
        header = [
            f"От: {msg.sender or ''}",
            f"Кому: {msg.to or ''}",
            f"Тема: {msg.subject or ''}",
            f"Дата: {msg.date or ''}",
        ]
        body = msg.body or ""
        names = [a.longFilename or a.shortFilename or "" for a in (msg.attachments or [])]
        if names:
            header.append("Вложения: " + ", ".join(n for n in names if n))
        meta = {"counterparty": (msg.sender or "").strip() or None,
                "doc_type": "письмо"}
        return Extracted(text="\n".join(header) + "\n\n" + body, meta=meta)
    finally:
        msg.close()
