"""Sjekker at den ferdigbygde Windows-appen virker – kjøres med den medfølgende Python-en.

    build\\PengeneMine\\python\\python.exe windows\\smoketest.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP = Path(os.environ.get("APP_DIR") or Path(sys.executable).resolve().parent.parent / "app")
os.environ["FORBRUKSAPP_DIR"] = tempfile.mkdtemp(prefix="pengene-test-")
os.chdir(APP)
sys.path.insert(0, str(APP))


def step(name):
    print(f"--- {name}", flush=True)


step("Pakker kan importeres")
import matplotlib, openpyxl, pandas, plotly, reportlab, streamlit, xlsxwriter  # noqa: E401,F401
print("streamlit", streamlit.__version__, "pandas", pandas.__version__)

step("Eksempeldata kan leses, kategoriseres og planlegges")
from forbruk import categorize, db, importer, plan, subscriptions  # noqa: E402
conn = db.connect()
db.set_setting(conn, "user_name", "Emma Hansen")
for f in sorted((APP / "eksempeldata").glob("*.*")):
    if f.suffix in {".csv", ".xlsx"}:
        r = importer.parse_file(f.read_bytes(), f.name)
        db.insert_transactions(conn, r.df, db.get_or_create_account(conn, f.stem, None, None), f.name)
categorize.refresh(conn)
df = db.load_transactions(conn)
p = plan.new_plan(df, subscriptions.find_subscriptions(df), plan.next_month())
print(len(df), "transaksjoner,", len(p["faste"]), "faste utgifter i planen")
assert len(df) > 100 and p["inntekter"]

step("Alle sidene i appen kjører uten feil")
from streamlit.testing.v1 import AppTest  # noqa: E402
at = AppTest.from_file(str(APP / "app.py"), default_timeout=120).run()
assert not at.exception, [e.value for e in at.exception]
print("forsiden OK")

step("Launcheren starter og stopper appen")
import launcher  # noqa: E402
print("nettleser for app-vindu:", launcher.find_app_browser())
launcher.open_window = lambda port: (print("app svarer på port", port, launcher.healthy(port)),
                                     subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"]))[1]
t = time.time()
assert launcher.main() == 0
assert not launcher.STATE.exists()
print(f"OK på {time.time() - t:.0f} s")
print("\nAlt virker ✅")
