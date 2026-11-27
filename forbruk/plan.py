"""Budsjettplan for én måned: «Hva får jeg inn, hva er fast, hva har jeg planlagt – og hvordan fordeler jeg resten?»

En plan lagres som innstillingen «plan:ÅÅÅÅ-MM» og ser slik ut:
{
  "måned": "2026-12",
  "inntekter": [{"navn": "Lønn", "beløp": 14500}, ...],
  "faste":     [{"navn": "Husleie", "kategori": "Bolig", "beløp": 6500}, ...],
  "egne":      [{"navn": "Bursdag til mamma", "kategori": "Gaver", "beløp": 500}, ...],
  "sparing":   1500,
  "resten":    [{"kategori": "Dagligvarer", "beløp": 3000}, ...],
}
Planen gjelder kalendermåneder, uansett om appen ellers viser «lønn til lønn».
"""
from __future__ import annotations

import math

import pandas as pd

from . import analysis, db
from .budget import DEFAULT_CUTS, NEEDS
from .categorize import EXPENSE_CATEGORIES, merchant_key, merchant_label

# Øk når forslagslogikken endres, så åpne økter får et nytt forslag
SUGGESTION_VERSION = 5

MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober",
          "november", "desember"]


# ---------------------------------------------------------------- måneder
def month_name(month: str) -> str:
    p = pd.Period(month, "M")
    return f"{MONTHS[p.month - 1]} {p.year}"


def this_month(today: pd.Timestamp | None = None) -> str:
    return str((today or pd.Timestamp.today()).to_period("M"))


def next_month(today: pd.Timestamp | None = None) -> str:
    return str((today or pd.Timestamp.today()).to_period("M") + 1)


def with_months(df: pd.DataFrame) -> pd.DataFrame:
    return df.assign(month=df["date"].dt.to_period("M").astype(str))


def complete_months(df: pd.DataFrame, n: int = 3) -> list[str]:
    """De siste n hele kalendermånedene i dataene (en måned er hel hvis det finnes data etter den)."""
    if df.empty:
        return []
    last = df["date"].max()
    last_month = last.to_period("M")
    # Siste måned teller som hel hvis dataene går til minst den 28.
    end = last_month if last.day >= 28 else last_month - 1
    first = df["date"].min().to_period("M")
    if df["date"].min().day > 3:
        first += 1
    months = [str(p) for p in pd.period_range(first, end, freq="M")] if first <= end else []
    return months[-n:] if months else [str(last_month)]


# ---------------------------------------------------------------- forslag
def _round(x: float, step: int = 50) -> float:
    return float(round(x / step) * step)


WORK_OR_GRANT = (r"lånekass|lanekass|stipend|studielån|\bnav\b|dagpenger|sykepenger|foreldrepenger|"
                 r"arbeidsavklaring|\baap\b|uføre|pensjon|barnetrygd|bostøtte|kontantstøtte|feriepenger|"
                 r"\blønn|\blonn|honorar|skattepenger|tilbakebetaling av skatt")
# Lønn kommer ofte bare med navnet på arbeidsgiveren («Fjellsiden AS»). Jevnlige innbetalinger fra
# firma og offentlige virksomheter regnes derfor som jobb – penger fra privatpersoner gjør ikke det.
ORGANISATION = r"\b(?:as|asa|ans|da|sa|ba|nuf|ab|ltd|kommune|fylkeskommune|universitet|høgskole|sykehus|stiftelse)\b"


# Stipend og ytelser – alt annet som kommer fast, regnes som jobb
GRANTS = (r"lånekass|lanekass|stipend|studielån|\bnav\b|dagpenger|sykepenger|foreldrepenger|arbeidsavklaring|"
          r"\baap\b|uføre|pensjon|barnetrygd|bostøtte|kontantstøtte|skattepenger|tilbakebetaling av skatt")
SUMMER = {6, 7, 8}          # sommerjobb – lønna er ofte mye høyere disse månedene


def is_summer(month: str) -> bool:
    return pd.Period(month, "M").month in SUMMER


def season_note(month: str) -> str:
    if is_summer(month):
        return "Lønna er anslått ut fra sommermånedene (juni–august), når studenter ofte jobber mer."
    return ("Studentlønn er ofte mye lavere utenom sommeren, så lønna er anslått bare ut fra månedene "
            "september–mai.")


