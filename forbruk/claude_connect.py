"""Kobler appen til Claude Desktop ved å legge MCP-serveren inn i Claude sin konfigurasjonsfil."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from . import config

NAME = "forbruksapp"
SERVER = config.PROJECT_DIR / "mcp_server.py"


def _windows_config_dirs() -> list[Path]:
    """Mulige mapper for Claude-appens innstillinger på Windows.

    Installert fra claude.ai/download (MSIX/Microsoft Store-pakke) skriver appen til en egen
    pakkemappe under %LOCALAPPDATA%\\Packages, ikke til %APPDATA%\\Claude."""
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    packaged = sorted(local.glob("Packages/Claude_*/LocalCache/Roaming/Claude"))
    packaged += sorted(local.glob("Packages/AnthropicPBC.Claude*/LocalCache/Roaming/Claude"))
    return packaged + [roaming / "Claude"]


def _windows_app_installed() -> bool:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return (any(d.exists() for d in _windows_config_dirs()) or (local / "AnthropicClaude").exists()
            or any(local.glob("Packages/Claude_*")) or any(local.glob("Packages/AnthropicPBC.Claude*")))


def desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if os.name == "nt":
        dirs = _windows_config_dirs()
        # Bruk den mappen appen faktisk bruker (finnes allerede), ellers pakkemappen, ellers %APPDATA%
        folder = next((d for d in dirs if d.exists()), dirs[0])
        return folder / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def desktop_installed() -> bool:
    if os.name == "nt":
        return _windows_app_installed()
    return desktop_config_path().parent.exists()


def _python() -> str:
    """Claude starter appens MCP-server selv – den trenger vanlig python.exe (pythonw har ingen stdin/stdout)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return str(exe)


def server_entry() -> dict:
    entry = {"command": _python(), "args": ["-X", "utf8", str(SERVER)]}
    if os.environ.get("FORBRUKSAPP_DIR"):
        entry["env"] = {"FORBRUKSAPP_DIR": str(config.DATA_DIR)}
    return entry


def _read(path: Path) -> dict:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def is_connected(path: Path | None = None) -> bool:
    try:
        return NAME in _read(path or desktop_config_path()).get("mcpServers", {})
    except (OSError, json.JSONDecodeError):
        return False


def connect(path: Path | None = None) -> Path:
    """Legger til appen i Claude Desktop. Andre innstillinger beholdes, og det tas en sikkerhetskopi."""
    path = path or desktop_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read(path)                       # kaster JSONDecodeError hvis filen er ødelagt – da rører vi den ikke
    if path.exists():
        shutil.copy2(path, path.with_suffix(".json.bak"))
    data.setdefault("mcpServers", {})[NAME] = server_entry()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def disconnect(path: Path | None = None) -> None:
    path = path or desktop_config_path()
    data = _read(path)
    if NAME in data.get("mcpServers", {}):
        shutil.copy2(path, path.with_suffix(".json.bak"))
        del data["mcpServers"][NAME]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def claude_code_command() -> str:
    e = server_entry()
    env = "".join(f" -e {k}={shlex.quote(v)}" for k, v in e.get("env", {}).items())
    args = " ".join(shlex.quote(a) for a in e["args"])
    return f"claude mcp add {NAME} --scope user{env} -- {shlex.quote(e['command'])} {args}"
