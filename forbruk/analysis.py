"""Perioder, oppsummeringer, avvik, «hva om», kontantstrøm-prognose og tullball-detektor."""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .categorize import EXPENSE_CATEGORIES, INCOME_CATEGORIES, merchant_key, merchant_label

EXPENSE_SET = set(EXPENSE_CATEGORIES)


# ---------------------------------------------------------------- perioder
def detect_payday(df: pd.DataFrame) -> int | None:
    sal = df[(df["category"] == "Lønn") & (df["amount"] > 0)]
    if sal.empty:
        return None
    biggest = sal.loc[sal.groupby(sal["date"].dt.to_period("M"))["amount"].idxmax()]
    return int(np.median(biggest["date"].dt.day))


def _salary_dates(df: pd.DataFrame) -> list[pd.Timestamp]:
    sal = df[(df["category"] == "Lønn") & (df["amount"] > 0)]
    if sal.empty:
        return []
    biggest = sal.loc[sal.groupby(sal["date"].dt.to_period("M"))["amount"].idxmax()]
    return sorted(biggest["date"].dt.normalize().tolist())


def _fixed_payday(year: int, month: int, payday: int) -> pd.Timestamp:
    d = date(year, month, min(payday, calendar.monthrange(year, month)[1]))
    while d.weekday() >= 5:            # lønn kommer fredag før hvis helg
        d -= timedelta(days=1)
    return pd.Timestamp(d)


def pay_boundaries(df: pd.DataFrame, payday: int) -> list[pd.Timestamp]:
    start = (df["date"].min() - pd.DateOffset(months=1)).replace(day=1)
    end = df["date"].max() + pd.DateOffset(months=2)
    months = pd.period_range(start, end, freq="M")
    fixed = [_fixed_payday(p.year, p.month, payday) for p in months]
    actual = _salary_dates(df)
    out = []
    for f in fixed:
        near = [a for a in actual if abs((a - f).days) <= 7]
        out.append(near[0] if near else f)
    return sorted(set(out))


def add_periods(df: pd.DataFrame, mode: str = "kalender", payday: int | None = None) -> pd.DataFrame:
    """Legger til kolonnene period (sorterbar nøkkel), period_label, period_start, period_end."""
    df = df.copy()
    if df.empty:
        for c in ("period", "period_label", "period_start", "period_end"):
            df[c] = pd.Series(dtype=object)
        return df
    if mode == "lønn":
        payday = payday or detect_payday(df) or 20
        bounds = pay_boundaries(df, payday)
        b = pd.DatetimeIndex(bounds)
        idx = b.searchsorted(df["date"].dt.normalize(), side="right") - 1
        idx = np.clip(idx, 0, len(b) - 2)
        starts = b[idx]
        ends = b[idx + 1] - pd.Timedelta(days=1)
        df["period_start"] = starts
        df["period_end"] = ends
        df["period"] = starts.strftime("%Y-%m-%d")
        df["period_label"] = [f"{s:%d.%m}–{e:%d.%m.%y}" for s, e in zip(starts, ends)]
    else:
        p = df["date"].dt.to_period("M")
        df["period_start"] = p.dt.start_time
        df["period_end"] = p.dt.end_time.dt.normalize()
        df["period"] = p.astype(str)
        df["period_label"] = [f"{_mnd(s.month)} {s.year}" for s in df["period_start"]]
    return df


_MND = ["jan", "feb", "mar", "apr", "mai", "jun", "jul", "aug", "sep", "okt", "nov", "des"]


def _mnd(m: int) -> str:
    return _MND[m - 1]


def period_table(df: pd.DataFrame) -> pd.DataFrame:
    """Én rad per periode, med start/slutt og om den er komplett."""
    if df.empty:
        return pd.DataFrame(columns=["period", "period_label", "period_start", "period_end", "complete"])
    t = (df.groupby("period", as_index=False)
           .agg(period_label=("period_label", "first"), period_start=("period_start", "first"),
                period_end=("period_end", "first"))
           .sort_values("period"))
    last_date = df["date"].max()
    first_date = df["date"].min()
    t["complete"] = (t["period_end"] <= last_date + pd.Timedelta(days=2)) & \
                    (t["period_start"] >= first_date - pd.Timedelta(days=2))
    return t.reset_index(drop=True)


def complete_periods(df: pd.DataFrame, n: int | None = None) -> list[str]:
    t = period_table(df)
    done = t[t["complete"]]["period"].tolist()
    if not done:
        done = t["period"].tolist()
    return done[-n:] if n else done