def income_sources(df: pd.DataFrame, n: int = 3, history: int = 6, month: str | None = None) -> list[dict]:
    """Faste inntekter fra jobb og stipend.

    En kilde tas med hvis den har betalt i minst halvparten av de siste `n` hele månedene (så en jobb
    du har sluttet i, ikke kommer med). Beløpet er medianen av månedene den har betalt de siste
    `history` månedene, så en lønn som varierer mye, ikke styres av én høy eller lav måned.

    Studentlønn varierer mye med årstiden: om sommeren jobber man mer. Når `month` er gitt, bygger
    beløpet for lønn bare på måneder i samme sesong (sommer = juni–august, ellers resten av året),
    så et forslag for desember ikke blir blåst opp av sommerjobben.
    """
    if df.empty:
        return []
    d = with_months(df)
    recent, longer = complete_months(d, n), complete_months(d, history)
    inc = analysis.income(d[d["month"].isin(longer)])
    # Bare det som ser ut som jobb, stipend eller støtte fra det offentlige – ikke penger fra
    # venner og familie (Vipps, overføringer fra personer)
    inc = inc[(inc["category"] == "Lønn") | inc["text"].str.contains(WORK_OR_GRANT, case=False, regex=True)
              | inc["text"].str.contains(ORGANISATION, case=False, regex=True)]
    if inc.empty:
        return []
    inc = inc.assign(key=inc["text"].map(merchant_key))
    per = inc.groupby(["key", "month"])["amount"].sum().reset_index()
    # Hvilke kilder er jobb (ikke stipend/ytelser), og hva har de betalt per måned det siste året
    grants = inc["text"].str.contains(GRANTS, case=False, regex=True)
    jobs = set(inc.loc[~grants, "key"])
    year = analysis.income(d[d["month"].isin(complete_months(d, 12))])
    year = year.assign(key=year["text"].map(merchant_key))
    per_year = year[year["key"].isin(jobs)].groupby(["key", "month"])["amount"].sum().reset_index()
    out = []
    season = is_summer(month) if month else None
    for key, g in per.groupby("key"):
        if g["month"].isin(recent).sum() < math.ceil(len(recent) / 2):
            continue                       # engangsinntekt, eller noe som har sluttet
        amounts = g["amount"]
        if season is not None and key in jobs:
            # Lønn: bruk bare måneder i samme sesong det siste året (sommer eller ikke sommer)
            year = per_year[per_year["key"] == key]
            same = year[year["month"].map(is_summer) == season]["amount"]
            if len(same):
                amounts = same
        out.append({"navn": merchant_label(key), "beløp": _round(amounts.median(), 100)})
    return sorted(out, key=lambda r: -r["beløp"])


# Kategorier der gjentatte kjøp ikke er «faste utgifter» (f.eks. Vinmonopolet hver fredag)
NOT_FIXED = {"Alkohol", "Restaurant og takeaway", "Dagligvarer", "Vipps", "Kontantuttak", "Klær og sko",
             "Elektronikk", "Reise", "Gaver", "Personlig pleie"}
_MONTH_STEP = {"månedlig": 1, "kvartalsvis": 3, "halvårlig": 6, "årlig": 12}


def fixed_costs(subs, month: str) -> list[dict]:
    """Faste trekk som ventes i måneden: husleie, abonnementer, mobil, buss … (årlige bare hvis de forfaller da)."""
    p = pd.Period(month, "M")
    start, end = p.start_time.normalize(), p.end_time.normalize()
    out = []
    for s in subs or []:
        if not s.active or s.category in NOT_FIXED:
            continue
        if s.interval in _MONTH_STEP:
            # Gå fram i hele måneder fra siste trekk, så et trekk den 1. ikke telles to ganger i en lang måned
            step, d = pd.DateOffset(months=_MONTH_STEP[s.interval]), s.last
            while d < start:
                d += step
            count = 1 if d <= end else 0
        else:                                   # ukentlig
            d, count = s.last, 0
            while d < start:
                d += pd.Timedelta(days=7)
            while d <= end:
                count, d = count + 1, d + pd.Timedelta(days=7)
        if count:
            name = s.name + ("" if s.interval in ("månedlig", "ukentlig") else f" ({s.interval})")
            out.append({"navn": name, "kategori": s.category, "beløp": _round(s.amount * count, 1)})
    return sorted(out, key=lambda r: -r["beløp"])


def usual_by_category(df: pd.DataFrame, n: int = 3) -> pd.Series:
    """Vanlig forbruk per kategori per måned (snitt av de siste hele månedene)."""
    if df.empty:
        return pd.Series(dtype=float)
    d = with_months(df)
    months = complete_months(d, n)
    s = analysis.spending(d[d["month"].isin(months)])
    if s.empty:
        return pd.Series(dtype=float)
    return s.groupby("category")["spend"].sum() / max(len(months), 1)


def suggest_rest(df: pd.DataFrame, income: float, fixed: list[dict], own: list[dict], saving: float,
                 n: int = 3) -> tuple[pd.DataFrame, float]:
    """Forslag til hvordan resten av pengene fordeles på vanlige kategorier.

    Utgangspunktet er hva du vanligvis bruker (minus det som allerede er faste trekk), med litt kutt der
    det er lett å spare. Holder ikke pengene, kuttes det mest i «ønsker» (takeaway, klær …) og minst i
    «behov» (mat, transport …). Returnerer (tabell, mangler) der mangler > 0 betyr at pengene ikke strekker til.
    """
    usual = usual_by_category(df, n)
    if "Ukategorisert" in usual:
        usual["Annet"] = usual.get("Annet", 0) + usual.pop("Ukategorisert")
    fixed_by_cat: dict[str, float] = {}
    for f in fixed:
        fixed_by_cat[f["kategori"]] = fixed_by_cat.get(f["kategori"], 0) + float(f["beløp"] or 0)

    rows = []
    for cat in EXPENSE_CATEGORIES:
        if cat == "Ukategorisert":
            continue
        base = max(float(usual.get(cat, 0)) - fixed_by_cat.get(cat, 0), 0.0)
        if base < 100:
            continue
        cut = DEFAULT_CUTS.get(cat, 0)
        rows.append({"kategori": cat, "vanligvis": base, "beløp": base * (1 - cut),
                     "hvorfor": f"{cut * 100:.0f} % mindre enn vanlig" if cut else "som vanlig"})
    rest = pd.DataFrame(rows, columns=["kategori", "vanligvis", "beløp", "hvorfor"])

    available = income - sum(float(f["beløp"] or 0) for f in fixed) - sum(float(o["beløp"] or 0) for o in own) - saving
    total = float(rest["beløp"].sum())
    missing = 0.0
    if total > available and total > 0:
        over = total - max(available, 0)
        for group, max_cut in ((~rest["kategori"].isin(NEEDS), 0.6), (rest["kategori"].isin(NEEDS), 0.3)):
            part = float(rest.loc[group, "beløp"].sum())
            if part <= 0 or over <= 0:
                continue
            cut = min(over, part * max_cut)
            rest.loc[group, "beløp"] *= 1 - cut / part
            rest.loc[group, "hvorfor"] = "kuttet så pengene holder"
            over -= cut
        missing = max(over, 0.0)
    rest["beløp"] = rest["beløp"].map(_round)
    rest["vanligvis"] = rest["vanligvis"].map(_round)
    return rest, missing


def suggest_saving(income: float, fixed_total: float) -> float:
    """10 % av inntekten, men aldri mer enn halvparten av det som er igjen etter faste utgifter."""
    return _round(max(min(income * 0.10, (income - fixed_total) * 0.5), 0), 100)


def new_plan(df: pd.DataFrame, subs, month: str) -> dict:
    inc = income_sources(df, month=month)
    fixed = fixed_costs(subs, month)
    total_in = sum(i["beløp"] for i in inc)
    saving = suggest_saving(total_in, sum(f["beløp"] for f in fixed))
    rest, missing = suggest_rest(df, total_in, fixed, [], saving)
    if missing > 0 and saving > 0:
        # Pengene strekker ikke til – da foreslår vi ikke sparing før det vanlige forbruket går opp
        saving = _round(max(saving - missing, 0), 100)
        rest, _ = suggest_rest(df, total_in, fixed, [], saving)
    return {"måned": month, "inntekter": inc, "faste": fixed, "egne": [], "sparing": saving,
            "resten": rest[["kategori", "beløp"]].to_dict("records")}


# ---------------------------------------------------------------- summer
def totals(plan: dict) -> dict:
    s = lambda rows: sum(float(r.get("beløp") or 0) for r in rows)  # noqa: E731
    t = {"inn": s(plan["inntekter"]), "faste": s(plan["faste"]), "egne": s(plan["egne"]),
         "sparing": float(plan.get("sparing") or 0), "resten": s(plan["resten"])}
    t["ut"] = t["faste"] + t["egne"] + t["resten"]
    t["ufordelt"] = t["inn"] - t["ut"] - t["sparing"]
    return t


def by_category(plan: dict) -> pd.DataFrame:
    """Planen som budsjett per kategori (category, amount, kind) – samme form som db.get_budget()."""
    rows: dict[str, list] = {}
    for kind, items in (("fast", plan["faste"]), ("variabel", plan["egne"]), ("variabel", plan["resten"])):
        for r in items:
            cat, amount = r.get("kategori"), float(r.get("beløp") or 0)
            if not cat or amount <= 0:
                continue
            cur = rows.setdefault(cat, [0.0, kind])
            cur[0] += amount
    out = [{"category": c, "amount": a, "kind": k} for c, (a, k) in rows.items()]
    if plan.get("sparing"):
        out.append({"category": "Sparing", "amount": float(plan["sparing"]), "kind": "sparing"})
    return pd.DataFrame(out, columns=["category", "amount", "kind"])


# ---------------------------------------------------------------- lagring
def get_plan(conn, month: str) -> dict | None:
    return db.get_setting(conn, f"plan:{month}")


def save_plan(conn, plan: dict) -> None:
    db.set_setting(conn, f"plan:{plan['måned']}", plan)


def delete_plan(conn, month: str) -> None:
    with db.tx(conn):
        conn.execute("DELETE FROM settings WHERE key = ?", (f"plan:{month}",))


def planned_months(conn) -> list[str]:
    return sorted(k[5:] for (k,) in conn.execute("SELECT key FROM settings WHERE key LIKE 'plan:%'"))


def follow_up(df: pd.DataFrame, plan: dict) -> pd.DataFrame:
    """Plan mot faktisk forbruk i planens måned (samme kolonner som budget.status)."""
    from .budget import status
    d = with_months(df)
    return status(d.assign(period=d["month"]), by_category(plan), plan["måned"])
