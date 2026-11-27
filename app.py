"""Forbruksapp – enkel oversikt over pengene dine.

Start:  streamlit run app.py   (eller ./start.sh)
"""
from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from forbruk import (ai_categorize, analysis, budget, categorize, claude_connect, config, db, importer,
                     report, sifo, subscriptions)
from forbruk.categorize import EXPENSE_CATEGORIES

st.set_page_config(page_title="Pengene mine", page_icon="💜", layout="wide")
config.ensure_dirs()
PROJECT = Path(__file__).resolve().parent

PURPLE = "#6d5dfc"
EMOJI = {
    "Dagligvarer": "🛒", "Restaurant og takeaway": "🍔", "Transport": "🚇", "Bil": "🚗",
    "Abonnementer": "📺", "Bolig": "🏠", "Lån": "🏦", "Klær og sko": "👟", "Personlig pleie": "💄",
    "Helse": "💊", "Elektronikk": "📱", "Alkohol": "🍷", "Fritid": "🎟️", "Reise": "✈️",
    "Husholdning": "🧺", "Barn": "🧸", "Gaver": "🎁", "Vipps": "📲", "Kontantuttak": "💵",
    "Gebyrer og renter": "⚠️", "Annet": "📦", "Ukategorisert": "❓", "Lønn": "💼",
    "Inntekt annet": "💰", "Sparing": "🐷", "Overføring": "🔁",
}
# Kategorier en vanlig bruker velger mellom (uten de tekniske)
PICK_CATEGORIES = [c for c in EXPENSE_CATEGORIES if c != "Ukategorisert"] + ["Sparing", "Lønn", "Inntekt annet", "Overføring"]


# ======================================================================== stil
st.markdown(f"""
<style>
  html, body, .stApp, button, input, textarea, select {{
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Inter, system-ui, sans-serif;
  }}
  .block-container {{ max-width: 1080px; padding-top: 1.2rem; padding-bottom: 4rem; }}
  header[data-testid="stHeader"] {{ background: transparent; }}
  h1 {{ font-weight: 750; letter-spacing: -0.02em; }}
  h2, h3 {{ font-weight: 700; letter-spacing: -0.01em; }}
  .hero {{
    background: linear-gradient(135deg, #6d5dfc 0%, #9b7bff 60%, #c38bff 100%);
    color: white; border-radius: 24px; padding: 28px 30px; margin: 6px 0 18px 0;
    box-shadow: 0 10px 30px rgba(109, 93, 252, .25);
  }}
  .hero .label {{ font-size: 15px; opacity: .9; }}
  .hero .big {{ font-size: 46px; font-weight: 750; letter-spacing: -0.02em; line-height: 1.1; margin: 4px 0 14px; }}
  .hero .row {{ display: flex; gap: 28px; flex-wrap: wrap; font-size: 15px; }}
  .hero .row b {{ font-size: 19px; display: block; }}
  .hero .pbar {{ height: 8px; background: rgba(255,255,255,.3); border-radius: 99px; overflow: hidden; margin-top: 16px; }}
  .hero .pbar > div {{ height: 100%; background: white; border-radius: 99px; }}
  .card {{ background: white; border: 1px solid #ececf4; border-radius: 20px; padding: 20px 22px; margin-bottom: 14px; }}
  .card h4 {{ margin: 0 0 12px 0; font-size: 17px; }}
  .catrow {{ display: grid; grid-template-columns: 40px 1fr auto; gap: 12px; align-items: center; margin: 12px 0; }}
  .ic {{ width: 40px; height: 40px; border-radius: 13px; background: #f1efff; display: flex; align-items: center; justify-content: center; font-size: 20px; flex-shrink: 0; }}
  .catrow .nm {{ font-weight: 600; font-size: 15px; }}
  .catrow .sub {{ color: #8a8aa3; font-size: 13px; }}
  .catrow .amt {{ font-weight: 650; font-size: 15px; text-align: right; }}
  .bar {{ height: 7px; background: #f0f0f6; border-radius: 99px; overflow: hidden; margin-top: 6px; }}
  .bar > div {{ height: 100%; border-radius: 99px; }}
  .tip {{ display: flex; gap: 14px; padding: 14px 0; border-bottom: 1px solid #f1f1f6; }}
  .tip:last-child {{ border-bottom: none; }}
  .tip .i {{ font-size: 22px; }}
  .tip .t {{ font-weight: 650; }}
  .tip .d {{ color: #5d5d75; font-size: 14px; margin-top: 2px; }}
  .tip .s {{ color: #16a34a; font-weight: 650; font-size: 14px; margin-top: 4px; }}
  .muted {{ color: #8a8aa3; font-size: 14px; }}
  .stat {{ background: white; border: 1px solid #ececf4; border-radius: 18px; padding: 16px 18px; }}
  .stat .l {{ color: #8a8aa3; font-size: 13px; }}
  .stat .v {{ font-size: 24px; font-weight: 700; margin-top: 2px; }}
  .subrow {{ display: flex; gap: 12px; align-items: center; }}
  .stButton > button, .stDownloadButton > button {{ border-radius: 12px; font-weight: 600; }}
  [data-testid="stFileUploaderDropzone"] {{ border-radius: 20px; padding: 34px; background: white; }}
</style>
""", unsafe_allow_html=True)


# ======================================================================== hjelpere
@st.cache_resource
def get_conn():
    return db.connect()


conn = get_conn()


def kr(x) -> str:
    if x is None or pd.isna(x):
        return "–"
    return f"{x:,.0f} kr".replace(",", " ").replace("-", "−")


def esc(s) -> str:
    return html.escape(str(s))


def setting(key, default=None):
    return db.get_setting(conn, key, default)


def first_name() -> str:
    name = (setting("user_name", "") or "").strip()
    return name.split()[0] if name else ""


@st.cache_data(show_spinner=False)
def _load(version: int, mode: str, payday: int) -> pd.DataFrame:
    df = db.load_transactions(conn)
    if df.empty:
        return df
    return analysis.add_periods(df, mode, payday or None)


def data_version() -> int:
    row = conn.execute("SELECT COUNT(*), COALESCE(SUM(LENGTH(category)), 0), COALESCE(SUM(is_transfer), 0), "
                       "COALESCE(SUM(id), 0) FROM transactions").fetchone()
    return hash(tuple(row))


def load_df() -> pd.DataFrame:
    return _load(data_version(), setting("period_mode", "kalender"), int(setting("payday", 0) or 0))


def refresh():
    categorize.refresh(conn)
    st.cache_data.clear()


def go_to(page_key: str):
    st.switch_page(PAGES[page_key])


def month_picker(df: pd.DataFrame, key: str) -> str:
    """Valg av måned som «piller». Husker valget mellom sidene."""
    pt = analysis.period_table(df)
    options = pt["period"].tolist()[-6:][::-1]
    labels = dict(zip(pt["period"], pt["period_label"]))
    current = st.session_state.get("sel_period")
    default = current if current in options else options[0]
    sel = st.segmented_control("Måned", options, default=default, format_func=lambda p: labels[p].capitalize(),
                               key=key, label_visibility="collapsed")
    sel = sel or default
    st.session_state["sel_period"] = sel
    return sel


