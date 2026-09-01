"""Пути в конфиге: UNC, относительные, абсолютные."""
from __future__ import annotations

from pathlib import Path

import pytest

from docsearch import config as config_mod

BACKSLASH = chr(92)

CONFIG_TEMPLATE = """roots:
  - label: "ПТО"
    path: {path}
index:
  db: "index.db"
"""


def write_config(tmp_path: Path, path_line: str) -> Path:
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text(CONFIG_TEMPLATE.format(path=path_line), encoding="utf-8")
    return cfg


def test_unc_with_forward_slashes(tmp_path: Path):
    cfg = config_mod.load(write_config(tmp_path, "'//Artem-server/Taininskaya16(Server)'"))
    assert "Artem-server" in cfg.roots[0].path
    # главное — путь не приклеился к папке конфига
    assert str(tmp_path) not in cfg.roots[0].path


def test_unc_with_backslashes(tmp_path: Path):
    line = "'" + BACKSLASH * 2 + "Artem-server" + BACKSLASH + "Taininskaya16(Server)'"
    cfg = config_mod.load(write_config(tmp_path, line))
    assert "Artem-server" in cfg.roots[0].path
    assert str(tmp_path) not in cfg.roots[0].path


def test_relative_path_is_resolved_against_config_dir(tmp_path: Path):
    cfg = config_mod.load(write_config(tmp_path, '"./sample"'))
    assert cfg.roots[0].path.startswith(str(tmp_path))
    assert cfg.db.startswith(str(tmp_path))


def test_double_quoted_backslashes_are_rejected_by_yaml(tmp_path: Path):
    """Двойные кавычки с обратными слэшами — ошибка разбора, а не тихий сбой."""
    import yaml

    line = '"' + BACKSLASH * 2 + "Artem-server" + BACKSLASH + 'Taininskaya16"'
    with pytest.raises(yaml.YAMLError):
        config_mod.load(write_config(tmp_path, line))
