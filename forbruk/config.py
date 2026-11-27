"""Stier og konstanter. All data lagres lokalt i DATA_DIR."""
from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("FORBRUKSAPP_DIR", Path.home() / ".forbruksapp"))
DB_PATH = DATA_DIR / "forbruk.db"
REPORT_DIR = DATA_DIR / "rapporter"

PROJECT_DIR = Path(__file__).resolve().parent.parent
SIFO_FILE = PROJECT_DIR / "data" / "sifo_satser.json"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
