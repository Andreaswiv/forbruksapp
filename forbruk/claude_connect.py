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


def desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def desktop_installed() -> bool:
    return desktop_config_path().parent.exists()


def server_entry() -> dict:
    entry = {"command": sys.executable, "args": [str(SERVER)]}
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
    return f"claude mcp add {NAME} --scope user{env} -- {shlex.quote(e['command'])} {shlex.quote(e['args'][0])}"