# ---------------------------------------------------------------- grunnlag
def spending(df: pd.DataFrame) -> pd.DataFrame:
    """Forbruk: utgiftskategorier, uten overføringer. Refusjoner (+) trekkes fra."""
    s = df[(~df["is_transfer"]) & (df["category"].isin(EXPENSE_SET))].copy()
    s["spend"] = -s["amount"]
    return s


def income(df: pd.DataFrame) -> pd.DataFrame:
    return df[(~df["is_transfer"]) & (df["category"].isin(INCOME_CATEGORIES)) & (df["amount"] > 0)]


def savings(df: pd.DataFrame) -> pd.DataFrame:
    """Sparing = trekk kategorisert som sparing + netto overføringer inn på egne sparekontoer."""
    direct = df[(~df["is_transfer"]) & (df["category"] == "Sparing")].copy()
    direct["saved"] = -direct["amount"]
    if "account_kind" in df.columns:
        to_savings = df[df["is_transfer"] & (df["account_kind"] == "sparekonto")].copy()
        to_savings["saved"] = to_savings["amount"]
        direct = pd.concat([direct, to_savings])
    return direct


def period_summary(df: pd.DataFrame) -> pd.DataFrame:
    t = period_table(df)
    if t.empty:
        return t
    inn = income(df).groupby("period")["amount"].sum()
    ut = spending(df).groupby("period")["spend"].sum()
    sp = savings(df).groupby("period")["saved"].sum()
    t["Inn"] = t["period"].map(inn).fillna(0)
    t["Forbruk"] = t["period"].map(ut).fillna(0)
    t["Sparing"] = t["period"].map(sp).fillna(0)
    t["Netto"] = t["Inn"] - t["Forbruk"] - t["Sparing"]
    return t


