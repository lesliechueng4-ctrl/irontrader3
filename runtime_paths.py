"""Paths for bundled and source-based IronTrader runs."""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "IronTrader"


def application_resource_dir() -> Path:
    """Return the directory that contains bundled read-only resources."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def application_data_dir() -> Path:
    """Return a writable directory for caches, exports, and logs."""
    configured = os.getenv("IRONTRADER_DATA_DIR", "").strip()
    if configured:
        base_dir = Path(configured).expanduser()
    elif getattr(sys, "frozen", False):
        base_dir = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME
    else:
        base_dir = application_resource_dir()

    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir
