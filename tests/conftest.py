import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("FORBRUKSAPP_DIR", str(tmp_path))
    from forbruk import db
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture(scope="session")
def demo_dir():
    d = ROOT / "eksempeldata"
    if not (d / "dnb_brukskonto_mai-aug.csv").exists():
        import runpy
        runpy.run_path(str(d / "lag_eksempeldata.py"), run_name="__main__")
    return d
