"""Valgfri AI-kategorisering med Claude. AVSLÅTT som standard.

Personvern: bare butikknavn/tekst sendes. Aldri beløp, dato, kontonummer eller
personnavn fra Vipps-overføringer. Tekster som ser ut som overføringer til
personer filtreres bort før sending. Forslagene må godkjennes før de lagres.

Krever `pip install anthropic` og en API-nøkkel (ANTHROPIC_API_KEY eller `ant auth login`).
"""
from __future__ import annotations

import json
import re

from .categorize import EXPENSE_CATEGORIES, merchant_key

MODEL = "claude-opus-5-5"

# Tekst som sannsynligvis inneholder navnet på en privatperson, sendes ikke
_PERSONAL = re.compile(r"\b(vipps|mobilepay|overføring|overf|fra:|til:|giro|nettbank)\b", re.I)
_DIGITS = re.compile(r"\d{5,}")


def safe_texts(texts: list[str]) -> list[str]:
    """Gjør tekstene om til butikknøkler og fjerner alt som kan være personlig."""
    out: list[str] = []
    for t in texts:
        if _PERSONAL.search(t):
            continue
        k = _DIGITS.sub("", merchant_key(t)).strip()
        if k and k not in out:
            out.append(k)
    return out


def suggest_categories(merchants: list[str], model: str = MODEL) -> dict[str, str]:
    """Returnerer {butikknøkkel: kategori}. Kaster RuntimeError med norsk feilmelding ved problemer."""
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("Pakken «anthropic» er ikke installert. Kjør: pip install anthropic") from e
    if not merchants:
        return {}
    cats = [c for c in EXPENSE_CATEGORIES if c != "Ukategorisert"]
    schema = {
        "type": "object",
        "properties": {
            "forslag": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "butikk": {"type": "string"},
                        "kategori": {"type": "string", "enum": cats + ["Vet ikke"]},
                    },
                    "required": ["butikk", "kategori"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["forslag"],
        "additionalProperties": False,
    }
    prompt = (
        "Du kategoriserer butikknavn fra norske kontoutskrifter. Velg den mest sannsynlige "
        "kategorien for hvert navn. Svar «Vet ikke» hvis du ikke kjenner igjen navnet. "
        "Returner ett forslag per butikk, med butikknavnet skrevet nøyaktig som i listen.\n\n"
        "Butikker:\n" + "\n".join(f"- {m}" for m in merchants)
    )
    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError as e:
        raise RuntimeError("Mangler eller ugyldig API-nøkkel. Sett ANTHROPIC_API_KEY eller kjør «ant auth login».") from e
    except anthropic.RateLimitError as e:
        raise RuntimeError("For mange forespørsler akkurat nå. Prøv igjen om litt.") from e
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Feil fra Claude-API-et ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError("Fikk ikke kontakt med Claude-API-et. Sjekk nettforbindelsen.") from e

    if response.stop_reason == "refusal":
        raise RuntimeError("Forespørselen ble avvist av modellen.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Svaret ble for langt. Prøv færre butikker om gangen.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    data = json.loads(text)
    wanted = set(merchants)
    return {f["butikk"]: f["kategori"] for f in data.get("forslag", [])
            if f["butikk"] in wanted and f["kategori"] in cats}
