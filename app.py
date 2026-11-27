"""Forbruksapp – lokal analyse av kontoutskrifter.

Start:  streamlit run app.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from forbruk import (analysis, budget, categorize, config, db, importer, report, sifo,
                     subscriptions)
from forbruk.categorize import ALL_CATEGORIES, EXPENSE_CATEGORIES

st.set_page_config(page_title="Forbruksapp", page_icon="💰", layout="wide")
config.ensure_dirs()

PROJECT = Path(__file__).resolve().parent
COLORS = px.colors.qualitative.Set2


# ======================================================================== felles hjelpere
@st.cache_resource
def get_conn():
    return db.connect()


conn = get_conn()


def kr(x: float | None) -> str:
    if x is None or pd.isna(x):
        return "–"
    return f"{x:,.0f} kr".replace(",", " ")


def settings(key, default=None):
    return db.get_setting(conn, key, default)


def load_df() -> pd.DataFrame:
    df = db.load_transactions(conn)
    if df.empty:
        return df
    mode = settings("period_mode", "kalender")
    payday = settings("payday", 0) or None
    return analysis.add_periods(df, mode, payday)


def filtered(df: pd.DataFrame) -> pd.DataFrame:
    accounts = st.session_state.get("filter_accounts")
    if accounts:
        df = df[df["account"].isin(accounts)]
    return df


def empty_state():
    st.info("Ingen transaksjoner ennå. Gå til **Last opp** for å lese inn en kontoutskrift, "
            "eller prøv appen med falske eksempeldata.")
    if st.button("Last inn eksempeldata", type="primary"):
        load_demo()
        st.rerun()


def load_demo():
    demo = PROJECT / "eksempeldata"
    if not (demo / "dnb_brukskonto_mai-aug.csv").exists():
        import runpy
        runpy.run_path(str(demo / "lag_eksempeldata.py"), run_name="__main__")
    files = [("dnb_brukskonto_mai-aug.csv", "DNB brukskonto", "DNB", "1203.45.67890", "meg"),
             ("dnb_brukskonto_jul-nov.csv", "DNB brukskonto", "DNB", "1203.45.67890", "meg"),
             ("sbanken_sparekonto.xlsx", "Sbanken sparekonto", "Sbanken", "1203.98.76543", "meg"),
             ("nordea_partner.csv", "Partner – Nordea", "Nordea", None, "partner")]
    for f, acc, bank, num, owner in files:
        r = importer.parse_file((demo / f).read_bytes(), f)
        aid = db.get_or_create_account(conn, acc, bank, num, owner)
        db.insert_transactions(conn, r.df, aid, f)
    categorize.refresh(conn)
    if not settings("household"):
        db.set_setting(conn, "household", {"medlemmer": [{"alder": 29, "kjønn": "mann"},
                                                         {"alder": 28, "kjønn": "kvinne"}], "bil": False})


def get_subs(df):
    return subscriptions.find_subscriptions(df)


def sifo_cmp(df):
    try:
        rates = sifo.load_rates()
    except FileNotFoundError:
        return None, None
    hh = settings("household")
    if not hh or not hh.get("medlemmer"):
        return None, rates
    mapping = settings("sifo_mapping", sifo.DEFAULT_MAPPING)
    avg = analysis.monthly_average_by_category(df)
    return sifo.compare(avg, hh, rates, mapping), rates


def period_picker(df, key, label="Periode", default_complete=True):
    pt = analysis.period_table(df)
    if pt.empty:
        return None
    options = pt["period"].tolist()[::-1]
    labels = dict(zip(pt["period"], pt["period_label"] + pt["complete"].map({True: "", False: " (pågår)"})))
    default = 0
    if default_complete:
        done = pt[pt["complete"]]["period"].tolist()
        if done:
            default = options.index(done[-1])
    return st.selectbox(label, options, index=default, format_func=lambda p: labels[p], key=key)


# ======================================================================== sidebar
def sidebar():
    with st.sidebar:
        st.markdown("### Visning")
        mode = settings("period_mode", "kalender")
        new_mode = st.radio("Periode", ["kalender", "lønn"], index=0 if mode == "kalender" else 1,
                            format_func=lambda m: "Kalendermåned" if m == "kalender" else "Lønn til lønn",
                            horizontal=True)
        if new_mode != mode:
            db.set_setting(conn, "period_mode", new_mode)
            st.rerun()
        accs = db.list_accounts(conn)
        if not accs.empty:
            st.multiselect("Kontoer", accs["name"].tolist(), key="filter_accounts",
                           placeholder="Alle kontoer")
        st.divider()
        st.caption(f"🔒 All data lagres lokalt i  \n`{config.DATA_DIR}`")
        if settings("ai_enabled", False):
            st.caption("🤖 AI-kategorisering er **på**")


# ======================================================================== sider
def page_overview():
    st.title("Oversikt")
    df = filtered(load_df())
    if df.empty:
        empty_state()
        return
    summ = analysis.period_summary(df)
    period = period_picker(df, "ov_period")
    cols = summ["period"].tolist()
    cur = summ.set_index("period").loc[period]
    prev = summ.set_index("period").loc[cols[cols.index(period) - 1]] if cols.index(period) > 0 else None

    c = st.columns(4)
    for col, name in zip(c, ["Inn", "Forbruk", "Sparing", "Netto"]):
        delta = None if prev is None else cur[name] - prev[name]
        col.metric(name, kr(cur[name]), None if delta is None else kr(delta),
                   delta_color="inverse" if name == "Forbruk" else "normal")
    if not cur["complete"]:
        st.caption("Perioden pågår fortsatt – tallene er ikke komplette.")

    st.subheader("Inn og ut per periode")
    # Ikke vis en første periode som bare er delvis dekket av dataene (gir misvisende tall)
    summ = summ[summ["period_start"] >= df["date"].min() - pd.Timedelta(days=2)] if len(summ) > 1 else summ
    fig = go.Figure()
    fig.add_bar(x=summ["period_label"], y=summ["Inn"], name="Inn", marker_color="#16a34a")
    fig.add_bar(x=summ["period_label"], y=summ["Forbruk"], name="Forbruk", marker_color="#dc2626")
    fig.add_bar(x=summ["period_label"], y=summ["Sparing"], name="Sparing", marker_color="#2563eb")
    fig.add_scatter(x=summ["period_label"], y=summ["Netto"], name="Netto", mode="lines+markers",
                    line=dict(color="#111827"))
    fig.update_layout(barmode="group", height=360, margin=dict(t=10, b=10), legend=dict(orientation="h"))
    st.plotly_chart(fig, width="stretch")

    left, right = st.columns([3, 2])
    piv = analysis.by_category(df)
    with left:
        st.subheader("Forbruk per kategori")
        if not piv.empty and period in piv.columns:
            s = piv[period][piv[period] > 0].sort_values()
            f2 = px.bar(x=s.values, y=s.index, orientation="h", labels={"x": "kr", "y": ""},
                        text=[kr(v) for v in s.values])
            f2.update_traces(marker_color="#2563eb", textposition="outside")
            f2.update_layout(height=max(300, 28 * len(s)), margin=dict(t=10, b=10, r=60))
            st.plotly_chart(f2, width="stretch")
    with right:
        st.subheader("Topp 10 steder")
        st.dataframe(analysis.top_merchants(df[df["period"] == period]),
                     hide_index=True, width="stretch",
                     column_config={"Sum": st.column_config.NumberColumn(format="%.0f kr")})
        an = analysis.anomalies(df, period)
        if an:
            st.subheader("Avvik")
            for a in an[:4]:
                arrow = "🔺" if a.diff > 0 else "🔻"
                st.write(f"{arrow} **{a.category}**: {kr(a.current)} ({a.pct:+.0f} % mot vanlig {kr(a.baseline)})")

    st.subheader("Utvikling over tid")
    if not piv.empty:
        labels = dict(zip(summ["period"], summ["period_label"]))
        top = piv.sum(axis=1).sort_values(ascending=False).index.tolist()
        chosen = st.multiselect("Kategorier", piv.index.tolist(), default=top[:5])
        if chosen:
            long = piv.loc[chosen].T.reset_index().melt(id_vars="period", var_name="Kategori", value_name="kr")
            long["Periode"] = long["period"].map(labels)
            f3 = px.line(long, x="Periode", y="kr", color="Kategori", markers=True)
            f3.update_layout(height=340, margin=dict(t=10, b=10))
            st.plotly_chart(f3, width="stretch")
        with st.expander("Tabell: forbruk per kategori og periode"):
            t = piv.rename(columns=labels)
            t["Snitt"] = t.mean(axis=1)
            st.dataframe(t.sort_values("Snitt", ascending=False).round(0), width="stretch")


def page_upload():
    st.title("Last opp kontoutskrift")
    st.write("Last ned transaksjoner fra nettbanken som CSV eller Excel og slipp filen her. "
             "Overlappende perioder er ikke noe problem – transaksjoner som allerede finnes, hoppes over.")
    files = st.file_uploader("Velg filer", type=["csv", "txt", "xlsx", "xls"], accept_multiple_files=True)
    accs = db.list_accounts(conn)
    for i, f in enumerate(files or []):
        with st.container(border=True):
            st.markdown(f"#### 📄 {f.name}")
            raw = f.getvalue()
            c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
            options = accs["name"].tolist() + ["➕ Ny konto"]
            acc = c1.selectbox("Konto", options, key=f"acc_{i}",
                               index=len(options) - 1 if accs.empty else 0)
            new_name = bank = number = None
            owner = "meg"
            if acc == "➕ Ny konto":
                new_name = c1.text_input("Navn på kontoen", key=f"newacc_{i}",
                                         placeholder="f.eks. DNB brukskonto")
                bank = c2.text_input("Bank", key=f"bank_{i}")
                number = c3.text_input("Kontonummer (valgfritt)", key=f"num_{i}",
                                       help="Brukes til å kjenne igjen overføringer mellom egne kontoer.")
                owner = c4.selectbox("Eier", ["meg", "partner"], key=f"owner_{i}",
                                     help="Brukes i rapporten for felles økonomi.")
            try:
                table, _ = importer.read_table(raw, f.name)
            except Exception as e:  # noqa: BLE001
                st.error(f"Kunne ikke lese filen: {e}")
                continue
            sig = importer.columns_signature(table.columns)
            saved = db.get_mapping(conn, sig)
            manual = None
            guessed = saved or importer.guess_mapping(list(table.columns))
            with st.expander("Kolonneoppsett" + ("" if guessed else " – må velges"), expanded=not guessed):
                cols = list(table.columns)
                none = "(ingen)"
                g = guessed or {}

                def pick(label, k, opts):
                    val = g.get(k)
                    return st.selectbox(label, opts, index=opts.index(val) if val in opts else 0, key=f"{k}_{i}")

                mc = st.columns(5)
                with mc[0]:
                    d = pick("Dato", "date", cols)
                with mc[1]:
                    t = pick("Tekst", "text", cols)
                with mc[2]:
                    a = pick("Beløp (én kolonne)", "amount", [none] + cols)
                with mc[3]:
                    o = pick("Ut (hvis egen kolonne)", "out", [none] + cols)
                with mc[4]:
                    n = pick("Inn (hvis egen kolonne)", "in", [none] + cols)
                manual = {"date": d, "text": t, "amount": None if a == none else a,
                          "out": None if o == none else o, "in": None if n == none else n}
                st.dataframe(table.head(6), width="stretch")
                if saved:
                    st.caption("Oppsettet er husket fra en tidligere fil med samme kolonner.")
            if not (manual["amount"] or manual["out"] or manual["in"]):
                st.warning("Velg enten en beløpskolonne eller kolonner for inn/ut.")
                continue
            try:
                res = importer.parse_file(raw, f.name, manual_mapping=manual)
            except importer.NeedMapping:
                st.warning("Velg kolonnene over.")
                continue
            except Exception as e:  # noqa: BLE001
                st.error(f"Feil ved lesing: {e}")
                continue
            for w in res.warnings:
                st.caption(f"ℹ️ {w}")
            if res.df.empty:
                st.error("Fant ingen gyldige transaksjoner. Sjekk kolonneoppsettet.")
                continue
            p = res.df
            st.write(f"**{len(p)} transaksjoner** fra {p['date'].min()} til {p['date'].max()} · "
                     f"inn {kr(p[p.amount > 0].amount.sum())} · ut {kr(-p[p.amount < 0].amount.sum())}")
            st.dataframe(p.head(10), hide_index=True, width="stretch")
            if st.button("Importer", key=f"imp_{i}", type="primary"):
                name = new_name if acc == "➕ Ny konto" else acc
                if not name:
                    st.error("Gi kontoen et navn.")
                    continue
                aid = db.get_or_create_account(conn, name, bank or None, number or None, owner)
                result = db.insert_transactions(conn, p, aid, f.name)
                db.save_mapping(conn, res.signature, res.mapping)
                categorize.refresh(conn)
                st.success(f"✅ {result['added']} nye transaksjoner lagt til, "
                           f"{result['skipped']} duplikater hoppet over.")

    st.divider()
    st.subheader("Tidligere opplastinger")
    imps = db.list_imports(conn)
    if imps.empty:
        st.caption("Ingen opplastinger ennå.")
        if st.button("Last inn eksempeldata i stedet"):
            load_demo()
            st.rerun()
        return
    st.dataframe(imps.rename(columns={"filename": "Fil", "imported_at": "Tidspunkt", "konto": "Konto",
                                      "rows_in_file": "Rader i fil", "rows_added": "Lagt til",
                                      "rows_skipped": "Duplikater", "rader_igjen": "Lagret nå"}),
                 hide_index=True, width="stretch")
    c1, c2 = st.columns([3, 1])
    choice = c1.selectbox("Slett transaksjonene fra én opplasting", imps["id"].tolist(),
                          format_func=lambda x: f"#{x} – {imps.set_index('id').loc[x, 'filename']}")
    if c2.button("Slett opplasting", width="stretch"):
        n = db.delete_import(conn, int(choice))
        categorize.refresh(conn)
        st.success(f"Slettet {n} transaksjoner.")
        st.rerun()


def page_transactions():
    st.title("Transaksjoner")
    df = filtered(load_df())
    if df.empty:
        empty_state()
        return
    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
    q = c1.text_input("Søk i tekst", placeholder="f.eks. foodora")
    cats = c2.multiselect("Kategori", sorted(df["category"].unique()))
    dmin, dmax = df["date"].min().date(), df["date"].max().date()
    rng = c3.date_input("Periode", (dmin, dmax), min_value=dmin, max_value=dmax, format="DD.MM.YYYY")
    only = c4.selectbox("Vis", ["Alle", "Bare ut", "Bare inn", "Overføringer", "Felles"])
    v = df
    if q:
        v = v[v["text"].str.contains(q, case=False, regex=False)]
    if cats:
        v = v[v["category"].isin(cats)]
    if isinstance(rng, tuple) and len(rng) == 2:
        v = v[(v["date"].dt.date >= rng[0]) & (v["date"].dt.date <= rng[1])]
    v = {"Bare ut": v[v.amount < 0], "Bare inn": v[v.amount > 0], "Overføringer": v[v.is_transfer],
         "Felles": v[v.is_shared]}.get(only, v)
    st.caption(f"{len(v)} transaksjoner · sum {kr(v['amount'].sum())}" + (" · viser de 1000 nyeste" if len(v) > 1000 else ""))
    v = v.head(1000)
    edit = v[["id", "date", "account", "text", "amount", "category", "is_transfer", "is_shared", "note"]].copy()
    edit["date"] = edit["date"].dt.date
    edited = st.data_editor(
        edit, hide_index=True, width="stretch", height=520, key="tx_editor",
        disabled=["id", "date", "account", "text", "amount"],
        column_config={
            "id": None, "date": st.column_config.DateColumn("Dato", format="DD.MM.YYYY"),
            "account": "Konto", "text": st.column_config.TextColumn("Tekst", width="large"),
            "amount": st.column_config.NumberColumn("Beløp", format="%.2f"),
            "category": st.column_config.SelectboxColumn("Kategori", options=ALL_CATEGORIES, required=True),
            "is_transfer": st.column_config.CheckboxColumn("Overføring", help="Mellom egne kontoer – telles ikke som forbruk"),
            "is_shared": st.column_config.CheckboxColumn("Felles", help="Felles utgift (for rapporten om felles økonomi)"),
            "note": st.column_config.TextColumn("Notat"),
        })
    if st.button("Lagre endringer", type="primary"):
        orig = edit.set_index("id")
        new = edited.set_index("id")
        n = 0
        for tid in new.index:
            o, e = orig.loc[tid], new.loc[tid]
            if o["category"] != e["category"]:
                categorize.set_manual_category(conn, int(tid), e["category"])
                n += 1
            if bool(o["is_transfer"]) != bool(e["is_transfer"]):
                db.update_transaction(conn, int(tid), is_transfer=int(e["is_transfer"]), transfer_manual=1)
                if not e["is_transfer"] and e["category"] == "Overføring":
                    db.update_transaction(conn, int(tid), category_source="rule")
                n += 1
            if bool(o["is_shared"]) != bool(e["is_shared"]):
                db.update_transaction(conn, int(tid), is_shared=int(e["is_shared"]))
                n += 1
            if (o["note"] or "") != (e["note"] or ""):
                db.update_transaction(conn, int(tid), note=e["note"] or None)
                n += 1
        categorize.recategorize_all(conn)
        st.success(f"Lagret {n} endringer.")
        st.rerun()

    with st.expander("➕ Lag regel fra en transaksjon"):
        texts = v["text"].drop_duplicates().tolist()[:300]
        if texts:
            t = st.selectbox("Transaksjon", texts)
            c1, c2 = st.columns(2)
            pattern = c1.text_input("Mønster", value=categorize.merchant_key(t),
                                    help="Ord som må finnes i teksten. Avslutt med * for «begynner med».")
            cat = c2.selectbox("Kategori", ALL_CATEGORIES, key="rule_cat")
            matches = df[df["text"].map(lambda x: bool(categorize.compile_pattern(pattern).search(db.normalize_text(x))) if pattern else False)]
            st.caption(f"Treffer {len(matches)} transaksjoner.")
            if st.button("Lagre regel"):
                categorize.add_rule(conn, pattern, cat)
                categorize.recategorize_all(conn)
                st.success(f"Regel lagret: «{pattern}» → {cat}")
                st.rerun()


def page_rules():
    st.title("Kategorier og regler")
    df = filtered(load_df())
    tabs = st.tabs(["Ukategorisert", "Mine regler", "Innebygde regler", "🤖 AI-forslag"])
    with tabs[0]:
        if df.empty:
            empty_state()
        else:
            unc = df[df["category"] == "Ukategorisert"].copy()
            if unc.empty:
                st.success("Alt er kategorisert 🎉")
            else:
                unc["Mønster"] = unc["text"].map(categorize.merchant_key)
                g = (unc.groupby("Mønster").agg(Antall=("id", "size"), Sum=("amount", "sum"),
                                                 Eksempel=("text", "first"))
                       .sort_values("Sum").reset_index())
                g["Kategori"] = None
                st.write(f"{len(unc)} transaksjoner er ikke kategorisert. Velg kategori for gruppene – "
                         "da lagres en regel som også brukes på fremtidige opplastinger.")
                ed = st.data_editor(g, hide_index=True, width="stretch", key="unc_editor",
                                    disabled=["Antall", "Sum", "Eksempel"],
                                    column_config={
                                        "Mønster": st.column_config.TextColumn(help="Kan redigeres"),
                                        "Sum": st.column_config.NumberColumn(format="%.0f kr"),
                                        "Kategori": st.column_config.SelectboxColumn(options=ALL_CATEGORIES)})
                if st.button("Lagre som regler", type="primary"):
                    n = 0
                    for r in ed.itertuples():
                        if r.Kategori:
                            categorize.add_rule(conn, r.Mønster, r.Kategori)
                            n += 1
                    categorize.recategorize_all(conn)
                    st.success(f"Lagret {n} regler.")
                    st.rerun()
    with tabs[1]:
        rules = categorize.list_user_rules(conn)
        if rules.empty:
            st.caption("Du har ingen egne regler ennå. Lag dem fra «Ukategorisert» eller «Transaksjoner».")
        else:
            st.dataframe(rules.drop(columns=["id"]), hide_index=True, width="stretch")
            c1, c2 = st.columns([3, 1])
            rid = c1.selectbox("Slett regel", rules["id"].tolist(),
                               format_func=lambda x: f"{rules.set_index('id').loc[x, 'mønster']} → {rules.set_index('id').loc[x, 'kategori']}")
            if c2.button("Slett", width="stretch"):
                categorize.delete_rule(conn, int(rid))
                categorize.recategorize_all(conn)
                st.rerun()
        with st.form("new_rule"):
            st.markdown("**Ny regel**")
            c1, c2 = st.columns(2)
            p = c1.text_input("Mønster", help="f.eks. «vipps*ola nordmann», «lønn*», eller «re:^giro \\d+»")
            c = c2.selectbox("Kategori", ALL_CATEGORIES)
            if st.form_submit_button("Legg til"):
                try:
                    categorize.add_rule(conn, p, c)
                    categorize.recategorize_all(conn)
                    st.success("Lagt til.")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(str(e))
        st.caption("Dine regler går foran de innebygde. Manuelt endrede transaksjoner røres aldri.")
    with tabs[2]:
        st.caption("Innebygde regler for vanlige norske butikker. Lag en egen regel med samme mønster for å overstyre.")
        st.dataframe(categorize.list_default_rules(), hide_index=True, width="stretch", height=500)
    with tabs[3]:
        page_ai(df)


def page_ai(df):
    if not settings("ai_enabled", False):
        st.info("AI-kategorisering er **av**. Den kan slås på under **Innstillinger og personvern**. "
                "Når den er på, sendes bare butikknavn – aldri beløp, datoer, kontonumre eller "
                "Vipps-/overføringstekster med personnavn.")
        return
    if df.empty:
        return
    unc = df[df["category"] == "Ukategorisert"]
    from forbruk import ai_categorize
    to_send = ai_categorize.safe_texts(unc["text"].tolist())[:80]
    st.warning("Følgende butikknavn vil bli sendt til Claude (Anthropic) for å få forslag. "
               "Ingenting annet sendes.")
    st.code("\n".join(to_send) or "(ingen ukategoriserte butikker å sende)")
    if to_send and st.button("Hent forslag"):
        try:
            with st.spinner("Spør Claude …"):
                st.session_state["ai_suggestions"] = ai_categorize.suggest_categories(to_send)
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    sug = st.session_state.get("ai_suggestions")
    if sug:
        t = pd.DataFrame([{"Godkjenn": True, "Mønster": k, "Kategori": v} for k, v in sug.items()])
        ed = st.data_editor(t, hide_index=True, width="stretch",
                            column_config={"Kategori": st.column_config.SelectboxColumn(options=EXPENSE_CATEGORIES)})
        if st.button("Lagre godkjente forslag som regler", type="primary"):
            for r in ed.itertuples():
                if r.Godkjenn:
                    categorize.add_rule(conn, r.Mønster, r.Kategori, source="ai")
            categorize.recategorize_all(conn)
            st.session_state.pop("ai_suggestions")
            st.success("Lagret.")
            st.rerun()


def page_subscriptions():
    st.title("Abonnementsjeger")
    df = filtered(load_df())
    if df.empty:
        empty_state()
        return
    subs = get_subs(df)
    if not subs:
        st.info("Fant ingen gjentakende trekk ennå. Det trengs minst to–tre måneder med data.")
        return
    statuses = db.get_subscription_statuses(conn)
    t = subscriptions.to_frame(subs, statuses)
    active, stopped = t[t["Aktiv"]], t[~t["Aktiv"]]

    c = st.columns(3)
    c[0].metric("Aktive faste trekk", len(active))
    c[1].metric("Per måned", kr(active["Per måned"].sum()))
    c[2].metric("Per år", kr(active["Per år"].sum()))

    for g, lst in subscriptions.overlaps(subs).items():
        st.warning(f"**Overlapp – {g}:** {', '.join(s.name for s in lst)} "
                   f"({kr(sum(s.monthly for s in lst))}/mnd). Trenger du alle samtidig?")
    for s in subs:
        if s.active and s.price_change and s.price_change > 0:
            st.error(f"**Prisøkning – {s.name}:** +{kr(s.price_change)} per trekk "
                     f"(nå {kr(s.amount)}, {kr(s.price_change * 12 * 30.44 / s.interval_days)} mer i året).")

    st.subheader("Si opp?")
    st.caption("Marker hva du vil gjøre med hvert trekk. Valgene lagres.")
    ed = st.data_editor(
        active[["key", "Status", "Navn", "Kategori", "Intervall", "Beløp per trekk", "Per måned", "Per år",
                "Sist trukket", "Neste forventet", "Antall trekk", "Eksempeltekst"]],
        hide_index=True, width="stretch", key="subs_editor",
        disabled=[c for c in active.columns if c != "Status"],
        column_config={
            "key": None,
            "Status": st.column_config.SelectboxColumn(options=["Vurder", "Beholde", "Si opp"], required=True),
            "Beløp per trekk": st.column_config.NumberColumn(format="%.0f kr"),
            "Per måned": st.column_config.NumberColumn(format="%.0f kr"),
            "Per år": st.column_config.NumberColumn(format="%.0f kr"),
            "Sist trukket": st.column_config.DateColumn(format="DD.MM.YYYY"),
            "Neste forventet": st.column_config.DateColumn(format="DD.MM.YYYY"),
        })
    changed = False
    for r in ed.itertuples():
        if statuses.get(r.key, "Vurder") != r.Status:
            db.set_subscription_status(conn, r.key, r.Status)
            changed = True
    if changed:
        st.rerun()
    cancel = ed[ed["Status"] == "Si opp"]
    if not cancel.empty:
        st.success(f"💡 Hvis du sier opp de {len(cancel)} markerte, sparer du "
                   f"**{kr(cancel['Per måned'].sum())} i måneden – {kr(cancel['Per år'].sum())} i året.**")

    if not stopped.empty:
        st.subheader("Har sluttet å trekke")
        st.caption("Disse er ikke trukket på en stund. Hvis du har sagt dem opp, ser du her at oppsigelsen gikk gjennom.")
        st.dataframe(stopped[["Navn", "Intervall", "Beløp per trekk", "Sist trukket", "Antall trekk", "Status"]],
                     hide_index=True, width="stretch")


def page_sifo():
    st.title("Sammenligning med SIFO")
    st.write("SIFOs referansebudsjett (OsloMet) viser hva det koster å leve på et nøkternt, men vanlig "
             "nivå i Norge. Nivået avhenger av hvem som bor i husholdningen.")
    df = filtered(load_df())
    try:
        rates = sifo.load_rates()
    except FileNotFoundError:
        st.error(f"Fant ikke {config.SIFO_FILE}.")
        return
    if rates.get("eksempeltall"):
        st.warning("⚠️ **SIFO-satsene er eksempeltall, ikke offisielle tall.** Oppdater "
                   f"`{config.SIFO_FILE.relative_to(PROJECT)}` med tall fra SIFOs referansebudsjett "
                   f"(se README, «Oppdatere SIFO-tall») og sett `\"eksempeltall\": false`.")
    else:
        st.caption(f"Offisielle satser for {rates.get('år')} · kilde: {rates.get('kilde')}")
        if rates.get("merknader"):
            with st.expander("Om tallene"):
                for m in rates["merknader"]:
                    st.write(f"- {m}")

    with st.expander("Husholdningen din", expanded=not settings("household")):
        hh = settings("household", {"medlemmer": [{"alder": 30, "kjønn": "kvinne"}], "bil": False})
        mem = pd.DataFrame(hh.get("medlemmer") or [{"alder": 30, "kjønn": "kvinne"}])
        ed = st.data_editor(mem, num_rows="dynamic", hide_index=True, key="hh_editor",
                            column_config={
                                "alder": st.column_config.NumberColumn("Alder", min_value=0, max_value=120, step=1),
                                "kjønn": st.column_config.SelectboxColumn("Kjønn", options=["kvinne", "mann"], required=True)})
        car_opts = ["ingen", "bensin", "el"]
        car_now = sifo.car_type(hh) or "ingen"
        car = st.radio("Bil", car_opts, index=car_opts.index(car_now), horizontal=True,
                       format_func={"ingen": "Ingen bil", "bensin": "Bensin-/dieselbil", "el": "Elbil"}.get)
        if st.button("Lagre husholdning"):
            members = [{"alder": int(r.alder), "kjønn": r.kjønn} for r in ed.itertuples()
                       if not pd.isna(r.alder) and r.kjønn]
            db.set_setting(conn, "household", {"medlemmer": members, "bil": False if car == "ingen" else car})
            st.rerun()
        st.caption("Kjønn brukes for jente/gutt og kvinne/mann der SIFO skiller. Har du lastet opp partnerens konto også, ta med begge.")

    if df.empty:
        empty_state()
        return
    cmp, _ = sifo_cmp(df)
    if cmp is None:
        st.info("Legg inn husholdningen over for å se sammenligningen.")
        return
    n = len(analysis.complete_periods(df, 3))
    st.caption(f"Ditt snitt er beregnet fra de siste {n} komplette periodene.")
    show = cmp.rename(columns={"Mitt_snitt": "Mitt snitt"})
    fig = go.Figure()
    fig.add_bar(y=show["Kategori"], x=show["Mitt snitt"], name="Mitt snitt", orientation="h", marker_color="#2563eb")
    fig.add_bar(y=show["Kategori"], x=show["SIFO"], name="SIFO", orientation="h", marker_color="#9ca3af")
    fig.update_layout(barmode="group", height=420, margin=dict(t=10, b=10), legend=dict(orientation="h"),
                      yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, width="stretch")

    def color(v):
        return "color: #dc2626" if v > 0 else "color: #16a34a"

    st.dataframe(show.style.format({"Mitt snitt": "{:,.0f} kr", "SIFO": "{:,.0f} kr",
                                    "Differanse": "{:+,.0f} kr", "Prosent": "{:+.0f} %"})
                 .map(color, subset=["Differanse", "Prosent"]),
                 hide_index=True, width="stretch")

    st.subheader("Ikke med i SIFO")
    mapping = settings("sifo_mapping", sifo.DEFAULT_MAPPING)
    um = sifo.unmapped_categories(analysis.monthly_average_by_category(df), mapping)
    if not um.empty:
        st.dataframe(um, hide_index=True, width="stretch",
                     column_config={"Mitt snitt per måned": st.column_config.NumberColumn(format="%.0f kr")})

    with st.expander("Koble kategoriene dine til SIFO-postene"):
        new = {}
        for sc in sifo.DEFAULT_MAPPING:
            new[sc] = st.multiselect(sc, EXPENSE_CATEGORIES, default=mapping.get(sc, []), key=f"map_{sc}")
        c1, c2 = st.columns(2)
        if c1.button("Lagre kobling", type="primary"):
            db.set_setting(conn, "sifo_mapping", new)
            st.rerun()
        if c2.button("Tilbakestill"):
            db.set_setting(conn, "sifo_mapping", sifo.DEFAULT_MAPPING)
            st.rerun()


def page_analysis():
    st.title("Analyse")
    df = filtered(load_df())
    if df.empty:
        empty_state()
        return
    subs = get_subs(df)
    cmp, _ = sifo_cmp(df)
    tabs = st.tabs(["💸 Tullball-detektor", "📈 Avvik", "🔮 Hva om", "📅 Prognose"])

    with tabs[0]:
        fs = analysis.findings(df, subs, cmp)
        if not fs:
            st.success("Fant ingen tydelige sparemuligheter. Godt jobbet!")
        total = sum(f.saving_monthly for f in fs)
        if fs:
            st.metric("Mulig besparelse med realistiske kutt", f"{kr(total)} / mnd", f"{kr(total * 12)} i året",
                      delta_color="off")
        for f in fs:
            icon = {3: "🔴", 2: "🟠", 1: "🔵"}[f.severity]
            with st.container(border=True):
                c1, c2 = st.columns([4, 1])
                c1.markdown(f"#### {icon} {f.title}")
                c1.write(f.detail)
                c1.markdown(f"**Anbefaling:** {f.recommendation}")
                if f.examples:
                    c1.caption(" · ".join(f.examples))
                if f.saving_monthly > 0:
                    c2.metric("Kan spare per måned", kr(f.saving_monthly), kr(f.saving_yearly) + " i året", delta_color="off")

    with tabs[1]:
        p = period_picker(df, "an_period")
        c1, c2, c3 = st.columns(3)
        look = c1.slider("Sammenlign med snittet av forrige … perioder", 1, 6, 3)
        min_kr = c2.number_input("Minste avvik i kr", 0, 10000, 300, step=100)
        min_pct = c3.number_input("Minste avvik i %", 0, 500, 25, step=5)
        an = analysis.anomalies(df, p, look, min_kr, min_pct)
        if not an:
            st.success("Ingen store avvik denne perioden.")
        for a in an:
            msg = (f"**{a.category}:** {kr(a.current)} denne perioden, mot snitt {kr(a.baseline)} "
                   f"({a.pct:+.0f} %, {'+' if a.diff > 0 else '−'}{kr(abs(a.diff))})")
            (st.error if a.diff > 0 else st.success)(msg)

    with tabs[2]:
        avg = analysis.monthly_average_by_category(df)
        st.write("Hva skjer hvis du kutter litt? Dra i spakene.")
        cuts = {}
        cats = [c for c in avg.index if c not in {"Bolig", "Lån", "Ukategorisert"}][:10]
        cols = st.columns(2)
        for i, c in enumerate(cats):
            cuts[c] = cols[i % 2].slider(f"{c} (snitt {kr(avg[c])}/mnd)", 0, 100, 0, step=5, format="%d %%",
                                         key=f"cut_{c}")
        names = {s.key: s for s in subs if s.active}
        cancel = st.multiselect("Si opp abonnementer", list(names), format_func=lambda k: f"{names[k].name} ({kr(names[k].monthly)}/mnd)")
        c1, c2 = st.columns(2)
        years = c1.slider("Antall år", 1, 20, 5)
        rate = c2.slider("Forventet årlig avkastning hvis du sparer pengene", 0.0, 10.0, 0.0, 0.5, format="%.1f %%")
        r = analysis.what_if(avg, cuts, sum(names[k].monthly for k in cancel), years, rate)
        m = st.columns(4)
        m[0].metric("Per måned", kr(r["per_måned"]))
        m[1].metric("Per år", kr(r["per_år"]))
        m[2].metric(f"Om {years} år", kr(r["totalt"]))
        m[3].metric(f"Om {years} år med avkastning", kr(r["med_avkastning"]))

    with tabs[3]:
        st.write("Hvor mye har du igjen før neste lønning? Kontoutskriften har sjelden saldo, så legg den inn selv.")
        bal = st.number_input("Saldo på brukskontoen nå (kr)", value=float(settings("balance", 0.0)), step=500.0)
        if bal != settings("balance", 0.0):
            db.set_setting(conn, "balance", bal)
        fc = analysis.forecast(df, subs, bal)
        if fc:
            st.caption(f"Basert på data til og med {fc.reference_date:%d.%m.%Y}. Perioden ({fc.period_label}) "
                       f"slutter {fc.period_end:%d.%m.%Y} – {fc.days_left} dager igjen.")
            m = st.columns(4)
            m[0].metric("Saldo", kr(fc.balance))
            m[1].metric("Faste trekk som gjenstår", kr(-fc.fixed_remaining))
            m[2].metric("Forventet variabelt forbruk", kr(-fc.variable_remaining), f"{kr(fc.variable_daily)} per dag", delta_color="off")
            m[3].metric("Estimert igjen ved periodeslutt", kr(fc.estimated_left))
            if fc.estimated_left is not None and fc.estimated_left < 0:
                st.error("Prognosen viser at du går i minus før perioden er over. Vurder å holde igjen på variabelt forbruk.")
            if fc.fixed_items:
                st.dataframe(pd.DataFrame(fc.fixed_items, columns=["Trekk", "Forventet dato", "Beløp"]),
                             hide_index=True, column_config={"Forventet dato": st.column_config.DateColumn(format="DD.MM.YYYY"),
                                                             "Beløp": st.column_config.NumberColumn(format="%.0f kr")})


def page_budget():
    st.title("Månedsbudsjett")
    df = filtered(load_df())
    if df.empty:
        empty_state()
        return
    subs = get_subs(df)
    cmp, _ = sifo_cmp(df)
    mapping = settings("sifo_mapping", sifo.DEFAULT_MAPPING)
    suggestion, info = budget.suggest(df, cmp, mapping, subs)
    saved = db.get_budget(conn)

    tabs = st.tabs(["Budsjett", "Følg opp", "Forslag"])
    with tabs[2]:
        st.write("Forslaget bygger på snittet ditt for de siste tre komplette periodene, med kutt der det ofte er "
                 "lett å spare og SIFO som referanse.")
        st.dataframe(suggestion.rename(columns={"category": "Kategori", "snitt": "Snitt i dag",
                                                "amount": "Forslag", "kind": "Type", "begrunnelse": "Begrunnelse"}),
                     hide_index=True, width="stretch",
                     column_config={"Snitt i dag": st.column_config.NumberColumn(format="%.0f kr"),
                                    "Forslag": st.column_config.NumberColumn(format="%.0f kr")})
        c = st.columns(4)
        c[0].metric("Snittinntekt", kr(info["inntekt"]))
        c[1].metric("Utgifter i forslaget", kr(info["sum_utgifter"]))
        c[2].metric("Sparing", kr(info["sparing"]))
        c[3].metric("Til overs", kr(info["rest"]))
        if st.button("Bruk forslaget som budsjett", type="primary"):
            db.save_budget(conn, suggestion[["category", "amount", "kind"]])
            st.rerun()

    with tabs[0]:
        if saved.empty:
            st.info("Du har ikke lagret et budsjett ennå. Se fanen **Forslag**, eller start med forslaget her og juster.")
            saved = suggestion[["category", "amount", "kind"]]
        ed = st.data_editor(saved, num_rows="dynamic", hide_index=True, width="stretch", key="budget_editor",
                            column_config={
                                "category": st.column_config.SelectboxColumn("Kategori", options=EXPENSE_CATEGORIES + ["Sparing"], required=True),
                                "amount": st.column_config.NumberColumn("Per måned", format="%.0f kr", min_value=0, step=100),
                                "kind": st.column_config.SelectboxColumn("Type", options=["fast", "variabel", "sparing"], required=True)})
        if st.button("Lagre budsjett", type="primary"):
            db.save_budget(conn, ed)
            st.success("Lagret.")
            st.rerun()
        inc = info["inntekt"]
        if inc > 0:
            ideal = budget.fifty_thirty_twenty(inc)
            exp = ed[ed["kind"] != "sparing"]
            needs = exp[exp["category"].isin(budget.NEEDS)]["amount"].sum()
            wants = exp[~exp["category"].isin(budget.NEEDS)]["amount"].sum()
            sav = ed[ed["kind"] == "sparing"]["amount"].sum()
            st.subheader("50/30/20-sjekk")
            st.caption("50 % til behov (bolig, mat, transport …), 30 % til ønsker, 20 % til sparing.")
            t = pd.DataFrame({"Del": ["Behov", "Ønsker", "Sparing"], "Ditt budsjett": [needs, wants, sav],
                              "50/30/20": [ideal["behov"], ideal["ønsker"], ideal["sparing"]]})
            t["Andel av inntekt"] = t["Ditt budsjett"] / inc * 100
            st.dataframe(t, hide_index=True, column_config={
                "Ditt budsjett": st.column_config.NumberColumn(format="%.0f kr"),
                "50/30/20": st.column_config.NumberColumn(format="%.0f kr"),
                "Andel av inntekt": st.column_config.NumberColumn(format="%.0f %%")})
            left = inc - ed["amount"].sum()
            (st.success if left >= 0 else st.error)(f"Inntekt {kr(inc)} − budsjett {kr(ed['amount'].sum())} = **{kr(left)}** til overs per måned.")

    with tabs[1]:
        b = db.get_budget(conn)
        if b.empty:
            st.info("Lagre et budsjett først.")
        else:
            p = period_picker(df, "bud_period", default_complete=False)
            stt = budget.status(df, b, p)
            for r in stt.itertuples():
                pct = r[6]
                over = r.Brukt > r.Budsjett
                label = f"**{r.Kategori}** – {kr(r.Brukt)} av {kr(r.Budsjett)}"
                if r.Type == "sparing":
                    label += " spart"
                elif over:
                    label += f" · 🔴 {kr(r.Brukt - r.Budsjett)} over"
                else:
                    label += f" · {kr(r.Igjen)} igjen"
                st.write(label)
                st.progress(min(pct / 100, 1.0) if r.Budsjett else 1.0)
            xlsx = budget.to_excel(b, stt, info)
            st.download_button("⬇️ Last ned budsjett som Excel", xlsx, file_name="budsjett.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def page_report():
    st.title("Månedsrapport (PDF)")
    df = filtered(load_df())
    if df.empty:
        empty_state()
        return
    p = period_picker(df, "rep_period")
    variant = st.radio("Variant", ["meg", "felles"], horizontal=True,
                       format_func=lambda v: "Bare meg" if v == "meg" else "Felles økonomi")
    shared_cfg = settings("shared", {"my_name": "Meg", "partner_name": "Partner", "my_share": 50,
                                     "categories": ["Bolig", "Dagligvarer"]})
    shared = None
    if variant == "felles":
        with st.container(border=True):
            c1, c2, c3 = st.columns(3)
            my = c1.text_input("Ditt navn", shared_cfg["my_name"])
            partner = c2.text_input("Partners navn", shared_cfg["partner_name"])
            share = c3.slider("Din andel av felles utgifter", 0, 100, int(shared_cfg["my_share"]), format="%d %%",
                              help="F.eks. 50/50, eller fordelt etter inntekt.")
            cats = st.multiselect("Kategorier som alltid er felles", EXPENSE_CATEGORIES, shared_cfg["categories"])
            st.caption("I tillegg teller transaksjoner du har markert som «Felles» under Transaksjoner. "
                       "Kontoer med eier «partner» regnes som betalt av partneren.")
            inc_me = analysis.income(df[(df["owner"] == "meg") & df["period"].isin(analysis.complete_periods(df, 3))])["amount"].sum()
            inc_p = analysis.income(df[(df["owner"] == "partner") & df["period"].isin(analysis.complete_periods(df, 3))])["amount"].sum()
            if inc_me + inc_p > 0 and inc_p > 0:
                st.caption(f"Fordeling etter inntekt ville vært {inc_me / (inc_me + inc_p) * 100:.0f} % / {inc_p / (inc_me + inc_p) * 100:.0f} %.")
            new_cfg = {"my_name": my, "partner_name": partner, "my_share": share, "categories": cats}
            if new_cfg != shared_cfg:
                db.set_setting(conn, "shared", new_cfg)
                shared_cfg = new_cfg
        shared = budget.shared_split(df[df["period"] == p], shared_cfg["my_share"], shared_cfg["categories"])
        c = st.columns(3)
        c[0].metric(f"Betalt av {shared_cfg['my_name']}", kr(shared["betalt_meg"]))
        c[1].metric(f"Betalt av {shared_cfg['partner_name']}", kr(shared["betalt_partner"]))
        owe = shared["jeg_skylder"]
        who = (f"{shared_cfg['my_name']} skylder {shared_cfg['partner_name']}" if owe > 0
               else f"{shared_cfg['partner_name']} skylder {shared_cfg['my_name']}")
        c[2].metric(who if abs(owe) >= 1 else "Skuls", kr(abs(owe)))

    if st.button("Lag PDF", type="primary"):
        subs = get_subs(df)
        cmp, _ = sifo_cmp(df)
        with st.spinner("Lager rapport …"):
            path = report.build(df, p, subs=subs, budget=db.get_budget(conn), sifo_cmp=cmp,
                                findings=analysis.findings(df, subs, cmp), variant=variant, shared=shared,
                                partner_name=shared_cfg["partner_name"], my_name=shared_cfg["my_name"])
        st.success(f"Rapporten er lagret lokalt: `{path}`")
        st.download_button("⬇️ Last ned PDF", path.read_bytes(), file_name=path.name, mime="application/pdf")
    st.caption("Rapporten lagres bare på maskinen din. Du velger selv om du vil dele den.")


def page_settings():
    st.title("Innstillinger og personvern")
    st.subheader("🔒 Personvern")
    st.markdown(f"""
