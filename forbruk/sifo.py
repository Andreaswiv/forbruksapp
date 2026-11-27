"""Sammenligning med SIFOs referansebudsjett (OsloMet).

Satsene ligger i data/sifo_satser.json og må oppdateres med offisielle tall hvert år.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import config

# Hvilke av appens kategorier som teller mot hver SIFO-post. Kan endres i appen.
DEFAULT_MAPPING: dict[str, list[str]] = {
    "Mat og drikke": ["Dagligvarer"],
    "Klær og sko": ["Klær og sko"],
    "Personlig pleie": ["Personlig pleie"],
    "Lek, sport og mediebruk": ["Fritid"],
    "Reisekostnader": ["Transport"],
    "Andre dagligvarer": [],
    "Husholdningsartikler": ["Husholdning"],
    "Møbler": [],
    "Mediebruk og fritid": ["Abonnementer", "Elektronikk"],
    "Bilkostnader": ["Bil"],
}

NOT_IN_SIFO_NOTE = {
    "Bolig": "SIFO dekker ikke boutgifter (husleie, lån, strøm).",
    "Lån": "Lån og renter er ikke med i SIFO.",
    "Restaurant og takeaway": "SIFO har ingen egen post for restaurant og takeaway.",
    "Alkohol": "Alkohol og tobakk er ikke med i SIFO.",
    "Reise": "Ferie og reiser er ikke med i SIFO.",
    "Helse": "SIFO dekker bare enkel helse/hygiene under personlig pleie.",
    "Gaver": "Gaver er ikke en egen post i SIFO.",
}


def load_rates(path: Path | None = None) -> dict:
    p = Path(path) if path else config.SIFO_FILE
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def individual_rate(rows: list[dict], age: int, sex: str) -> float:
    """Finn satsen for én person i én SIFO-post (hver post har egne alders-/kjønnsgrupper)."""
    for r in rows:
        if r["alder_fra"] <= age <= r["alder_til"] and r["kjønn"] in ("alle", sex):
            return float(r["beløp"])
    return 0.0


def car_type(household: dict) -> str | None:
    car = household.get("bil")
    if car is True:          # eldre lagret verdi
        return "bensin"
    return car if car in ("bensin", "el") else None


def household_budget(household: dict, rates: dict) -> pd.Series:
    """household = {"medlemmer": [{"alder": 28, "kjønn": "mann"}, ...], "bil": "bensin" | "el" | False}"""
    members = household.get("medlemmer") or []
    totals: dict[str, float] = {}
    for cat, rows in rates["individ"].items():
        totals[cat] = sum(individual_rate(rows, int(m.get("alder", 0)), m.get("kjønn", "kvinne"))
                          for m in members)
    if members:
        for cat, spec in rates["husholdning"].items():
            n = sum(1 for m in members if int(m.get("alder", 0)) >= spec.get("telles_fra_alder", 0))
            table = spec["per_antall"]
            n = min(max(n, 1), max(int(k) for k in table))
            totals[cat] = float(table[str(n)])
    car = car_type(household)
    if car and members:
        brackets = rates.get("bil", {}).get(car, {})
        for bracket, val in brackets.items():
            lo, hi = (int(x) for x in bracket.split("-"))
            if lo <= len(members) <= hi:
                totals["Bilkostnader"] = float(val)
    return pd.Series(totals, dtype=float)


def compare(monthly_by_cat: pd.Series, household: dict, rates: dict,
            mapping: dict[str, list[str]] | None = None) -> pd.DataFrame:
    mapping = mapping or DEFAULT_MAPPING
    budget = household_budget(household, rates)
    rows = []
    for sifo_cat, sifo_val in budget.items():
        mine = mapping.get(sifo_cat, [])
        my_val = float(sum(monthly_by_cat.get(c, 0) for c in mine))
        diff = my_val - sifo_val
        pct = diff / sifo_val * 100 if sifo_val else 0.0
        rows.append({"Kategori": sifo_cat, "Mine kategorier": ", ".join(mine) or "–",
                     "Mitt_snitt": my_val, "SIFO": sifo_val, "Differanse": diff, "Prosent": pct})
    return pd.DataFrame(rows)


def unmapped_categories(monthly_by_cat: pd.Series, mapping: dict[str, list[str]] | None = None) -> pd.DataFrame:
    mapping = mapping or DEFAULT_MAPPING
    mapped = {c for cats in mapping.values() for c in cats}
    rows = [{"Kategori": c, "Mitt snitt per måned": float(v),
             "Merknad": NOT_IN_SIFO_NOTE.get(c, "Ikke koblet til en SIFO-post.")}
            for c, v in monthly_by_cat.items() if c not in mapped and v > 0]
    return pd.DataFrame(rows)
