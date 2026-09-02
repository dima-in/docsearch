"""Создание конфига: кодировка, пути, метка, защита от перезаписи."""
from __future__ import annotations

from pathlib import Path

import pytest

from docsearch import config as config_mod
from docsearch import scaffold

BACKSLASH = chr(92)


def test_label_defaults_to_last_path_part():
    assert scaffold.default_label("//server/share/ПТО") == "ПТО"
    assert scaffold.default_label("D:/Архив/2025") == "2025"


def test_backslashes_are_normalized():
    unc = BACKSLASH * 2 + "Artem-server" + BACKSLASH + "Taininskaya16(Server)"
    assert scaffold.normalize_root(unc) == "//Artem-server/Taininskaya16(Server)"


def test_written_config_is_utf8_and_loadable(tmp_path: Path):
    target = tmp_path / "config.server.yaml"
    scaffold.write(target, "//Artem-server/Taininskaya16(Server)",
                   label="Тайнинская 16", db="index-server.db")

    # читается как UTF-8, русская метка не испорчена
    assert "Тайнинская 16" in target.read_text(encoding="utf-8")

    cfg = config_mod.load(target)
    assert cfg.roots[0].label == "Тайнинская 16"
    assert "Artem-server" in cfg.roots[0].path
    assert cfg.db.endswith("index-server.db")


def test_unc_from_explorer_survives_round_trip(tmp_path: Path):
    """Путь, скопированный из проводника, должен работать без правки."""
    target = tmp_path / "config.server.yaml"
    unc = BACKSLASH * 2 + "Artem-server" + BACKSLASH + "Taininskaya16(Server)"
    scaffold.write(target, unc)
    cfg = config_mod.load(target)
    assert "Artem-server" in cfg.roots[0].path
    assert str(tmp_path) not in cfg.roots[0].path


def test_refuses_to_overwrite(tmp_path: Path):
    target = tmp_path / "config.local.yaml"
    scaffold.write(target, "D:/Архив")
    with pytest.raises(FileExistsError):
        scaffold.write(target, "D:/Другой")
    assert "Архив" in target.read_text(encoding="utf-8")


def test_force_overwrites(tmp_path: Path):
    target = tmp_path / "config.local.yaml"
    scaffold.write(target, "D:/Архив")
    scaffold.write(target, "D:/Другой", force=True)
    assert "Другой" in target.read_text(encoding="utf-8")


def test_absolute_windows_db_path_is_loadable(tmp_path: Path):
    """Путь к базе с обратными слэшами не должен ломать разбор YAML."""
    target = tmp_path / "config.local.yaml"
    db_path = str(tmp_path / "index.db")      # C:\...\index.db на Windows
    scaffold.write(target, "D:/Архив", db=db_path)
    cfg = config_mod.load(target)
    assert cfg.db.endswith("index.db")