- All data lagres lokalt i **`{config.DATA_DIR}`** (database: `{config.DB_PATH.name}`, rapporter: `{config.REPORT_DIR.name}/`).
- Appen kjører bare på denne maskinen (`localhost`), og Streamlits bruksstatistikk er skrudd av.
- Ingen data sendes noe sted, med mindre du slår på AI-kategorisering under.
""")

    st.subheader("Kontoer")
    accs = db.list_accounts(conn)
    if accs.empty:
        st.caption("Ingen kontoer ennå.")
    else:
        ed = st.data_editor(accs, hide_index=True, width="stretch", key="acc_editor", disabled=["id"],
                            column_config={"id": None, "name": "Navn", "bank": "Bank",
                                           "account_number": st.column_config.TextColumn("Kontonummer", help="Brukes til å finne overføringer mellom egne kontoer"),
                                           "owner": st.column_config.SelectboxColumn("Eier", options=["meg", "partner"]),
                                           "kind": st.column_config.SelectboxColumn("Type", options=["brukskonto", "sparekonto", "kredittkort"],
                                                                                    help="Overføringer inn på en sparekonto telles som sparing")})
        if st.button("Lagre kontoer"):
            for r in ed.itertuples():
                db.update_account(conn, int(r.id), name=r.name, bank=r.bank, account_number=r.account_number,
                                  owner=r.owner, kind=r.kind)
            categorize.refresh(conn)
            st.success("Lagret.")
            st.rerun()

    st.subheader("Lønn til lønn")
    df = db.load_transactions(conn)
    auto = analysis.detect_payday(df) if not df.empty else None
    cur = settings("payday", 0)
    pd_val = st.number_input("Lønningsdag (0 = finn automatisk)", 0, 31, int(cur),
                             help=f"Fant automatisk: den {auto}." if auto else "Fant ingen lønn i dataene ennå.")
    if pd_val != cur:
        db.set_setting(conn, "payday", int(pd_val))
        st.rerun()
    st.caption("Når lønna kommer en annen dag (f.eks. før helg), brukes den faktiske lønnsdatoen.")

    st.subheader("🤖 AI-kategorisering (valgfritt)")
    st.markdown("""
