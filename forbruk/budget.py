"""Budsjettforslag, oppfølging mot budsjett, felles økonomi og Excel-eksport."""
from __future__ import annotations

import io

import pandas as pd

from . import analysis
from .categorize import EXPENSE_CATEGORIES

FIXED_CATEGORIES = {"Bolig", "Lån", "Abonnementer"}
NEEDS = {"Bolig", "Lån", "Dagligvarer", "Transport", "Bil", "Helse", "Barn", "Gebyrer og renter"}

# Hvor mye vi foreslår å kutte i kategorier der det ofte er lett å spare
DEFAULT_CUTS = {
    "Restaurant og takeaway": 0.30, "Alkohol": 0.25, "Klær og sko": 0.15, "Elektronikk": 0.20,
    "Fritid": 0.10, "Gebyrer og renter": 0.50, "Kontantuttak": 0.20, "Personlig pleie": 0.10,
    "Husholdning": 0.10, "Vipps": 0.10, "Annet": 0.10,
}


def _round(x: float, step: int = 100) -> float:
    return float(round(x / step) * step)


def suggest(df: pd.DataFrame, sifo_cmp: pd.DataFrame | None = None, sifo_mapping: dict | None = None,
            subs=None, n_periods: int = 3) -> tuple[pd.DataFrame, dict]:
    avg = analysis.monthly_average_by_category(df, n_periods)
    income = analysis.average_income(df, n_periods)
    over_sifo: dict[str, float] = {}
    if sifo_cmp is not None and not sifo_cmp.empty and sifo_mapping:
        for r in sifo_cmp.itertuples():
            cats = sifo_mapping.get(r.Kategori, [])
            if len(cats) == 1 and r.Differanse > 0:
                over_sifo[cats[0]] = r.SIFO

    overlap_saving = 0.0
    if subs:
        from .subscriptions import overlaps
        for lst in overlaps(subs).values():
            overlap_saving += sum(sorted(x.monthly for x in lst)[:-1])

    rows = []
    for cat in EXPENSE_CATEGORIES:
        a = float(avg.get(cat, 0))
        if a <= 0 or cat == "Ukategorisert":
            continue
        target = a * (1 - DEFAULT_CUTS.get(cat, 0))
        reason = f"−{DEFAULT_CUTS[cat] * 100:.0f} % (lett å kutte)" if cat in DEFAULT_CUTS else "som i dag"
        if cat in over_sifo:
            mid = (a + over_sifo[cat]) / 2
            if mid < target:
                target, reason = mid, "halvveis ned mot SIFO-nivå"
        if cat == "Abonnementer" and overlap_saving > 0:
            target, reason = a - overlap_saving, "uten overlappende abonnementer"
        kind = "fast" if cat in FIXED_CATEGORIES else "variabel"
        rows.append({"category": cat, "snitt": round(a), "amount": _round(target), "kind": kind,
                     "begrunnelse": reason})
    unc = float(avg.get("Ukategorisert", 0))
    if unc > 0:
        rows.append({"category": "Ukategorisert", "snitt": round(unc), "amount": _round(unc),
                     "kind": "variabel", "begrunnelse": "kategoriser for bedre forslag"})

    df_b = pd.DataFrame(rows)
    total = float(df_b["amount"].sum()) if not df_b.empty else 0.0
    target_saving = income * 0.20
    available = income - total
    saving = max(0.0, min(target_saving, available)) if income > 0 else 0.0
    df_b = pd.concat([df_b, pd.DataFrame([{
        "category": "Sparing", "snitt": round(float(analysis.savings(df[df["period"].isin(
            analysis.complete_periods(df, n_periods))])["saved"].sum()) / max(len(analysis.complete_periods(df, n_periods)), 1)),
        "amount": _round(saving), "kind": "sparing",
        "begrunnelse": "20 % av inntekten" if saving >= target_saving - 1 else "det som er igjen etter budsjettet"}])],
        ignore_index=True)

    needs = float(df_b[df_b["category"].isin(NEEDS)]["amount"].sum())
    wants = float(df_b[(~df_b["category"].isin(NEEDS)) & (df_b["kind"] != "sparing")]["amount"].sum())
    info = {"inntekt": income, "sum_utgifter": total, "sparing": saving, "behov": needs, "ønsker": wants,
            "rest": income - total - saving}
    return df_b, info


