"""Abonnementsjeger: finner faste, gjentakende trekk."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .categorize import merchant_key, merchant_label

INTERVALS = {           # navn: (typisk antall dager, toleranse, minste antall trekk)
    "ukentlig": (7, 2, 4),
    "månedlig": (30.4, 5, 2),
    "kvartalsvis": (91, 10, 2),
    "halvårlig": (182, 15, 2),
    "årlig": (365, 20, 2),
}

OVERLAP_GROUPS = {
    "Strømmetjenester (TV/film)": ["netflix", "hbo", "max", "viaplay", "disney", "tv 2", "tv2",
                                   "prime video", "amazon prime", "skyshowtime", "discovery",
                                   "strim", "allente", "apple tv"],
    "Musikk": ["spotify", "tidal", "apple music", "youtube music", "deezer"],
    "Lydbøker": ["storytel", "bookbeat", "audible", "nextory"],
    "Skylagring": ["icloud", "google one", "google storage", "dropbox", "onedrive"],
    "Trening": ["sats", "evo", "fresh fitness", "3t", "elixia", "actic", "spenst", "impulse"],
    "AI-verktøy": ["chatgpt", "openai", "anthropic", "claude", "copilot", "gemini"],
    "Nyheter": ["aftenposten", "vg+", "dagbladet", "dn", "schibsted", "amedia"],
}

EXCLUDED_CATEGORIES = {"Overføring", "Kontantuttak", "Lønn", "Inntekt annet", "Sparing",
                       "Dagligvarer", "Restaurant og takeaway"}


@dataclass
class Subscription:
    key: str
    name: str
    category: str
    interval: str
    interval_days: float
    amount: float              # typisk beløp per trekk (positivt)
    monthly: float
    yearly: float
    count: int
    first: pd.Timestamp
    last: pd.Timestamp
    next_expected: pd.Timestamp
    active: bool
    price_change: float | None  # siste beløp minus forrige typiske beløp
    overlap_group: str | None
    sample_text: str


def _cluster_amounts(amounts: np.ndarray, tol: float = 0.15) -> np.ndarray:
    """Grupperer beløp som ligger innen ±tol av hverandre (sortert, nabo for nabo)."""
    order = np.argsort(amounts)
    labels = np.empty(len(amounts), dtype=int)
    label, ref = 0, None
    for idx in order:
        a = amounts[idx]
        if ref is not None and a > ref * (1 + tol):
            label += 1
            ref = a
        if ref is None:
            ref = a
        labels[idx] = label
    return labels


def _classify_interval(diffs: np.ndarray) -> tuple[str, float] | None:
    if len(diffs) == 0:
        return None
    med = float(np.median(diffs))
    for name, (days, tol, _) in INTERVALS.items():
        if abs(med - days) <= tol:
            within = np.abs(diffs - days) <= tol * 1.6
            if within.mean() >= 0.6:
                return name, days
    return None


def _overlap_group(key: str, text: str) -> str | None:
    t = f"{key} {text}".lower()
    for group, words in OVERLAP_GROUPS.items():
        for w in words:
            if f" {w} " in f" {t} " or t.startswith(w):
                return group
    return None


def find_subscriptions(df: pd.DataFrame, reference_date: pd.Timestamp | None = None) -> list[Subscription]:
    """df: transaksjoner fra db.load_transactions()."""
    if df.empty:
        return []
    out = df[(df["amount"] < 0) & (~df["is_transfer"]) & (~df["category"].isin(EXCLUDED_CATEGORIES))].copy()
    if out.empty:
        return []
    ref = reference_date or df["date"].max()
    out["mkey"] = out["text"].map(merchant_key)
    out["abs"] = out["amount"].abs()
    subs: list[Subscription] = []

    for mkey, g in out.groupby("mkey"):
        if len(g) < 2:
            continue
        labels = _cluster_amounts(g["abs"].to_numpy())
        for lbl in np.unique(labels):
            c = g[labels == lbl].sort_values("date")
            # Slå sammen flere trekk samme dag (f.eks. delbetaling)
            c = c.groupby("date", as_index=False).agg(abs=("abs", "sum"), text=("text", "first"),
                                                       category=("category", "first"))
            if len(c) < 2:
                continue
            # Et abonnement dominerer kjøpene hos mottakeren. Mange andre kjøp med
            # varierende beløp hos samme mottaker = vanlig handel.
            if len(c) / len(g) < 0.5:
                continue
            diffs = c["date"].diff().dt.days.dropna().to_numpy()
            cls = _classify_interval(diffs)
            if not cls:
                continue
            name, days = cls
            if len(c) < INTERVALS[name][2]:
                continue
            amounts = c["abs"].to_numpy()
            typical = float(np.median(amounts[-6:]))
            # Variabelt beløp (f.eks. dagligvarer hver uke) er ikke et abonnement
            if np.mean(np.abs(amounts - typical) <= typical * 0.15) < 0.6:
                continue
            if name == "ukentlig" and c["category"].iloc[-1] in {"Dagligvarer", "Restaurant og takeaway"}:
                continue
            last_amount = float(amounts[-1])
            # Prisendring: sammenlign med siste trekk som hadde et annet beløp enn i dag
            changed = np.where(np.abs(amounts - last_amount) >= max(1.0, last_amount * 0.03))[0]
            price_change = float(last_amount - amounts[changed[-1]]) if len(changed) else None
            last = c["date"].iloc[-1]
            next_expected = last + pd.Timedelta(days=round(days))
            active = (ref - last).days <= days * 1.5 + 5
            monthly = last_amount * 30.44 / days
            key = f"{mkey}|{name}|{lbl}"
            subs.append(Subscription(
                key=key, name=merchant_label(mkey), category=c["category"].iloc[-1],
                interval=name, interval_days=days, amount=last_amount,
                monthly=monthly, yearly=monthly * 12, count=len(c),
                first=c["date"].iloc[0], last=last, next_expected=next_expected, active=active,
                price_change=price_change, overlap_group=_overlap_group(mkey, c["text"].iloc[-1]),
                sample_text=c["text"].iloc[-1],
            ))
    subs.sort(key=lambda s: (not s.active, -s.monthly))
    return subs


def to_frame(subs: list[Subscription], statuses: dict[str, str] | None = None) -> pd.DataFrame:
    statuses = statuses or {}
    rows = []
    for s in subs:
        rows.append({
            "key": s.key, "Navn": s.name, "Kategori": s.category, "Intervall": s.interval,
            "Beløp per trekk": round(s.amount, 2), "Per måned": round(s.monthly), "Per år": round(s.yearly),
            "Sist trukket": s.last.date(), "Neste forventet": s.next_expected.date() if s.active else None,
            "Antall trekk": s.count, "Aktiv": s.active,
            "Prisendring": round(s.price_change, 2) if s.price_change else None,
            "Overlapp": s.overlap_group, "Status": statuses.get(s.key, "Vurder"),
            "Eksempeltekst": s.sample_text,
        })
    return pd.DataFrame(rows)


def overlaps(subs: list[Subscription]) -> dict[str, list[Subscription]]:
    groups: dict[str, list[Subscription]] = {}
    for s in subs:
        if s.active and s.overlap_group:
            groups.setdefault(s.overlap_group, []).append(s)
    return {g: lst for g, lst in groups.items() if len(lst) >= 2}
