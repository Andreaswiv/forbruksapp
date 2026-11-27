"""MCP-server: lar Claude-appen på PC-en (Claude Desktop eller Claude Code) hjelpe deg å kategorisere.

Claude får bare anonymiserte butikktekster – aldri beløp, datoer, kontonummer eller navn
på personer (de blir «Person 1», «Person 2» …). Se forbruk/anonymize.py.

Koble til fra appen (Innstillinger → AI-hjelp), eller manuelt i claude_desktop_config.json:
  "mcpServers": {"forbruksapp": {"command": "<prosjekt>/.venv/bin/python", "args": ["<prosjekt>/mcp_server.py"]}}

Protokollen (JSON-RPC over stdin/stdout) er skrevet for hånd, så det trengs ingen ekstra pakker.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forbruk import ai_categorize, config, db  # noqa: E402

SERVER_INFO = {"name": "forbruksapp", "title": "Pengene mine", "version": "1.0.0"}
INSTRUCTIONS = (
    "Verktøy for appen «Pengene mine», der brukeren har lastet opp kontoutskrifter. "
    "Når brukeren ber om hjelp med å kategorisere utgifter: kall hent_ukjente_utgifter, velg den mest "
    "sannsynlige kategorien for hver linje (bare fra listen «kategorier»), og lagre med lagre_kategorier. "
    "Hopp over linjer du er usikker på. «Person N» er anonymiserte privatpersoner og «Deg selv» er brukeren – "
    "ikke prøv å finne ut hvem de er. Fortell til slutt kort hva du lagret."
)

TOOLS = [
    {
        "name": "hent_ukjente_utgifter",
        "title": "Hent utgifter som mangler kategori",
        "description": "Henter utgifter i «Pengene mine» som mangler kategori, og listen over gyldige kategorier. "
                       "Tekstene er anonymisert: ingen beløp, datoer eller kontonummer, og personnavn er erstattet "
                       "med «Person 1», «Person 2» … («Deg selv» = brukeren).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "lagre_kategorier",
        "title": "Lagre kategorier",
        "description": "Lagrer kategorier for utgifter fra hent_ukjente_utgifter. Appen husker valget, så samme "
                       "butikk får samme kategori neste gang. Brukeren kan angre under Innstillinger i appen.",
        "inputSchema": {
            "type": "object",
            "properties": {"forslag": {"type": "array", "items": {
                "type": "object",
                "properties": {"id": {"type": "string", "description": "id fra hent_ukjente_utgifter"},
                               "kategori": {"type": "string", "enum": ai_categorize.CATEGORIES}},
                "required": ["id", "kategori"]}}},
            "required": ["forslag"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True,
                        "openWorldHint": False},
    },
]


def _conn():
    config.ensure_dirs()
    return db.connect()


def _guard(conn) -> str | None:
    if not db.get_setting(conn, "ai_enabled", False):
        return ("AI-hjelp er slått av i appen. Be brukeren åpne «Pengene mine» → Innstillinger → "
                "Personvern og slå på «AI-hjelp til kategorisering».")
    return None


def call_tool(name: str, args: dict) -> tuple[dict, bool]:
    conn = _conn()
    try:
        blocked = _guard(conn)
        if blocked:
            return {"feil": blocked}, True
        if name == "hent_ukjente_utgifter":
            items = ai_categorize.build_items(conn)
            return {"kategorier": ai_categorize.CATEGORIES,
                    "utgifter": [dict(i.public(), antall_kjøp=i.count) for i in items],
                    "merknad": "Ingen ukjente utgifter – alt er kategorisert." if not items else
                               "Lagre med lagre_kategorier. Hopp over det du er usikker på."}, False
        if name == "lagre_kategorier":
            items = ai_categorize.build_items(conn, limit=10_000)
            sugg = {f.get("id"): f.get("kategori") for f in args.get("forslag", []) if isinstance(f, dict)}
            n = ai_categorize.save_suggestions(conn, items, sugg)
            left = len(ai_categorize.build_items(conn, limit=10_000))
            return {"lagret": n, "ukjente_igjen": left,
                    "ugyldige": len(sugg) - n}, False
        return {"feil": f"Ukjent verktøy: {name}"}, True
    finally:
        conn.close()


def handle(msg: dict) -> dict | None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:                      # varsel, ingen svar
        return None
    if method == "initialize":
        version = (msg.get("params") or {}).get("protocolVersion", "2025-06-18")
        result = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params") or {}
        try:
            data, is_error = call_tool(p.get("name", ""), p.get("arguments") or {})
        except Exception as e:  # noqa: BLE001
            data, is_error = {"feil": f"Noe gikk galt i appen: {e}"}, True
        result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                  "structuredContent": data, "isError": is_error}
    elif method in ("resources/list", "prompts/list"):
        result = {method.split("/")[0]: []}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Ukjent metode: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Ugyldig JSON"}}
        else:
            out = handle(msg)
        if out is not None:
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
