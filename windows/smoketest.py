"""Sjekker at den ferdigbygde Windows-appen virker – kjøres med den medfølgende Python-en.

    build\\PengeneMine\\python\\python.exe -X utf8 windows\\smoketest.py

Feiler noe, skrives feilen også som en GitHub-«annotation», så den kan leses uten å logge inn.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

APP = Path(os.environ.get("APP_DIR") or Path(sys.executable).resolve().parent.parent / "app")
DATA = Path(tempfile.mkdtemp(prefix="pengene-test-"))
os.environ["FORBRUKSAPP_DIR"] = str(DATA)
os.chdir(APP)
sys.path.insert(0, str(APP))
current = "oppstart"


def step(name):
    global current
    current = name
    print(f"--- {name}", flush=True)


def run():
    step("Pakker kan importeres")
    import matplotlib, openpyxl, pandas, plotly, reportlab, streamlit, xlsxwriter  # noqa: E401,F401
    print("python", sys.version.split()[0], "utf8-modus", sys.flags.utf8_mode,
          "streamlit", streamlit.__version__, "pandas", pandas.__version__)

    step("Eksempeldata kan leses, kategoriseres og planlegges")
    from forbruk import categorize, db, importer, plan, subscriptions
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
    assert len(df) > 100 and p["inntekter"], "for lite data"

    step("Leter etter Claude uten å krasje")
    from forbruk import ai_categorize, claude_connect
    print("Claude-appen funnet:", claude_connect.desktop_installed(), "| config:", claude_connect.desktop_config_path())
    print("claude-kommando:", ai_categorize.find_claude_cli())
    print("MCP-oppføring:", claude_connect.server_entry())

    step("Forsiden i appen kjører uten feil")
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(APP / "app.py"), default_timeout=180).run()
    assert not at.exception, [e.value for e in at.exception]
    print("forsiden OK")

    step("Launcheren starter og stopper appen")
    import launcher
    print("nettleser for app-vindu:", launcher.find_app_browser())
    import socket
    import threading

    def fake_window(port):
        """Som et ekte vindu: holder en forbindelse åpen i 8 sekunder, så «lukkes» det."""
        print("app svarer på port", port, launcher.healthy(port))

        def hold():
            with socket.create_connection(("127.0.0.1", port)):
                time.sleep(8)
        threading.Thread(target=hold, daemon=True).start()

    launcher.open_window = fake_window
    launcher.FIRST_CONNECT, launcher.IDLE_STOP = 30, 4
    t = time.time()
    assert launcher.main() == 0, "launcheren returnerte feil"
    took = time.time() - t
    assert not launcher.STATE.exists()
    assert took >= 8, f"appen stoppet mens vinduet fortsatt var åpent (etter {took:.0f} s)"
    assert "vinduet er lukket" in (launcher.LOG.read_text(encoding="utf-8")), "stoppet av feil grunn"
    print(f"OK: appen levde mens vinduet var åpent og stoppet {took:.0f} s etter start")


def report(text: str) -> None:
    """Skriv feilen som en GitHub-annotation (synlig for alle uten innlogging)."""
    for name in ("server.log", "launcher.log"):
        f = DATA / name
        if f.exists():
            text += f"\n\n--- {name} ---\n" + "\n".join(f.read_text(encoding="utf-8", errors="replace").splitlines()[-25:])
    text = text[-3500:].replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::error title=Røyktest feilet: {current}::{text}", flush=True)


if __name__ == "__main__":
    try:
        run()
    except BaseException:
        tb = traceback.format_exc()
        print(tb, flush=True)
        report(tb)
        sys.exit(1)
    print("\nAlt virker ✅")
