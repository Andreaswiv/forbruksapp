"""AI-hjelp til kategorisering med Claude. AVSLÅTT som standard.

Tre måter å koble til Claude på:
1. Claude Desktop (anbefalt): appen er en MCP-server (mcp_server.py). Du spør Claude i
   Claude-appen på PC-en, og Claude henter de ukjente utgiftene og lagrer kategorier.
2. Claude Code på PC-en («claude»-kommandoen): appen spør Claude direkte, med ditt eget abonnement.
3. API-nøkkel (ANTHROPIC_API_KEY): for utviklere.

Personvern – det eneste som sendes, er butikktekster som er anonymisert:
- Aldri beløp, datoer, kontonummer, kortnummer, telefon, e-post eller saldo.
- Navn på personer erstattes med «Person 1», «Person 2» …, og navnet ditt med «Deg selv»
  (se anonymize.py). Koblingen mellom nummer og navn blir på maskinen.
- Hver utgift får et tilfeldig utseende id («k3f9a…»). Svaret kobles tilbake lokalt.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import categorize, db
from .anonymize import Anonymizer
from .categorize import EXPENSE_CATEGORIES, INCOME_CATEGORIES

MODEL = "claude-opus-5-5"
CLI_MODELS = ["sonnet", "haiku"]      # Claude Code-aliaser, prøves i rekkefølge
UNKNOWN = "Vet ikke"
CATEGORIES = [c for c in EXPENSE_CATEGORIES if c != "Ukategorisert"] + ["Sparing"] + INCOME_CATEGORIES
PROMPT_INTRO = (
    "Du hjelper en ung person i Norge med å kategorisere utgifter fra kontoutskriften sin. "
    "Hver linje er en anonymisert transaksjonstekst fra et kortkjøp eller en betaling. "
    "«retning» sier om penger gikk ut eller kom inn.\n\n"
    "Gi ALLTID ditt beste forslag til kategori, også når du ikke kjenner igjen navnet – bruk alle hint i teksten. "
    "Sett «sikker» til true hvis du kjenner igjen stedet eller det er helt tydelig, og false hvis det er en gjetning. "
    "Bruk «Vet ikke» bare når teksten ikke gir noe hint i det hele tatt.\n\n"
    "Nyttige hint:\n"
    "- «Person 1», «Person 2» … er anonymiserte privatpersoner, «Deg selv» er eieren. Penger ut til en person er "
    "som regel «Vipps», penger inn fra en person «Inntekt annet». «… penger tilbake» betyr at eieren betaler en venn tilbake (Vipps).\n"
    "- Firmaformer sier hvilket land: EOOD/OOD/EAD = Bulgaria, SRL/SPA/SNC = Italia, SL/SA = Spania, LTD = Storbritannia/Kypros, "
    "AB = Sverige, ApS = Danmark. Ukjente småbutikker i utlandet er oftest restaurant, kafé, bar, kiosk eller suvenirbutikk – "
    "sannsynligvis på ferie.\n"
    "- Norske gatenavn + by (f.eks. «MARKENS GATE KRISTIANSAND», «TOLLBODGATA») i sentrum er ofte utesteder, barer eller kafeer.\n"
    "- Ord som BAR, PUB, ØLBAR → Alkohol. KAFE, COFFEE, ESPRESSO, PIZZA, GRILL, GYROS → Restaurant og takeaway. "
    "SUPERMERCATO, MARKET, MATVARER → Dagligvarer. BOOKING, HOTEL, CAMPING → Reise. BUS, TOG, TAXI → Transport. "
    "SPORT, BOWLING, KINO, BILLETT/TICKET → Fritid. FARMACIA/APOTEK → Helse.\n"
    "- Klarna, Revolut, PayPal-påfylling og lignende er betaling av gjeld eller overføring – velg «Annet» med sikker=false.\n\n"
    "Returner ett forslag for HVER linje, med id-en nøyaktig slik den står."
)
BATCH = 40          # linjer per forespørsel


# --------------------------------------------------------------------- hva som sendes
@dataclass
class Item:
    id: str           # tilfeldig utseende nøkkel som sendes
    key: str          # butikknøkkel – blir på maskinen, brukes som regel
    text: str         # anonymisert tekst – dette sendes
    direction: str    # «ut» eller «inn»
    count: int

    def public(self) -> dict:
        return {"id": self.id, "tekst": self.text, "retning": self.direction}


def _known_merchant(conn):
    rules = [r for r in categorize.all_rules(conn) if r.source != "generic"]
    return lambda text: categorize.match_category(text, -1, rules) is not None or \
        categorize.match_category(text, 1, rules) is not None


def _item_id(key: str) -> str:
    return "k" + hashlib.sha256(key.encode()).hexdigest()[:10]


def build_items(conn, df: pd.DataFrame | None = None, limit: int = 80) -> list[Item]:
    """Ukjente utgifter, gruppert per butikk og anonymisert. Bare tekst, ingen beløp eller datoer."""
    df = db.load_transactions(conn) if df is None else df
    if df.empty:
        return []
    unc = df[(df["category"] == "Ukategorisert") & (~df["is_transfer"].astype(bool))]
    if unc.empty:
        return []
    unc = unc.assign(key=unc["text"].map(categorize.merchant_key))
    groups = (unc.groupby("key")
              .agg(n=("id", "size"), total=("amount", "sum"),
                   ex=("text", lambda s: s.value_counts().index[0]))
              .sort_values("n", ascending=False))
    anon = Anonymizer(db.get_setting(conn, "user_name", ""), _known_merchant(conn))
    items: list[Item] = []
    seen: set[str] = set()
    for key, g in groups.iterrows():
        if not key:
            continue
        text = anon.anonymize(g.ex)
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(Item(_item_id(key), key, text, "ut" if g.total < 0 else "inn", int(g.n)))
        if len(items) >= limit:
            break
    return items


def save_suggestions(conn, items: list[Item], suggestions: dict[str, str]) -> int:
    """Lagrer forslag som regler (kilde «ai»). Returnerer antall lagret."""
    by_id = {i.id: i for i in items}
    n = 0
    for item_id, cat in suggestions.items():
        item = by_id.get(item_id)
        if item and cat in CATEGORIES:
            categorize.add_rule(conn, item.key, cat, source="ai")
            n += 1
    if n:
        categorize.refresh(conn)
    return n


# --------------------------------------------------------------------- Claude på PC-en
def find_claude_cli() -> str | None:
    """Finner «claude»-kommandoen (Claude Code) på maskinen, også den som følger med Claude-appen."""
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    candidates = [home / ".claude" / "local" / "claude", home / ".local" / "bin" / "claude",
                  Path("/opt/homebrew/bin/claude"), Path("/usr/local/bin/claude")]
    candidates += [Path(p) for p in sorted(glob.glob(str(
        home / "Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude")), reverse=True)]
    candidates += [Path(p) for p in glob.glob(os.path.expandvars(r"%APPDATA%\Claude\claude-code\*\claude.exe"))]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def backends() -> dict[str, str]:
    out = {}
    if find_claude_cli():
        out["claude_code"] = "Claude på denne PC-en (ditt eget abonnement)"
    if has_api_key():
        out["api"] = "Claude-API (API-nøkkel)"
    return out


def _schema() -> dict:
    return {
        "type": "object",
        "properties": {"forslag": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"},
                           "kategori": {"type": "string", "enum": CATEGORIES + [UNKNOWN]},
                           "sikker": {"type": "boolean"}},
                           "required": ["id", "kategori", "sikker"], "additionalProperties": False}}},
        "required": ["forslag"], "additionalProperties": False,
    }


def _prompt(items: list[Item]) -> str:
    return PROMPT_INTRO + "\n\n" + json.dumps([i.public() for i in items], ensure_ascii=False, indent=1)


def _parse(data: dict, items: list[Item]) -> dict[str, dict]:
    """{id: {"kategori": …, "sikker": bool}} – «Vet ikke» og ukjente id-er tas ikke med."""
    wanted = {i.id for i in items}
    return {f["id"]: {"kategori": f["kategori"], "sikker": bool(f.get("sikker", False))}
            for f in data.get("forslag", []) if f.get("id") in wanted and f.get("kategori") in CATEGORIES}


def _via_claude_code(items: list[Item]) -> dict[str, dict]:
    cli = find_claude_cli()
    if not cli:
        raise RuntimeError("Fant ikke Claude på PC-en. Installer Claude Code, eller bruk Claude Desktop-koblingen.")
    last_error = ""
    # Kategorisering er en enkel oppgave. Bruk en vanlig modell som finnes i alle abonnementer,
    # ikke en som krever ekstra kreditter.
    for model in CLI_MODELS:
        cmd = [cli, "-p", "--model", model, "--output-format", "json", "--json-schema", json.dumps(_schema()),
               "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--setting-sources", "",
               "--disable-slash-commands"]
        # Kjør i en tom mappe, så Claude ikke ser andre filer
        with tempfile.TemporaryDirectory() as tmp:
            try:
                p = subprocess.run(cmd, input=_prompt(items), capture_output=True, text=True, cwd=tmp, timeout=240)
            except subprocess.TimeoutExpired as e:
                raise RuntimeError("Claude brukte for lang tid. Prøv igjen.") from e
        try:
            out = json.loads(p.stdout)
        except json.JSONDecodeError as e:
            msg = (p.stderr or p.stdout).strip()[:300]
            if "login" in msg.lower() or "auth" in msg.lower():
                msg = "Du må logge inn i Claude først (åpne Claude og logg inn)."
            raise RuntimeError(f"Claude svarte ikke som forventet. {msg}") from e
        if out.get("is_error"):
            last_error = str(out.get("result", ""))[:300]
            continue
        data = out.get("structured_output")
        if data is None:
            txt = str(out.get("result", "")).strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            data = json.loads(txt)
        return _parse(data, items)
    raise RuntimeError(f"Claude ga en feil: {last_error}")


def _via_api(items: list[Item], model: str = MODEL) -> dict[str, dict]:
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("Pakken «anthropic» er ikke installert. Kjør: pip install anthropic") from e
    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": _schema()}},
            messages=[{"role": "user", "content": _prompt(items)}],
        )
    except anthropic.AuthenticationError as e:
        raise RuntimeError("Mangler eller ugyldig API-nøkkel. Sett ANTHROPIC_API_KEY.") from e
    except anthropic.RateLimitError as e:
        raise RuntimeError("For mange forespørsler akkurat nå. Prøv igjen om litt.") from e
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Feil fra Claude-API-et ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError("Fikk ikke kontakt med Claude. Sjekk nettforbindelsen.") from e
    if response.stop_reason == "refusal":
        raise RuntimeError("Forespørselen ble avvist av modellen.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Svaret ble for langt. Prøv færre utgifter om gangen.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    return _parse(json.loads(text), items)


def suggest(items: list[Item], backend: str, progress=None) -> dict[str, dict]:
    """Går gjennom ALLE linjene, BATCH om gangen.

    Returnerer {id: {"kategori": …, "sikker": bool}}. `progress(ferdig, totalt)` kalles etter hver runde.
    Kaster RuntimeError med norsk feilmelding ved problemer.
    """
    if backend not in ("claude_code", "api"):
        raise RuntimeError("Ingen kobling til Claude valgt.")
    call = _via_claude_code if backend == "claude_code" else _via_api
    out: dict[str, dict] = {}
    for start in range(0, len(items), BATCH):
        out.update(call(items[start:start + BATCH]))
        if progress:
            progress(min(start + BATCH, len(items)), len(items))
    return out