def period_info(df, period):
    pt = analysis.period_table(df).set_index("period")
    return pt.loc[period, "period_label"], bool(pt.loc[period, "complete"])


def category_rows(items, max_value, color=PURPLE, sub=None) -> str:
    rows = []
    for cat, value in items:
        pct = max(2, min(100, value / max_value * 100)) if max_value else 0
        s = f'<div class="sub">{esc(sub(cat))}</div>' if sub else ""
        rows.append(f'<div class="catrow"><div class="ic">{EMOJI.get(cat, "📦")}</div>'
                    f'<div><div class="nm">{esc(cat)}</div>{s}<div class="bar"><div style="width:{pct:.0f}%;background:{color}"></div></div></div>'
                    f'<div class="amt">{kr(value)}</div></div>')
    return "".join(rows)


def stat(label, value) -> str:
    return f'<div class="stat"><div class="l">{esc(label)}</div><div class="v">{esc(value)}</div></div>'


def clean_fig(fig, height=260):
    fig.update_layout(height=height, margin=dict(t=10, b=10, l=10, r=10), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", showlegend=False, font=dict(size=13, color="#5d5d75"))
    fig.update_xaxes(showgrid=False, title=None)
    fig.update_yaxes(showgrid=True, gridcolor="#f0f0f6", title=None, zeroline=False, showticklabels=False)
    return fig


def short(text: str, n: int = 140) -> str:
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " …"


def load_demo():
    demo = PROJECT / "eksempeldata"
    import runpy
    runpy.run_path(str(demo / "lag_eksempeldata.py"), run_name="__main__")
    if not setting("user_name"):
        db.set_setting(conn, "user_name", "Emma Hansen")
    files = [("dnb_brukskonto_mai-aug.csv", "Brukskonto", "DNB", "1203.45.67890"),
             ("dnb_brukskonto_jul-nov.csv", "Brukskonto", "DNB", "1203.45.67890"),
             ("sbanken_sparekonto.xlsx", "Sparekonto", "Sbanken", "1203.98.76543")]
    for f, acc, bank, num in files:
        r = importer.parse_file((demo / f).read_bytes(), f)
        aid = db.get_or_create_account(conn, acc, bank, num)
        db.insert_transactions(conn, r.df, aid, f)
    if not setting("household"):
        db.set_setting(conn, "household", {"medlemmer": [{"alder": 20, "kjønn": "kvinne"}], "bil": False})
    refresh()


def save_name(name: str):
    clean = " ".join(name.split())
    if clean != (setting("user_name", "") or ""):
        db.set_setting(conn, "user_name", clean)
        refresh()


# ======================================================================== hjem
def page_home():
    df = load_df()
    if df.empty:
        welcome()
        return
    name = first_name()
    st.title(f"Hei, {name} 👋" if name else "Hei 👋")
    period = month_picker(df, "home_month")
    label, complete = period_info(df, period)
    summ = analysis.period_summary(df).set_index("period")
    cur = summ.loc[period]
    p = df[df["period"] == period]
    b = db.get_budget(conn)

    left = cur["Inn"] - cur["Forbruk"] - cur["Sparing"]
    budget_html = ""
    if not b.empty:
        total_b = b[b["kind"] != "sparing"]["amount"].sum()
        pct = cur["Forbruk"] / total_b * 100 if total_b else 0
        budget_html = (f'<div class="pbar"><div style="width:{min(pct, 100):.0f}%"></div></div>'
                       f'<div style="margin-top:8px;font-size:14px;opacity:.95">{pct:.0f} % av budsjettet på {kr(total_b)}</div>')
    st.markdown(f'<div class="hero"><div class="label">Brukt {"hittil " if not complete else ""}i {esc(label)}</div>'
                f'<div class="big">{kr(cur["Forbruk"])}</div>'
                f'<div class="row"><div>Fått inn<b>{kr(cur["Inn"])}</b></div><div>Spart<b>{kr(cur["Sparing"])}</b></div>'
                f'<div>{"Igjen" if left >= 0 else "Brukt mer enn du fikk inn"}<b>{kr(abs(left))}</b></div></div>'
                f'{budget_html}</div>', unsafe_allow_html=True)

    col1, col2 = st.columns([1.15, 1], gap="medium")
    with col1:
        piv = analysis.by_category(df)
        if not piv.empty and period in piv.columns:
            s = piv[period][piv[period] > 0].sort_values(ascending=False)
            cols = sorted(piv.columns)
            prev = cols[cols.index(period) - 1] if cols.index(period) > 0 else None

            def sub(cat):
                if not prev:
                    return ""
                d = s[cat] - piv.loc[cat, prev]
                if abs(d) < 50:
                    return "Omtrent som måneden før"
                return f"{kr(abs(d))} {'mer' if d > 0 else 'mindre'} enn måneden før"

            st.markdown(f'<div class="card"><h4>Hvor gikk pengene?</h4>'
                        f'{category_rows(list(s.head(6).items()), s.max(), sub=sub)}</div>', unsafe_allow_html=True)
            if st.button("Se alle kjøp →", key="see_all"):
                go_to("money")

    with col2:
        subs = subscriptions.find_subscriptions(df)
        fs = analysis.findings(df, subs, None)[:3]
        if fs:
            tips = "".join(
                f'<div class="tip"><div class="i">{"🔥" if f.severity == 3 else "💡"}</div><div>'
                f'<div class="t">{esc(f.title)}</div><div class="d">{esc(short(f.detail))}</div>'
                + (f'<div class="s">Du kan spare ca. {kr(f.saving_monthly)} i måneden</div>' if f.saving_monthly >= 50 else "")
                + '</div></div>' for f in fs)
            st.markdown(f'<div class="card"><h4>Tips til deg</h4>{tips}</div>', unsafe_allow_html=True)
            if st.button("Flere tips →", key="more_tips"):
                go_to("insight")
        active = [x for x in subs if x.active and x.category == "Abonnementer"]
        if active:
            tot = sum(x.monthly for x in active)
            st.markdown(f'<div class="card"><h4>📺 Abonnementer</h4>'
                        f'<div style="font-size:26px;font-weight:700">{kr(tot)} <span class="muted">i måneden</span></div>'
                        f'<div class="muted">{len(active)} abonnementer · {kr(tot * 12)} i året</div></div>',
                        unsafe_allow_html=True)
            if st.button("Gå gjennom abonnementene →", key="to_subs"):
                go_to("subs")

    unc = p[p["category"] == "Ukategorisert"]
    if len(unc):
        with st.container(border=True):
            c1, c2 = st.columns([3, 1], vertical_alignment="center")
            c1.markdown(f"**❓ {len(unc)} kjøp mangler kategori.** Hjelp appen å lære – det tar ett minutt.")
            if c2.button("Fiks nå", type="primary", width="stretch"):
                go_to("money")

    hist = summ.reset_index()
    hist = hist[hist["period_start"] >= df["date"].min() - pd.Timedelta(days=2)].tail(6)
    if len(hist) > 1:
        st.markdown("#### Måned for måned")
        colors = [PURPLE if x == period else "#d9d4ff" for x in hist["period"]]
        fig = go.Figure(go.Bar(x=hist["period_label"].str.capitalize(), y=hist["Forbruk"], marker_color=colors,
                               text=[kr(v) for v in hist["Forbruk"]], textposition="outside", cliponaxis=False,
                               hovertemplate="%{x}: %{y:,.0f} kr<extra></extra>"))
        st.plotly_chart(clean_fig(fig, 260), width="stretch", config={"displayModeBar": False})


def welcome():
    st.markdown('<div class="hero"><div class="big" style="font-size:38px">Få kontroll på pengene dine 💜</div>'
                '<div style="font-size:17px;opacity:.95">Last opp kontoutskriften fra nettbanken, så viser appen hva '
                'pengene går til, hvilke abonnementer du betaler for, og hvor du lett kan spare. '
                'Alt blir på din egen maskin.</div></div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("#### 1. Hva heter du?")
        st.caption("Skriv fullt navn slik det står i banken. Da skjønner appen at «Overføring fra Emma Hansen» "
                   "er deg som flytter penger mellom egne kontoer – ikke inntekt eller forbruk.")
        name = st.text_input("Fullt navn", value=setting("user_name", ""), placeholder="f.eks. Emma Hansen",
                             label_visibility="collapsed")
        st.markdown("#### 2. Last opp kontoutskriften")
        st.caption("Last ned transaksjonene som CSV eller Excel fra nettbanken – gjerne de siste 3–6 månedene.")
        c1, c2 = st.columns(2)
        if c1.button("Last opp fil", type="primary", width="stretch"):
            if name.strip():
                save_name(name)
            go_to("upload")
        if c2.button("Prøv med eksempeldata", width="stretch"):
            if name.strip():
                save_name(name)
            load_demo()
            st.rerun()


# ======================================================================== pengene mine
def page_money():
    df = load_df()
    if df.empty:
        welcome()
        return
    st.title("Pengene mine")
    teach_uncategorized(df)
    period = month_picker(df, "money_month")
    label, _ = period_info(df, period)
    p = df[df["period"] == period]
    sp = analysis.spending(p)
    by = sp.groupby("category")["spend"].sum()
    by = by[by > 0].sort_values(ascending=False)

    if not by.empty:
        c1, c2 = st.columns([1, 1.2], gap="medium")
        with c1:
            fig = px.pie(values=by.values, names=by.index, hole=0.64,
                         color_discrete_sequence=["#6d5dfc", "#9b7bff", "#c3b5ff", "#ff9bb3", "#ffc56d", "#7dd3c0",
                                                  "#8ec5ff", "#d4d4e8", "#b3e5a1", "#f4a6ff"])
            fig.update_traces(textinfo="none", hovertemplate="%{label}: %{value:,.0f} kr<extra></extra>", sort=False)
            fig.add_annotation(text=f"<b>{kr(by.sum())}</b><br><span style='font-size:13px'>brukt</span>",
                               showarrow=False, font=dict(size=22, color="#1d1b3a"))
            st.plotly_chart(clean_fig(fig, 320), width="stretch", config={"displayModeBar": False})
        with c2:
            n = sp.groupby("category").size()
            st.markdown(f'<div class="card"><h4>Kategorier i {esc(label)}</h4>'
                        f'{category_rows(list(by.items()), by.max(), sub=lambda c: f"{n[c]} kjøp")}</div>',
                        unsafe_allow_html=True)

    st.markdown("#### Alle kjøp og innbetalinger")
    c1, c2, c3 = st.columns([2, 1.4, 1], vertical_alignment="center")
    q = c1.text_input("Søk", placeholder="🔎  Søk, f.eks. foodora", label_visibility="collapsed")
    cats = ["Alle kategorier"] + sorted(p["category"].unique())
    cat = c2.selectbox("Kategori", cats, label_visibility="collapsed")
    show_all = c3.toggle("Alle måneder", value=False)
    v = df if show_all else p
    if q:
        v = v[v["text"].str.contains(q, case=False, regex=False)]
    if cat != "Alle kategorier":
        v = v[v["category"] == cat]
    v = v.head(500)
    edit = v[["id", "date", "text", "amount", "category"]].copy()
    edit["date"] = edit["date"].dt.date
    options = PICK_CATEGORIES + ["Ukategorisert"]
    edit["category"] = edit["category"].where(edit["category"].isin(options), "Annet")
    edited = st.data_editor(
        edit, hide_index=True, width="stretch", height=min(460, 38 + 35 * max(len(edit), 1)),
        key="tx_editor", disabled=["id", "date", "text", "amount"],
        column_config={
            "id": None,
            "date": st.column_config.DateColumn("Dato", format="DD.MM", width="small"),
            "text": st.column_config.TextColumn("Hva", width="large"),
            "amount": st.column_config.NumberColumn("Beløp", format="%.0f kr", width="small"),
            "category": st.column_config.SelectboxColumn("Kategori ✏️", options=options, required=True, width="medium"),
        })
    changed = edited[edited["category"] != edit["category"]]
    if not changed.empty:
        for r in changed.itertuples():
            categorize.set_manual_category(conn, int(r.id), r.category)
        st.cache_data.clear()
        st.session_state.pop("tx_editor", None)
        st.toast(f"Lagret {len(changed)} endring{'er' if len(changed) > 1 else ''} ✅")
        st.rerun()
    st.caption("Trykk på en kategori for å endre den. Endringen lagres med en gang.")


def teach_uncategorized(df):
    """Én butikk om gangen: «Hva er dette?» → lagrer en regel som også gjelder fremover."""
    unc = df[df["category"] == "Ukategorisert"]
    if unc.empty:
        return
    unc = unc.assign(key=unc["text"].map(categorize.merchant_key))
    skipped = st.session_state.setdefault("skipped", set())
    groups = (unc[~unc["key"].isin(skipped)].groupby("key")
              .agg(n=("id", "size"), total=("amount", "sum"), ex=("text", "first")).sort_values("total"))
    if groups.empty:
        return
    key, g = groups.index[0], groups.iloc[0]
    with st.container(border=True):
        st.markdown(f"**❓ Hjelp appen å lære** · {len(groups)} butikk{'er' if len(groups) > 1 else ''} mangler kategori")
        st.markdown(f"Hva er **{esc(categorize.merchant_label(key))}**? "
                    f"<span class='muted'>({g.n} kjøp, {kr(-g.total)} · «{esc(g.ex)}»)</span>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="bottom")
        cat = c1.selectbox("Kategori", PICK_CATEGORIES, index=None, placeholder="Velg kategori …",
                           format_func=lambda c: f"{EMOJI.get(c, '')} {c}", key=f"teach_{key}",
                           label_visibility="collapsed")
        if c2.button("Lagre", type="primary", width="stretch", disabled=cat is None):
            categorize.add_rule(conn, key, cat)
            refresh()
            st.toast(f"Supert! «{categorize.merchant_label(key)}» er nå {cat} – også neste gang.")
            st.rerun()
        if c3.button("Hopp over", width="stretch"):
            skipped.add(key)
            st.rerun()
        if setting("ai_enabled", False):
            backs = ai_categorize.backends()
            if backs:
                with st.expander("🤖 Eller la Claude foreslå for alle"):
                    ai_suggestions(backs, key="ai_money")
            elif claude_connect.is_connected():
                st.caption("🤖 Tips: Åpne Claude-appen og skriv «Hjelp meg å kategorisere utgiftene mine i Pengene mine».")
        else:
            st.caption("Mange ukjente? Slå på AI-hjelp under Innstillinger, så kan Claude foreslå for deg.")


# ======================================================================== abonnementer
def page_subs():
    df = load_df()
    if df.empty:
        welcome()
        return
    st.title("Abonnementer")
    subs = subscriptions.find_subscriptions(df)
    if not subs:
        st.info("Fant ingen faste trekk ennå. Last opp minst to–tre måneder, så finner appen dem.")
        return
    statuses = db.get_subscription_statuses(conn)
    active = [s for s in subs if s.active]
    abos = [s for s in active if s.category == "Abonnementer"]
    other = [s for s in active if s.category != "Abonnementer"]
    stopped = [s for s in subs if not s.active]
    tot = sum(s.monthly for s in abos)
    cancel = [s for s in active if statuses.get(s.key) == "Si opp"]
    extra = (f'<div style="margin-top:14px;font-size:16px;background:rgba(255,255,255,.18);padding:10px 14px;'
             f'border-radius:14px">🎉 Sier du opp de {len(cancel)} du har markert, sparer du '
             f'<b>{kr(sum(s.yearly for s in cancel))} i året</b></div>' if cancel else "")
    st.markdown(f'<div class="hero"><div class="label">Du betaler for abonnementer</div>'
                f'<div class="big">{kr(tot)} <span style="font-size:20px;font-weight:500">i måneden</span></div>'
                f'<div class="row"><div>Per år<b>{kr(tot * 12)}</b></div><div>Antall<b>{len(abos)}</b></div></div>'
                f'{extra}</div>', unsafe_allow_html=True)

    for g, lst in subscriptions.overlaps(subs).items():
        st.warning(f"**Du har flere av samme type ({g.lower()}):** {', '.join(s.name for s in lst)}. "
                   f"Trenger du alle samtidig? Bytt heller på å ha én om gangen.", icon="👯")
    for s in active:
        if s.price_change and s.price_change > 0:
            st.error(f"**{s.name} har blitt dyrere:** +{kr(s.price_change)} per trekk (nå {kr(s.amount)}).", icon="📈")

    st.markdown("#### Trenger du alle?")
    st.caption("Marker det du vil si opp, så regner appen ut hva du sparer.")
    for s in abos:
        sub_row(s, statuses)
    if other:
        st.markdown("#### Andre faste utgifter")
        st.caption("Husleie, mobil, buss og lignende som trekkes hver måned.")
        for s in other:
            sub_row(s, statuses)
    if stopped:
        with st.expander(f"Har sluttet å trekke ({len(stopped)})"):
            st.caption("Har du sagt opp disse? Da ser du her at oppsigelsen gikk gjennom ✅")
            for s in stopped:
                st.markdown(f"**{esc(s.name)}** · {kr(s.amount)} · sist trukket {s.last:%d.%m.%Y}")


def sub_row(s, statuses):
    with st.container(border=True):
        c1, c2 = st.columns([2.2, 1.4], vertical_alignment="center")
        nxt = f" · neste trekk {s.next_expected:%d.%m}" if s.active else ""
        interval = "" if s.interval == "månedlig" else f" ({kr(s.amount)} {s.interval})"
        c1.markdown(f"<div class='subrow'><div class='ic'>{EMOJI.get(s.category, '📦')}</div><div>"
                    f"<div style='font-weight:650'>{esc(s.name)}</div>"
                    f"<div class='muted'>{kr(s.monthly)} i måneden{esc(interval)}{nxt}</div></div></div>",
                    unsafe_allow_html=True)
        cur = statuses.get(s.key, "Usikker")
        cur = "Usikker" if cur == "Vurder" else cur
        val = c2.segmented_control("Status", ["Beholde", "Usikker", "Si opp"], default=cur, key=f"s_{s.key}",
                                   label_visibility="collapsed")
        if val and val != cur:
            db.set_subscription_status(conn, s.key, val)
            st.rerun()


# ======================================================================== budsjett
def page_budget():
    df = load_df()
    if df.empty:
        welcome()
        return
    st.title("Budsjett")
    b = db.get_budget(conn)
    subs = subscriptions.find_subscriptions(df)
    cmp, _ = sifo_cmp(df)
    suggestion, info = budget.suggest(df, cmp, setting("sifo_mapping", sifo.DEFAULT_MAPPING), subs)

    if b.empty:
        st.markdown('<div class="hero"><div class="big" style="font-size:34px">Lag ditt første budsjett ✨</div>'
                    '<div style="font-size:16px;opacity:.95">Appen ser på hva du vanligvis bruker, kutter litt der '
                    'det er lett å spare, og setter av penger til sparing. Du kan endre alt etterpå.</div></div>',
                    unsafe_allow_html=True)
        c = st.columns(3)
        c[0].markdown(stat("Du får vanligvis inn", kr(info["inntekt"])), unsafe_allow_html=True)
        c[1].markdown(stat("Forslag til forbruk", kr(info["sum_utgifter"])), unsafe_allow_html=True)
        c[2].markdown(stat("Forslag til sparing", kr(info["sparing"])), unsafe_allow_html=True)
        st.write("")
        if st.button("Lag budsjett for meg", type="primary"):
            db.save_budget(conn, suggestion[["category", "amount", "kind"]])
            st.rerun()
        return

    period = month_picker(df, "budget_month")
    label, complete = period_info(df, period)
    stt = budget.status(df, b, period)
    spend = stt[stt["Type"] != "sparing"]
    total_b, total_used = spend["Budsjett"].sum(), spend["Brukt"].sum()
    left = total_b - total_used
    pct = total_used / total_b * 100 if total_b else 0
    st.markdown(f'<div class="hero"><div class="label">{"Igjen å bruke" if left >= 0 else "Over budsjettet"} i {esc(label)}</div>'
                f'<div class="big">{kr(abs(left))}</div>'
                f'<div class="row"><div>Budsjett<b>{kr(total_b)}</b></div><div>Brukt{" hittil" if not complete else ""}<b>{kr(total_used)}</b></div></div>'
                f'<div class="pbar"><div style="width:{min(pct, 100):.0f}%"></div></div></div>', unsafe_allow_html=True)

    rows = []
    for r in spend.sort_values("Brukt", ascending=False).itertuples():
        used, bud = r.Brukt, r.Budsjett
        ratio = used / bud if bud else 1.5
        color = "#22c55e" if ratio < .8 else "#f59e0b" if ratio <= 1 else "#ef4444"
        if bud:
            sub = f"{kr(used)} av {kr(bud)}" + (f" · {kr(used - bud)} over" if used > bud else "")
            amt = f"{kr(bud - used)} igjen" if used <= bud else ""
        else:
            sub, amt = "Ikke med i budsjettet", kr(used)
        rows.append(f'<div class="catrow"><div class="ic">{EMOJI.get(r.Kategori, "📦")}</div>'
                    f'<div><div class="nm">{esc(r.Kategori)}</div><div class="sub">{esc(sub)}</div>'
                    f'<div class="bar"><div style="width:{max(min(100, ratio * 100), 2):.0f}%;background:{color}"></div></div></div>'
                    f'<div class="amt">{amt}</div></div>')
    c1, c2 = st.columns([1.5, 1], gap="medium")
    c1.markdown(f'<div class="card"><h4>Per kategori</h4>{"".join(rows)}</div>', unsafe_allow_html=True)
    with c2:
        sav = stt[stt["Type"] == "sparing"]
        if not sav.empty:
            sv = sav.iloc[0]
            ratio = sv["Brukt"] / sv["Budsjett"] if sv["Budsjett"] else 0
            st.markdown(f'<div class="card"><h4>🐷 Sparing</h4><div style="font-size:24px;font-weight:700">{kr(sv["Brukt"])}</div>'
                        f'<div class="muted">av {kr(sv["Budsjett"])} som er målet</div>'
                        f'<div class="bar" style="height:10px"><div style="width:{min(ratio * 100, 100):.0f}%;background:#22c55e"></div></div></div>',
                        unsafe_allow_html=True)
        st.markdown(f'<div class="card"><h4>💡 Slik er budsjettet laget</h4><div class="muted">Det bygger på hva du '
                    f'vanligvis bruker, med litt kutt i takeaway, klær og lignende. Du får vanligvis inn '
                    f'<b>{kr(info["inntekt"])}</b> i måneden.</div></div>', unsafe_allow_html=True)

    with st.expander("✏️ Endre budsjettet"):
        new = {}
        cols = st.columns(2)
        for i, r in enumerate(b.itertuples()):
            new[r.category] = (cols[i % 2].number_input(f"{EMOJI.get(r.category, '')} {r.category}", min_value=0,
                                                        value=int(r.amount), step=100, key=f"b_{r.category}"), r.kind)
        add = st.selectbox("Legg til kategori", [c for c in PICK_CATEGORIES if c not in new], index=None,
                           placeholder="Legg til en kategori …")
        c1, c2, c3 = st.columns([1, 1, 2])
        if c1.button("Lagre", type="primary", width="stretch"):
            rows = [{"category": c, "amount": a, "kind": k} for c, (a, k) in new.items()]
            if add:
                rows.append({"category": add, "amount": 0,
                             "kind": "sparing" if add == "Sparing" else "fast" if add in budget.FIXED_CATEGORIES else "variabel"})
            db.save_budget(conn, pd.DataFrame(rows))
            st.rerun()
        if c2.button("Lag nytt forslag", width="stretch"):
            db.save_budget(conn, suggestion[["category", "amount", "kind"]])
            st.rerun()
        c3.download_button("⬇️ Last ned som Excel", budget.to_excel(b, stt, info), file_name="budsjett.xlsx",
                           width="stretch",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ======================================================================== innsikt
def sifo_cmp(df):
    try:
        rates = sifo.load_rates()
    except FileNotFoundError:
        return None, None
    hh = setting("household")
    if not hh or not hh.get("medlemmer"):
        return None, rates
    avg = analysis.monthly_average_by_category(df)
    return sifo.compare(avg, hh, rates, setting("sifo_mapping", sifo.DEFAULT_MAPPING)), rates


def page_insight():
    df = load_df()
    if df.empty:
        welcome()
        return
    st.title("Innsikt")
    subs = subscriptions.find_subscriptions(df)
    cmp, rates = sifo_cmp(df)
    t = st.tabs(["💡 Sparetips", "👥 Sammenlignet med andre", "🔮 Hva om …", "📅 Fram til lønning", "📄 Rapport"])

    with t[0]:
        fs = analysis.findings(df, subs, cmp)
        total = sum(f.saving_monthly for f in fs)
        if not fs:
            st.success("Fant ingen tydelige sparemuligheter. Bra jobba! 🎉")
        else:
            st.markdown(f'<div class="hero"><div class="label">Med noen små grep kan du spare</div>'
                        f'<div class="big">{kr(total)} <span style="font-size:20px;font-weight:500">i måneden</span></div>'
                        f'<div class="row"><div>Det blir<b>{kr(total * 12)} i året</b></div></div></div>',
                        unsafe_allow_html=True)
            for f in fs:
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1], vertical_alignment="center")
                    c1.markdown(f"**{'🔥' if f.severity == 3 else '💡'} {f.title}**")
                    c1.write(f.detail)
                    c1.markdown(f"👉 {f.recommendation}")
                    if f.saving_monthly >= 50:
                        c2.markdown(stat("Spar per måned", kr(f.saving_monthly)), unsafe_allow_html=True)

    with t[1]:
        st.write("Hvordan ligger du an mot et vanlig forbruk for noen på din alder? Tallene er fra "
                 "SIFOs referansebudsjett (OsloMet) – et nøkternt, men vanlig nivå i Norge.")
        hh = setting("household") or {"medlemmer": [{"alder": 20, "kjønn": "kvinne"}], "bil": False}
        members = hh.get("medlemmer") or [{"alder": 20, "kjønn": "kvinne"}]
        me = members[0]
        c1, c2, c3, c4 = st.columns(4)
        age = c1.number_input("Alderen din", 14, 100, int(me.get("alder", 20)))
        sex = c2.selectbox("Kjønn", ["kvinne", "mann"], index=0 if me.get("kjønn") == "kvinne" else 1)
        n_other = c3.number_input("Deler økonomi med (antall)", 0, 6, len(members) - 1)
        car_opts = ["ingen", "bensin", "el"]
        car = c4.selectbox("Bil", car_opts, index=car_opts.index(sifo.car_type(hh) or "ingen"),
                           format_func={"ingen": "Ingen bil", "bensin": "Bensinbil", "el": "Elbil"}.get)
        others = (members[1:] + [{"alder": int(age), "kjønn": "kvinne"}] * 6)[:int(n_other)]
        new_hh = {"medlemmer": [{"alder": int(age), "kjønn": sex}] + others, "bil": False if car == "ingen" else car}
        if new_hh != setting("household"):
            db.set_setting(conn, "household", new_hh)
            st.rerun()
        if cmp is not None:
            rows = []
            for r in cmp.itertuples():
                if r.SIFO <= 0:
                    continue
                diff = r.Mitt_snitt - r.SIFO
                color = "#ef4444" if diff > 0 else "#22c55e"
                mx = max(r.Mitt_snitt, r.SIFO, 1)
                rows.append(f'<div style="margin:16px 0"><div style="display:flex;justify-content:space-between">'
                            f'<b>{esc(r.Kategori)}</b><span style="color:{color};font-weight:650">{kr(abs(diff))} '
                            f'{"over" if diff > 0 else "under"}</span></div>'
                            f'<div class="muted">Du: {kr(r.Mitt_snitt)} · Vanlig: {kr(r.SIFO)}</div>'
                            f'<div class="bar"><div style="width:{r.Mitt_snitt / mx * 100:.0f}%;background:{PURPLE}"></div></div>'
                            f'<div class="bar" style="margin-top:3px"><div style="width:{r.SIFO / mx * 100:.0f}%;background:#d4d4e8"></div></div></div>')
            st.markdown(f'<div class="card"><h4>Per måned</h4><div class="muted">'
                        f'<span style="color:{PURPLE}">■</span> deg &nbsp;&nbsp; <span style="color:#c4c4dc">■</span> vanlig nivå</div>'
                        f'{"".join(rows)}</div>', unsafe_allow_html=True)
            st.caption("Husleie, restaurant, alkohol og reiser er ikke med i SIFO, så de sammenlignes ikke her. "
                       f"Kilde: {rates.get('kilde', '')}")

    with t[2]:
        avg = analysis.monthly_average_by_category(df)
        st.write("Dra i spakene og se hva du kan spare.")
        cats = [c for c in avg.index if c not in {"Bolig", "Lån", "Ukategorisert"}][:8]
        cuts = {}
        cols = st.columns(2)
        for i, c in enumerate(cats):
            cuts[c] = cols[i % 2].slider(f"{EMOJI.get(c, '')} {c} – nå {kr(avg[c])} i måneden", 0, 100, 0, step=10,
                                         format="Kutt %d %%", key=f"cut_{c}")
        names = {s.key: s for s in subs if s.active and s.category == "Abonnementer"}
        cancel = st.multiselect("Si opp abonnementer", list(names), placeholder="Velg abonnementer …",
                                format_func=lambda k: f"{names[k].name} ({kr(names[k].monthly)}/mnd)")
        r = analysis.what_if(avg, cuts, sum(names[k].monthly for k in cancel), 5, 0)
        c = st.columns(3)
        c[0].markdown(stat("Per måned", kr(r["per_måned"])), unsafe_allow_html=True)
        c[1].markdown(stat("Per år", kr(r["per_år"])), unsafe_allow_html=True)
        c[2].markdown(stat("Om 5 år", kr(r["totalt"])), unsafe_allow_html=True)

    with t[3]:
        st.write("Hvor mye har du igjen før neste lønning? Skriv inn hva du har på brukskontoen nå.")
        bal = st.number_input("Saldo nå (kr)", value=float(setting("balance", 0.0)), step=500.0)
        if bal != setting("balance", 0.0):
            db.set_setting(conn, "balance", bal)
        fc = analysis.forecast(df, subs, bal)
        if fc and bal:
            ok = fc.estimated_left >= 0
            style = "" if ok else ' style="background:linear-gradient(135deg,#ef4444,#f97316)"'
            st.markdown(f'<div class="hero"{style}><div class="label">Antatt igjen {fc.period_end:%d.%m}</div>'
                        f'<div class="big">{kr(fc.estimated_left)}</div>'
                        f'<div class="row"><div>Faste trekk som kommer<b>{kr(fc.fixed_remaining)}</b></div>'
                        f'<div>Vanlig forbruk framover<b>{kr(fc.variable_remaining)}</b></div>'
                        f'<div>Dager igjen<b>{fc.days_left}</b></div></div></div>', unsafe_allow_html=True)
            if fc.days_left:
                st.caption(f"For å gå i null kan du bruke ca. {kr(max(bal - fc.fixed_remaining, 0) / fc.days_left)} per dag.")
        elif fc:
            st.caption("Skriv inn saldoen for å se prognosen.")

    with t[4]:
        st.write("Lag en pen PDF med månedens tall, kategorier, abonnementer og tips.")
        period = month_picker(df, "rep_month")
        if st.button("Lag månedsrapport", type="primary"):
            with st.spinner("Lager rapport …"):
                path = report.build(df, period, subs=subs, budget=db.get_budget(conn), sifo_cmp=cmp,
                                    findings=analysis.findings(df, subs, cmp), variant="meg")
            st.session_state["report_path"] = str(path)
        rp = st.session_state.get("report_path")
        if rp and Path(rp).exists():
            st.download_button("⬇️ Last ned PDF", Path(rp).read_bytes(), file_name=Path(rp).name, mime="application/pdf")
            st.caption("Rapporten lagres bare på maskinen din.")


# ======================================================================== last opp
BANK_HINTS = [("arkivreferanse", "Sbanken"), ("hovedkategori", "Bulder"), ("forklaring", "DNB"),
              ("tittel", "Nordea"), ("beskrivelse", "SpareBank 1")]


def guess_bank(columns) -> str:
    sig = importer.columns_signature(columns)
    for hint, bank in BANK_HINTS:
        if hint in sig:
            return bank
    return ""


def page_upload():
    st.title("Last opp")
    st.write("Last ned transaksjonene fra nettbanken som **CSV** eller **Excel**, og slipp filen her. "
             "Det gjør ingenting om periodene overlapper – appen hopper over det den allerede har.")
    with st.expander("Hvordan laster jeg ned fra banken?"):
        st.markdown("""
1. Logg inn i nettbanken på PC (ikke i appen på mobilen).
2. Åpne kontoen og velg en periode, f.eks. de siste 3–6 månedene.
3. Se etter **Eksporter** eller **Last ned**, og velg **CSV** eller **Excel**.
4. Slipp filen her. Har du flere kontoer (f.eks. en sparekonto), laster du opp én fil per konto.
""")
    files = st.file_uploader("Slipp filen her", type=["csv", "txt", "xlsx"], accept_multiple_files=True,
                             label_visibility="collapsed")
    accs = db.list_accounts(conn)
    for i, f in enumerate(files or []):
        raw = f.getvalue()
        with st.container(border=True):
            st.markdown(f"**📄 {esc(f.name)}**")
            try:
                table, _ = importer.read_table(raw, f.name)
            except Exception as e:  # noqa: BLE001
                st.error(f"Klarte ikke å lese filen. Er det en CSV- eller Excel-fil fra nettbanken? ({e})")
                continue
            sig = importer.columns_signature(table.columns)
            mapping = db.get_mapping(conn, sig) or importer.guess_mapping(list(table.columns))
            if not mapping:
                mapping = manual_mapping(table, i)
            try:
                res = importer.parse_file(raw, f.name, manual_mapping=mapping)
            except Exception as e:  # noqa: BLE001
                st.error(f"Noe gikk galt: {e}")
                continue
            p = res.df
            if p.empty:
                st.error("Fant ingen kjøp i filen. Sjekk at kolonnene er riktige.")
                continue
            d0, d1 = pd.to_datetime(p["date"]).min(), pd.to_datetime(p["date"]).max()
            st.markdown(f"Fant **{len(p)} transaksjoner** fra {d0:%d.%m.%Y} til {d1:%d.%m.%Y}.")
            bank = guess_bank(table.columns)
            options = accs["name"].tolist()
            new_label = "➕ En ny konto"
            c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
            choice = c1.selectbox("Hvilken konto er dette?", options + [new_label],
                                  index=len(options) if not options else 0, key=f"acc_{i}")
            name = choice
            if choice == new_label:
                default = "Brukskonto" if not options else "Sparekonto"
                name = c1.text_input("Gi kontoen et navn", value=default, key=f"new_{i}")
            if c2.button("Legg til", type="primary", key=f"imp_{i}", width="stretch"):
                aid = db.get_or_create_account(conn, name.strip() or "Brukskonto", bank or None)
                result = db.insert_transactions(conn, p, aid, f.name)
                db.save_mapping(conn, res.signature, res.mapping)
                refresh()
                st.session_state["last_import"] = result
                st.rerun()
    if st.session_state.get("last_import"):
        r = st.session_state.pop("last_import")
        st.success(f"Ferdig! {r['added']} nye transaksjoner lagt til"
                   + (f", {r['skipped']} hadde du fra før." if r["skipped"] else "."), icon="🎉")
        if st.button("Se oversikten →", type="primary"):
            go_to("home")
    if accs.empty:
        st.divider()
        st.caption("Vil du bare se hvordan appen fungerer?")
        if st.button("Prøv med eksempeldata"):
            load_demo()
            go_to("home")


def manual_mapping(table, i):
    st.warning("Vi kjente ikke igjen kolonnene i denne filen. Velg hvilke kolonner som er hva:")
    cols = list(table.columns)
    st.dataframe(table.head(4), width="stretch", hide_index=True)
    c = st.columns(3)
    d = c[0].selectbox("Dato", cols, key=f"md_{i}")
    t = c[1].selectbox("Tekst / beskrivelse", cols, index=min(1, len(cols) - 1), key=f"mt_{i}")
    a = c[2].selectbox("Beløp", cols, index=min(2, len(cols) - 1), key=f"ma_{i}")
    none = "(ingen)"
    with st.expander("Har banken egne kolonner for inn og ut?"):
        o = st.selectbox("Ut", [none] + cols, key=f"mo_{i}")
        n = st.selectbox("Inn", [none] + cols, key=f"mi_{i}")
    if o != none or n != none:
        return {"date": d, "text": t, "amount": None, "out": None if o == none else o, "in": None if n == none else n}
    return {"date": d, "text": t, "amount": a, "out": None, "in": None}


# ======================================================================== innstillinger
def page_settings():
    st.title("Innstillinger")

    with st.container(border=True):
        st.markdown("#### 👤 Navnet ditt")
        st.caption("Brukes til å kjenne igjen når du flytter penger mellom dine egne kontoer, f.eks. "
                   "«Overføring til Emma Hansen» eller «Vipps*Emma Hansen». Det teller ikke som forbruk eller inntekt.")
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        name = c1.text_input("Fullt navn (slik det står i banken)", value=setting("user_name", ""))
        if c2.button("Lagre navn", width="stretch"):
            save_name(name)
            st.rerun()
        words = (setting("user_name", "") or "").split()
        if len(words) == 1:
            st.warning("Skriv både fornavn og etternavn – ellers kan en venn med samme fornavn bli tolket som deg.")
        df = load_df()
        if len(words) >= 2 and not df.empty:
            pats = categorize.own_name_patterns(setting("user_name"))
            hits = df[df["text"].map(lambda t: any(p.search(db.normalize_text(t)) for p in pats))]
            st.caption(f"✅ {len(hits)} overføringer med navnet ditt er registrert som flytting mellom egne kontoer.")

    with st.container(border=True):
        st.markdown("#### 🏦 Kontoene dine")
        accs = db.list_accounts(conn)
        if accs.empty:
            st.caption("Ingen kontoer ennå.")
        else:
            base = accs[["id", "name", "kind"]]
            ed = st.data_editor(base, hide_index=True, width="stretch", key="acc_editor", disabled=["id"],
                                column_config={"id": None, "name": "Navn",
                                               "kind": st.column_config.SelectboxColumn(
                                                   "Type", options=["brukskonto", "sparekonto", "kredittkort"],
                                                   help="Penger du flytter til en sparekonto, telles som sparing")})
            if not ed.reset_index(drop=True).equals(base.reset_index(drop=True)):
                for r in ed.itertuples():
                    db.update_account(conn, int(r.id), name=r.name, kind=r.kind)
                refresh()
                st.rerun()
        imps = db.list_imports(conn)
        if not imps.empty:
            with st.expander("Opplastede filer"):
                for r in imps.itertuples():
                    c1, c2 = st.columns([4, 1], vertical_alignment="center")
                    c1.markdown(f"**{esc(r.filename)}** · {esc(r.konto)} · {r.rows_added} nye · {r.imported_at[:10]}")
                    if c2.button("Slett", key=f"del_imp_{r.id}", width="stretch"):
                        db.delete_import(conn, int(r.id))
                        refresh()
                        st.rerun()

    with st.container(border=True):
        st.markdown("#### 📅 Måned eller lønn til lønn")
        mode = setting("period_mode", "kalender")
        new = st.radio("Vis tallene per", ["kalender", "lønn"], index=0 if mode == "kalender" else 1, horizontal=True,
                       format_func={"kalender": "Kalendermåned", "lønn": "Fra lønning til lønning"}.get)
        if new != mode:
            db.set_setting(conn, "period_mode", new)
            st.session_state.pop("sel_period", None)
            st.rerun()
        if new == "lønn":
            cur = int(setting("payday", 0) or 0)
            pdv = st.number_input("Lønningsdag (0 = finn automatisk)", 0, 31, cur)
            if pdv != cur:
                db.set_setting(conn, "payday", int(pdv))
                st.rerun()

    with st.container(border=True):
        st.markdown("#### 🏷️ Det du har lært appen")
        rules = categorize.list_user_rules(conn)
        if rules.empty:
            st.caption("Ingenting ennå. Her dukker det opp når du gir butikker en kategori.")
        else:
            q = st.text_input("Søk", placeholder=f"🔎  Søk blant {len(rules)} butikker …", key="rule_search",
                              label_visibility="collapsed")
            shown = rules
            if q:
                shown = rules[rules["mønster"].str.contains(q, case=False, regex=False)
                              | rules["kategori"].str.contains(q, case=False, regex=False)]
            st.caption("🤖 = foreslått av Claude. Rull i boksen for å se alle.")
            # Egen boks med fast høyde som du ruller i, så resten av siden blir kort
            with st.container(height=320, border=True):
                if shown.empty:
                    st.caption("Ingen treff.")
                for r in shown.itertuples():
                    c1, c2 = st.columns([4, 1], vertical_alignment="center")
                    who = " 🤖" if r.kilde == "ai" else ""
                    c1.markdown(f"«{esc(r.mønster)}» → {EMOJI.get(r.kategori, '')} {esc(r.kategori)}{who}")
                    if c2.button("Fjern", key=f"rule_{r.id}", width="stretch"):
                        categorize.delete_rule(conn, int(r.id))
                        refresh()
                        st.rerun()

    ai_card()

    with st.container(border=True):
        st.markdown("#### 🔒 Personvern")
        st.markdown(f"Alt lagres bare på denne maskinen, i `{config.DATA_DIR}`. "
                    "Ingenting sendes ut på nettet, med mindre du slår på AI-hjelp – og da bare anonymisert tekst.")
        with st.expander("🗑️ Slett alle data"):
            st.write("Sletter alle transaksjoner, kontoer, budsjett og innstillinger. **Kan ikke angres.**")
            confirm = st.text_input("Skriv SLETT for å bekrefte")
            if st.button("Slett alt", type="primary", disabled=confirm.strip() != "SLETT"):
                conn.close()
                get_conn.clear()
                st.cache_data.clear()
                db.delete_all_data()
                st.session_state.clear()
                st.rerun()


def ai_card():
    with st.container(border=True):
        st.markdown("#### 🤖 AI-hjelp fra Claude")
        st.caption("Claude kan foreslå kategorier for butikker appen ikke kjenner. Claude får bare se "
                   "butikkteksten – aldri beløp, datoer eller kontonummer. Navn på personer byttes ut med "
                   "«Person 1», «Person 2» …, og navnet ditt med «Deg selv».")
        on = st.toggle("Slå på AI-hjelp til kategorisering", value=setting("ai_enabled", False))
        if on != setting("ai_enabled", False):
            db.set_setting(conn, "ai_enabled", on)
            st.rerun()
        if not on:
            return

        st.markdown("**1. Bruk Claude-appen på PC-en** (enklest)")
        path = claude_connect.desktop_config_path()
        if claude_connect.is_connected():
            st.success("Koblet til Claude ✅  Åpne Claude og skriv: *«Hjelp meg å kategorisere utgiftene "
                       "mine i Pengene mine»*. Har du nettopp koblet til, må du avslutte og starte Claude på nytt.")
            if st.button("Koble fra Claude"):
                claude_connect.disconnect()
                st.rerun()
        elif claude_connect.desktop_installed():
            st.caption("Ett trykk, så kan Claude-appen lese de anonymiserte utgiftene og lagre kategorier her.")
            if st.button("Koble til Claude", type="primary"):
                try:
                    claude_connect.connect()
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(f"Klarte ikke å endre {path}: {e}")
        else:
            st.caption("Fant ikke Claude-appen. Last den ned fra claude.ai/download, logg inn og kom tilbake hit.")
        with st.expander("Bruker du Claude Code i terminalen?"):
            st.code(claude_connect.claude_code_command(), language="bash")

        backs = ai_categorize.backends()
        if backs:
            st.markdown("**2. Eller spør Claude rett herfra**")
            ai_suggestions(backs)

        items = ai_categorize.build_items(conn)
        with st.expander(f"👀 Se nøyaktig hva Claude får se ({len(items)} linjer)"):
            if items:
                st.dataframe(pd.DataFrame([i.public() for i in items]), hide_index=True, width="stretch")
            else:
                st.caption("Ingenting – alle utgifter har kategori.")


def ai_suggestions(backs: dict[str, str], key: str = "ai"):
    items = ai_categorize.build_items(conn, limit=10_000)
    if not items:
        st.caption("Alle utgifter har kategori. 🎉")
        return
    backend = next(iter(backs))
    if len(backs) > 1:
        backend = st.radio("Hvordan", list(backs), format_func=backs.get, horizontal=True, key=f"{key}_backend")
    if st.button(f"✨ La Claude foreslå kategorier for {len(items)} butikk{'er' if len(items) > 1 else ''}",
                 key=f"{key}_ask"):
        rounds = -(-len(items) // ai_categorize.BATCH)
        bar = st.progress(0.0, text=f"Spør Claude … (ca. {15 * rounds} sekunder)")
        try:
            st.session_state["ai_sug"] = ai_categorize.suggest(
                items, backend,
                progress=lambda done, total: bar.progress(done / total, text=f"Claude har sett på {done} av {total} …"))
        except RuntimeError as e:
            st.error(str(e))
        bar.empty()
    sug = st.session_state.get("ai_sug")
    if sug is not None:
        by_id = {i.id: i for i in items}
        rows = [{"Bruk": True, "id": k, "Butikk": categorize.merchant_label(by_id[k].key),
                 "Kategori": v["kategori"], "Sikkerhet": "✅ Sikker" if v["sikker"] else "🤔 Gjetning"}
                for k, v in sug.items() if k in by_id]
        rows.sort(key=lambda r: (r["Sikkerhet"] != "✅ Sikker", r["Butikk"]))
        unknown = len(items) - len(rows)
        if not rows:
            st.info("Claude kjente ikke igjen noen av dem. Du kan velge kategori selv under Pengene mine.")
            st.session_state.pop("ai_sug")
            return
        n_guess = sum(r["Sikkerhet"] != "✅ Sikker" for r in rows)
        st.caption(f"Claude har forslag til {len(rows)} av {len(items)} butikker"
                   + (f" ({unknown} hadde ingen hint)" if unknown else "") + ". "
                   + (f"**{n_guess} er gjetninger 🤔** – se ekstra på dem. " if n_guess else "")
                   + "Fjern haken på det som er feil, eller endre kategorien.")
        ed = st.data_editor(pd.DataFrame(rows), hide_index=True, width="stretch", key=f"{key}_editor",
                            disabled=["Butikk", "Sikkerhet"],
                            column_config={"id": None, "Bruk": st.column_config.CheckboxColumn("Bruk", width="small"),
                                           "Kategori": st.column_config.SelectboxColumn(options=PICK_CATEGORIES)})
        c1, c2, c3 = st.columns(3)
        save_all = c1.button("Lagre de med hake", type="primary", key=f"{key}_save", width="stretch")
        save_sure = c2.button("Lagre bare de sikre", key=f"{key}_save_sure", width="stretch")
        if save_all or save_sure:
            chosen = {r.id: r.Kategori for r in ed.itertuples()
                      if r.Bruk and (save_all or r.Sikkerhet == "✅ Sikker")}
            n = ai_categorize.save_suggestions(conn, items, chosen)
            st.session_state.pop("ai_sug")
            st.cache_data.clear()
            st.toast(f"Lagret {n} kategorier ✅")
            st.rerun()
        if c3.button("Avbryt", key=f"{key}_cancel", width="stretch"):
            st.session_state.pop("ai_sug")
            st.rerun()


# ======================================================================== navigasjon
PAGES = {
    "home": st.Page(page_home, title="Hjem", icon=":material/home:", default=True),
    "money": st.Page(page_money, title="Pengene mine", icon=":material/receipt_long:", url_path="pengene"),
    "subs": st.Page(page_subs, title="Abonnementer", icon=":material/autorenew:", url_path="abonnementer"),
    "budget": st.Page(page_budget, title="Budsjett", icon=":material/savings:", url_path="budsjett"),
    "insight": st.Page(page_insight, title="Innsikt", icon=":material/lightbulb:", url_path="innsikt"),
    "upload": st.Page(page_upload, title="Last opp", icon=":material/upload:", url_path="last-opp"),
    "settings": st.Page(page_settings, title="Innstillinger", icon=":material/settings:", url_path="innstillinger"),
}
st.navigation(list(PAGES.values()), position="top").run()
