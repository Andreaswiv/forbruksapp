"""Starter «Pengene mine» som et vanlig program.

Snarveien på skrivebordet peker hit. Launcheren
1. starter appen i bakgrunnen (uten svart konsollvindu),
2. åpner den i et eget vindu (Edge/Chrome i «app-modus», uten adresselinje),
3. stopper appen igjen når vinduet lukkes.

Trykker man på ikonet mens appen allerede kjører, åpnes bare et nytt vindu.
All data ligger lokalt i brukerens hjemmemappe (~/.forbruksapp), aldri i programmappen.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("FORBRUKSAPP_DIR", Path.home() / ".forbruksapp"))
STATE = DATA_DIR / "kjorer.json"           # port og prosess-id når appen kjører
LOG = DATA_DIR / "launcher.log"
WINDOWS = sys.platform == "win32"
NO_WINDOW = 0x08000000 if WINDOWS else 0   # CREATE_NO_WINDOW


def log(msg: str) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except OSError:
        pass


def healthy(port: int, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def free_port() -> int:
    for port in range(8601, 8700):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def python_for_server() -> str:
    """Samme Python som launcheren, men aldri et konsollvindu på Windows."""
    exe = Path(sys.executable)
    if WINDOWS and exe.name.lower() == "python.exe" and (exe.parent / "pythonw.exe").exists():
        return str(exe.parent / "pythonw.exe")
    return str(exe)


def start_server() -> tuple[subprocess.Popen, int]:
    port = free_port()
    # -X utf8: æøå fungerer likt overalt (den innebygde Python-en på Windows ignorerer PYTHONUTF8)
    cmd = [python_for_server(), "-X", "utf8", "-m", "streamlit", "run", str(HERE / "app.py"),
           "--server.port", str(port), "--server.address", "127.0.0.1", "--server.headless", "true",
           "--browser.gatherUsageStats", "false", "--global.developmentMode", "false",
           "--server.fileWatcherType", "none", "--server.runOnSave", "false"]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = (DATA_DIR / "server.log").open("w", encoding="utf-8")
    env = dict(os.environ, PYTHONUTF8="1")
    proc = subprocess.Popen(cmd, cwd=HERE, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            creationflags=NO_WINDOW, env=env)
    log(f"startet server pid={proc.pid} port={port}")
    return proc, port


def find_app_browser() -> str | None:
    """Edge finnes på alle Windows-PC-er; Chrome brukes hvis det er det som finnes."""
    candidates: list[str] = []
    if WINDOWS:
        for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                candidates += [rf"{base}\Microsoft\Edge\Application\msedge.exe",
                               rf"{base}\Google\Chrome\Application\chrome.exe"]
    elif sys.platform == "darwin":
        candidates += ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                       "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    else:
        candidates += [shutil.which(n) or "" for n in ("microsoft-edge", "google-chrome", "chromium")]
    return next((c for c in candidates if c and Path(c).exists()), None)


def open_window(port: int) -> subprocess.Popen | None:
    """Åpner appen i eget vindu. Returnerer prosessen hvis vi kan vente på at vinduet lukkes."""
    url = f"http://127.0.0.1:{port}"
    browser = find_app_browser()
    if browser:
        # Egen profil = egen prosess som lever akkurat så lenge vinduet er åpent
        profile = DATA_DIR / "vindu"
        cmd = [browser, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
               "--no-default-browser-check", "--disable-features=Translate", "--window-size=1280,880"]
        log(f"åpner vindu med {Path(browser).name}")
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("fant ingen Edge/Chrome – åpner i standard nettleser")
    webbrowser.open(url)
    return None


def running_port() -> int | None:
    try:
        port = int(json.loads(STATE.read_text())["port"])
    except (OSError, ValueError, KeyError):
        return None
    return port if healthy(port) else None


def show_error(text: str) -> None:
    log("FEIL: " + text)
    if WINDOWS:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, "Pengene mine", 0x10)
    else:
        print(text, file=sys.stderr)


def main() -> int:
    port = running_port()
    if port:                                   # kjører allerede – bare åpne et nytt vindu
        open_window(port)
        return 0

    server, port = start_server()
    try:
        deadline = time.time() + 90             # første start kan ta litt tid
        while not healthy(port):
            if server.poll() is not None:
                show_error("Appen klarte ikke å starte.\n\nSe filen server.log i mappen\n" + str(DATA_DIR))
                return 1
            if time.time() > deadline:
                show_error("Appen brukte for lang tid på å starte. Prøv igjen.")
                return 1
            time.sleep(0.3)
        STATE.write_text(json.dumps({"port": port, "pid": server.pid}))
        window = open_window(port)
        if window is None:
            server.wait()                       # vanlig nettleser: la appen kjøre til PC-en slås av
        else:
            window.wait()
            # Vinduet kan ha blitt overtatt av en annen prosess med samme profil – vent til alle er lukket
            lock = DATA_DIR / "vindu" / "lockfile"
            while lock.exists() and _locked(lock):
                time.sleep(1)
            log("vinduet er lukket – stopper appen")
    finally:
        try:
            STATE.unlink()
        except OSError:
            pass
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(10)
            except subprocess.TimeoutExpired:
                server.kill()
    return 0


def _locked(path: Path) -> bool:
    """Edge/Chrome holder «lockfile» åpen på Windows så lenge profilen er i bruk."""
    if not WINDOWS:
        return False
    try:
        os.rename(path, path)                   # lykkes bare når ingen har filen åpen
        return False
    except OSError:
        return True


if __name__ == "__main__":
    sys.exit(main())