Når dette er på, kan du be Claude (Anthropic) foreslå kategorier for butikker som reglene ikke kjenner igjen.
- **Bare butikknavn sendes** – aldri beløp, datoer, kontonumre eller Vipps-/overføringstekster som kan inneholde personnavn.
- Du ser nøyaktig hva som sendes før du trykker, og må godkjenne forslagene før de lagres.
- Krever en API-nøkkel (`ANTHROPIC_API_KEY`) eller `ant auth login`, og koster litt per forespørsel.
""")
    on = st.toggle("Slå på AI-kategorisering", value=settings("ai_enabled", False))
    if on != settings("ai_enabled", False):
        db.set_setting(conn, "ai_enabled", on)
        st.rerun()

    st.subheader("Slett data")
    if not df.empty:
        c1, c2, c3 = st.columns([2, 2, 1])
        start = c1.date_input("Fra", df["date"].min().date(), format="DD.MM.YYYY", key="del_from")
        end = c2.date_input("Til", df["date"].max().date(), format="DD.MM.YYYY", key="del_to")
        if c3.button("Slett periode", width="stretch"):
            n = db.delete_period(conn, start.isoformat(), end.isoformat())
            st.success(f"Slettet {n} transaksjoner.")
            st.rerun()
        st.caption("Vil du slette én bestemt opplasting? Gå til **Last opp**.")
    with st.container(border=True):
        st.markdown("#### 🗑️ Slett alle data")
        st.write("Sletter alle transaksjoner, kontoer, regler, budsjett, innstillinger og genererte rapporter. "
                 "**Kan ikke angres.**")
        confirm = st.text_input("Skriv SLETT for å bekrefte")
        if st.button("Slett alle data", type="primary", disabled=confirm.strip() != "SLETT"):
            conn.close()
            get_conn.clear()
            db.delete_all_data()
            st.session_state.clear()
            st.success("Alle data er slettet.")
            st.rerun()


# ======================================================================== navigasjon
sidebar()
pages = {
    "": [st.Page(page_overview, title="Oversikt", icon="📊", default=True),
         st.Page(page_upload, title="Last opp", icon="📤", url_path="last-opp"),
         st.Page(page_transactions, title="Transaksjoner", icon="📋", url_path="transaksjoner"),
         st.Page(page_rules, title="Kategorier og regler", icon="🏷️", url_path="regler")],
    "Analyse": [st.Page(page_subscriptions, title="Abonnementer", icon="🔁", url_path="abonnementer"),
                st.Page(page_analysis, title="Tullball og prognoser", icon="💸", url_path="analyse"),
                st.Page(page_sifo, title="SIFO", icon="⚖️", url_path="sifo")],
    "Plan": [st.Page(page_budget, title="Budsjett", icon="🎯", url_path="budsjett"),
             st.Page(page_report, title="Månedsrapport", icon="📄", url_path="rapport")],
    "System": [st.Page(page_settings, title="Innstillinger og personvern", icon="🔒", url_path="innstillinger")],
}
st.navigation(pages).run()