def by_category(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot: rader = kategori, kolonner = periode, verdier = forbruk."""
    s = spending(df)
    if s.empty:
        return pd.DataFrame()
    return s.pivot_table(index="category", columns="period", values="spend", aggfunc="sum", fill_value=0)


def monthly_average_by_category(df: pd.DataFrame, n_periods: int = 3) -> pd.Series:
    periods = complete_periods(df, n_periods)
    s = spending(df[df["period"].isin(periods)])
    if s.empty:
        return pd.Series(dtype=float)
    return (s.groupby("category")["spend"].sum() / max(len(periods), 1)).sort_values(ascending=False)


def average_income(df: pd.DataFrame, n_periods: int = 3) -> float:
    periods = complete_periods(df, n_periods)
    inc = income(df[df["period"].isin(periods)])
    return float(inc["amount"].sum() / max(len(periods), 1)) if periods else 0.0


def top_merchants(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    s = spending(df)
    if s.empty:
        return pd.DataFrame(columns=["Sted", "Kategori", "Antall", "Sum"])
    s = s.assign(mkey=s["text"].map(merchant_key))
    g = (s.groupby("mkey").agg(Kategori=("category", lambda x: x.mode().iat[0]),
                                Antall=("spend", "size"), Sum=("spend", "sum"))
           .sort_values("Sum", ascending=False).head(n).reset_index())
    g.insert(0, "Sted", g.pop("mkey").map(merchant_label))
    return g


# ---------------------------------------------------------------- avvik
@dataclass
class Anomaly:
    category: str
    current: float
    baseline: float
    diff: float
    pct: float


def anomalies(df: pd.DataFrame, period: str, lookback: int = 3,
              min_kr: float = 300, min_pct: float = 25) -> list[Anomaly]:
    piv = by_category(df)
    if piv.empty or period not in piv.columns:
        return []
    cols = sorted(piv.columns)
    i = cols.index(period)
    prev = cols[max(0, i - lookback):i]
    if not prev:
        return []
    base = piv[prev].mean(axis=1)
    cur = piv[period]
    out = []
    for cat in piv.index:
        b, c = float(base[cat]), float(cur[cat])
        diff = c - b
        pct = (diff / b * 100) if b > 0 else (100.0 if c > 0 else 0.0)
        if abs(diff) >= min_kr and abs(pct) >= min_pct:
            out.append(Anomaly(cat, c, b, diff, pct))
    out.sort(key=lambda a: -abs(a.diff))
    return out


# ---------------------------------------------------------------- hva om
def what_if(monthly_by_cat: pd.Series, cuts_pct: dict[str, float],
            cancelled_monthly: float = 0.0, years: int = 5, annual_rate: float = 0.0) -> dict:
    monthly = sum(float(monthly_by_cat.get(c, 0)) * p / 100 for c, p in cuts_pct.items()) + cancelled_monthly
    r = annual_rate / 100 / 12
    n = years * 12
    fv = monthly * (((1 + r) ** n - 1) / r) if r > 0 else monthly * n
    return {"per_måned": monthly, "per_år": monthly * 12, "totalt": monthly * n, "med_avkastning": fv}


# ---------------------------------------------------------------- prognose
@dataclass
class Forecast:
    period_label: str
    reference_date: pd.Timestamp
    period_end: pd.Timestamp
    days_left: int
    fixed_remaining: float
    fixed_items: list[tuple[str, pd.Timestamp, float]]
    variable_daily: float
    variable_remaining: float
    balance: float | None
    estimated_left: float | None


def forecast(df: pd.DataFrame, subs, balance: float | None) -> Forecast | None:
    if df.empty:
        return None
    ref = df["date"].max().normalize()
    cur = df[df["date"] == df["date"].max()].iloc[0]
    period_end = cur["period_end"]
    days_left = max(int((period_end - ref).days), 0)

    fixed_items = [(s.name, s.next_expected, s.amount) for s in subs
                   if s.active and ref < s.next_expected <= period_end]
    fixed_remaining = float(sum(a for _, _, a in fixed_items))

    # Variabelt forbruk per dag = snitt fra siste komplette perioder, uten faste trekk
    periods = complete_periods(df, 3)
    hist = spending(df[df["period"].isin(periods)])
    sub_keys = {s.key.split("|")[0] for s in subs}
    if not hist.empty:
        hist = hist[~hist["text"].map(merchant_key).isin(sub_keys)]
        hist = hist[~hist["category"].isin({"Bolig", "Lån"})]
    t = period_table(df)
    t = t[t["period"].isin(periods)]
    n_days = int(((t["period_end"] - t["period_start"]).dt.days + 1).sum()) if not t.empty else 0
    variable_daily = float(hist["spend"].sum() / n_days) if n_days and not hist.empty else 0.0
    variable_remaining = variable_daily * days_left
    left = None if balance is None else balance - fixed_remaining - variable_remaining
    return Forecast(cur["period_label"], ref, period_end, days_left, fixed_remaining, fixed_items,
                    variable_daily, variable_remaining, balance, left)


# ---------------------------------------------------------------- tullball-detektor
@dataclass
class Finding:
    title: str
    detail: str
    monthly: float
    saving_monthly: float
    recommendation: str
    severity: int = 1          # 1 = info, 2 = bør se på, 3 = viktig
    examples: list[str] = field(default_factory=list)

    @property
    def saving_yearly(self) -> float:
        return self.saving_monthly * 12


def _kr(x: float) -> str:
    return f"{x:,.0f} kr".replace(",", " ")


def findings(df: pd.DataFrame, subs=None, sifo_diff: pd.DataFrame | None = None,
             n_periods: int = 3) -> list[Finding]:
    periods = complete_periods(df, n_periods)
    if not periods:
        return []
    n = len(periods)
    recent = df[df["period"].isin(periods)]
    s = spending(recent)
    out: list[Finding] = []
    if s.empty:
        return out
    s = s.assign(mkey=s["text"].map(merchant_key))

    # Takeaway og restaurant
    ta = s[s["category"] == "Restaurant og takeaway"]
    if not ta.empty:
        monthly = ta["spend"].sum() / n
        count = len(ta[ta["spend"] > 0]) / n
        delivery = ta[ta["text"].str.lower().str.contains("foodora|wolt|just eat|justeat", regex=True)]
        d_month = delivery["spend"].sum() / n
        detail = f"Snitt {_kr(monthly)} per måned fordelt på {count:.0f} kjøp ({_kr(monthly * 12)} i året)."
        if d_month > 0:
            detail += f" Av dette er {_kr(d_month)} matlevering, der du også betaler leveringsgebyr."
        out.append(Finding(
            "Restaurant og takeaway", detail, monthly, monthly * 0.5,
            "Halver antall bestillinger: lag middag på søndag til flere dager, og sett deg en fast "
            "takeaway-dag i uka i stedet for spontane bestillinger.",
            3 if monthly >= 2000 else 2,
            [f"{merchant_label(k)}: {_kr(v / n)}/mnd" for k, v in
             ta.groupby("mkey")["spend"].sum().sort_values(ascending=False).head(4).items()]))

    # Mange små kjøp
    small = s[(s["spend"] > 0) & (s["spend"] < 100) & (~s["category"].isin({"Transport"}))]
    if len(small) >= 10 * n:
        monthly = small["spend"].sum() / n
        out.append(Finding(
            "Mange små kjøp", f"{len(small) / n:.0f} kjøp under 100 kr per måned, til sammen "
            f"{_kr(monthly)} per måned ({_kr(monthly * 12)} i året).", monthly, monthly * 0.3,
            "Små kjøp merkes ikke enkeltvis. Ta med kaffe/matpakke, og handle dagligvarer "
            "én–to ganger i uka i stedet for innom butikken hver dag.", 2,
            [f"{merchant_label(k)}: {c} kjøp" for k, c in
             small["mkey"].value_counts().head(4).items()]))

    # Gebyrer, renter, purringer
    fees = s[s["category"] == "Gebyrer og renter"]
    if not fees.empty and fees["spend"].sum() > 0:
        monthly = fees["spend"].sum() / n
        bad = fees[fees["text"].str.lower().str.contains("purr|inkasso|forsinkelse|lindorff|intrum|kredinor|sergel|lowell", regex=True)]
        detail = f"{_kr(monthly)} per måned i gebyrer og renter."
        sev = 2
        if not bad.empty:
            detail += f" Inkludert purringer/inkasso: {_kr(bad['spend'].sum() / n)} per måned."
            sev = 3
        out.append(Finding(
            "Gebyrer, renter og purringer", detail, monthly, (bad["spend"].sum() / n) if not bad.empty else monthly * 0.3,
            "Sett opp AvtaleGiro/eFaktura for faste regninger, og nedbetal dyr kredittgjeld "
            "(kredittkort, forbrukslån) først.", sev,
            fees["text"].head(4).tolist()))

    # Abonnementer
    if subs:
        active = [x for x in subs if x.active and x.category == "Abonnementer"]
        total = sum(x.monthly for x in active)
        if active:
            from .subscriptions import overlaps
            ov = overlaps(subs)
            detail = f"{len(active)} aktive abonnementer, til sammen {_kr(total)} per måned ({_kr(total * 12)} i året)."
            saving = 0.0
            if ov:
                parts = []
                for g, lst in ov.items():
                    parts.append(f"{g}: {', '.join(x.name for x in lst)}")
                    saving += sum(sorted(x.monthly for x in lst)[:-1])
                detail += " Overlapp: " + "; ".join(parts) + "."
            out.append(Finding(
                "Abonnementer", detail, total, saving or total * 0.2,
                "Gå gjennom «Si opp?»-listen. Rullér strømmetjenester: ha én om gangen og bytt når du "
                "har sett det du vil.", 3 if ov else 2,
                [f"{x.name}: {_kr(x.monthly)}/mnd" for x in active[:5]]))

    # Kategorier som stiger
    piv = by_category(df)
    cols = sorted(c for c in piv.columns if c in complete_periods(df)) if not piv.empty else []
    if len(cols) >= 6:
        last3 = piv[cols[-3:]].mean(axis=1)
        prev3 = piv[cols[-6:-3]].mean(axis=1)
        for cat in piv.index:
            if cat in {"Bolig", "Lån", "Ukategorisert"}:
                continue
            a, b = float(last3[cat]), float(prev3[cat])
            if b > 300 and a > b * 1.3 and a - b > 400:
                out.append(Finding(
                    f"{cat} øker", f"Snitt siste 3 perioder: {_kr(a)}, mot {_kr(b)} de 3 før "
                    f"(+{(a / b - 1) * 100:.0f} %).", a, a - b,
                    "Se gjennom transaksjonene i kategorien. Er økningen planlagt, eller har det "
                    "sneket seg inn nye vaner?", 2))

    # Over SIFO
    if sifo_diff is not None and not sifo_diff.empty:
        over = sifo_diff[(sifo_diff["Differanse"] > 300) & (sifo_diff["SIFO"] > 0)]
        for r in over.sort_values("Differanse", ascending=False).head(4).itertuples():
            out.append(Finding(
                f"{r.Kategori} over SIFO-nivå",
                f"Du bruker {_kr(r.Mitt_snitt)} per måned, mot SIFO-nivå {_kr(r.SIFO)} "
                f"(+{r.Prosent:.0f} %).", r.Mitt_snitt, r.Differanse * 0.5,
                "SIFO-nivået er et nøkternt, men vanlig forbruk. Prøv å ta igjen halve differansen.",
                2))

    # Ukategorisert
    unc = s[s["category"] == "Ukategorisert"]
    if not unc.empty and unc["spend"].sum() / n > 500:
        out.append(Finding(
            "Mye ukategorisert", f"{_kr(unc['spend'].sum() / n)} per måned er ikke kategorisert.",
            unc["spend"].sum() / n, 0,
            "Kategoriser disse under «Kategorier og regler», så blir analysen mer presis.", 1))

    out.sort(key=lambda f: (-f.severity, -f.saving_monthly))
    return out