def fifty_thirty_twenty(income: float) -> dict:
    return {"behov": income * 0.5, "ønsker": income * 0.3, "sparing": income * 0.2}


def status(df: pd.DataFrame, budget: pd.DataFrame, period: str) -> pd.DataFrame:
    """Budsjett mot faktisk forbruk i én periode."""
    if budget.empty:
        return pd.DataFrame()
    p = df[df["period"] == period]
    spent = analysis.spending(p).groupby("category")["spend"].sum()
    saved = analysis.savings(p)["saved"].sum()
    rows = []
    for r in budget.itertuples(index=False):
        actual = float(saved) if r.kind == "sparing" else float(spent.get(r.category, 0))
        left = r.amount - actual
        pct = actual / r.amount * 100 if r.amount else 0
        rows.append({"Kategori": r.category, "Type": r.kind, "Budsjett": r.amount, "Brukt": actual,
                     "Igjen": left, "Brukt %": pct})
    extra = [c for c in spent.index if c not in set(budget["category"]) and spent[c] > 0]
    for c in extra:
        rows.append({"Kategori": c, "Type": "ikke budsjettert", "Budsjett": 0.0, "Brukt": float(spent[c]),
                     "Igjen": -float(spent[c]), "Brukt %": 100.0})
    return pd.DataFrame(rows)


def shared_split(df: pd.DataFrame, my_share_pct: float, shared_categories: list[str]) -> dict:
    """Felles økonomi: hvem har betalt hva av felles utgifter, og hvem skylder hvem."""
    s = analysis.spending(df)
    shared = s[s["is_shared"] | s["category"].isin(shared_categories)]
    total = float(shared["spend"].sum())
    paid_me = float(shared[shared["owner"] == "meg"]["spend"].sum())
    paid_partner = float(shared[shared["owner"] == "partner"]["spend"].sum())
    my_share = total * my_share_pct / 100
    # Positivt = jeg skylder partner
    i_owe = my_share - paid_me
    by_cat = shared.groupby(["category", "owner"])["spend"].sum().unstack(fill_value=0)
    return {"total": total, "betalt_meg": paid_me, "betalt_partner": paid_partner,
            "min_andel": my_share, "partner_andel": total - my_share, "jeg_skylder": i_owe,
            "per_kategori": by_cat, "rader": shared}


def to_excel(budget: pd.DataFrame, status_df: pd.DataFrame | None = None, info: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xw:
        b = budget.rename(columns={"category": "Kategori", "amount": "Budsjett per måned",
                                   "kind": "Type", "snitt": "Snitt i dag", "begrunnelse": "Begrunnelse"})
        b.to_excel(xw, sheet_name="Budsjett", index=False)
        ws = xw.sheets["Budsjett"]
        money = xw.book.add_format({"num_format": "# ##0 \"kr\""})
        ws.set_column(0, 0, 26)
        ws.set_column(1, 3, 18, money)
        ws.set_column(4, 4, 36)
        if status_df is not None and not status_df.empty:
            status_df.to_excel(xw, sheet_name="Status", index=False)
            xw.sheets["Status"].set_column(0, 1, 22)
            xw.sheets["Status"].set_column(2, 4, 14, money)
        if info:
            pd.DataFrame([{"Post": k.capitalize(), "Beløp per måned": round(v)} for k, v in info.items()]) \
              .to_excel(xw, sheet_name="Nøkkeltall", index=False)
    return buf.getvalue()
