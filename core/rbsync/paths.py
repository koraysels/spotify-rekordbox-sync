"""Where the application keeps its own state.

Deliberately outside the rekordbox directory: this app's files should never be
mistaken for rekordbox's own, and a user cleaning up after us should be able to
delete one folder.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "rbsync"


def config_dir() -> Path:
    override = os.environ.get("RBSYNC_HOME")
    if override:
        path = Path(override)
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        path = Path(base) / APP_NAME
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_path() -> Path:
    return config_dir() / "cache.db"


def backups_dir() -> Path:
    path = config_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tokens_path() -> Path:
    return config_dir() / "tokens.json"


def exports_dir() -> Path:
    path = config_dir() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path
