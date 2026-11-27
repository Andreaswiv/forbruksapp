import pandas as pd

from forbruk import categorize, db, importer, plan, subscriptions


def load(conn, demo_dir):
    db.set_setting(conn, "user_name", "Emma Hansen")
    for f, acc, num in [("dnb_brukskonto_mai-aug.csv", "Brukskonto", "1203.45.67890"),
                        ("dnb_brukskonto_jul-nov.csv", "Brukskonto", "1203.45.67890"),
                        ("sbanken_sparekonto.xlsx", "Sparekonto", "1203.98.76543")]:
        r = importer.parse_file((demo_dir / f).read_bytes(), f)
        db.insert_transactions(conn, r.df, db.get_or_create_account(conn, acc, None, num), f)
    categorize.refresh(conn)
    df = db.load_transactions(conn)
    return df, subscriptions.find_subscriptions(df)


def test_new_plan_from_demo(conn, demo_dir):
    df, subs = load(conn, demo_dir)
    p = plan.new_plan(df, subs, "2026-12")
    inc = {i["navn"]: i["beløp"] for i in p["inntekter"]}
    assert inc == {"Lønn Fjellsiden": 14500, "Lånekassen Utbetaling": 11000}
    fixed = {f["navn"]: f["beløp"] for f in p["faste"]}
    assert fixed["Husleie Hybel"] == 6500          # én gang, selv om desember har 31 dager
    assert "Netflix" in fixed and fixed["Netflix"] == 199
    assert not any(f["kategori"] == "Alkohol" for f in p["faste"])   # Vinmonopolet er ikke en fast utgift
    assert 0 < p["sparing"] <= 2600
    t = plan.totals(p)
    assert t["ufordelt"] >= -100                     # forslaget går omtrent opp


def test_rest_is_cut_when_money_is_short(conn, demo_dir):
    df, subs = load(conn, demo_dir)
    fixed = plan.fixed_costs(subs, "2026-12")
    rich, missing_rich = plan.suggest_rest(df, 40000, fixed, [], 2000)
    poor, missing_poor = plan.suggest_rest(df, 17000, fixed, [{"beløp": 1500}], 1000)
    r, p = rich.set_index("kategori")["beløp"], poor.set_index("kategori")["beløp"]
    assert missing_rich == 0
    # Det kuttes mer i takeaway enn i mat
    assert p["Restaurant og takeaway"] / r["Restaurant og takeaway"] < p["Dagligvarer"] / r["Dagligvarer"]
    assert p.sum() <= 17000 - sum(f["beløp"] for f in fixed) - 1500 - 1000 + 100 + missing_poor


def test_yearly_subscription_only_in_due_month():
    s = subscriptions.Subscription(
        key="x", name="Domeneleie", category="Abonnementer", interval="årlig", interval_days=365, amount=300,
        monthly=25, yearly=300, count=2, first=pd.Timestamp("2025-03-10"), last=pd.Timestamp("2026-03-10"),
        next_expected=pd.Timestamp("2027-03-10"), active=True, price_change=None, overlap_group=None, sample_text="")
    assert plan.fixed_costs([s], "2027-03")[0]["beløp"] == 300
    assert plan.fixed_costs([s], "2026-12") == []


def test_plan_is_saved_and_followed_up(conn, demo_dir):
    df, subs = load(conn, demo_dir)
    p = plan.new_plan(df, subs, "2026-10")
    p["egne"] = [{"navn": "Konsert", "kategori": "Fritid", "beløp": 800}]
    plan.save_plan(conn, p)
    assert plan.get_plan(conn, "2026-10")["egne"][0]["navn"] == "Konsert"
    assert "2026-10" in plan.planned_months(conn)
    by_cat = plan.by_category(p).set_index("category")
    assert by_cat.loc["Fritid", "amount"] >= 800
    assert by_cat.loc["Sparing", "kind"] == "sparing"
    stt = plan.follow_up(df, p).set_index("Kategori")
    assert stt.loc["Bolig", "Brukt"] == 6500
    assert stt.loc["Sparing", "Brukt"] == 1000      # overføringen til sparekontoen
    plan.delete_plan(conn, "2026-10")
    assert plan.get_plan(conn, "2026-10") is None


def test_income_is_only_work_and_grants(conn, demo_dir):
    db.set_setting(conn, "user_name", "Emma Hansen")
    aid = db.get_or_create_account(conn, "Brukskonto", "DNB", "1203.45.67890")
    rows = []
    for m in ("2026-08", "2026-09", "2026-10", "2026-11"):
        rows += [(f"{m}-05", "Vipps*Kari Nordmann", 500.0),            # mamma
                 (f"{m}-06", "Fra: Ola Nordmann", 1000.0),              # pappa
                 (f"{m}-07", "Vipps*Petter Smart", 200.0),              # kompis
                 (f"{m}-15", "Statens lånekasse for utdanning", 11000.0),
                 (f"{m}-21", "Fjordbris Konsult AS", 9000.0),                  # jobb uten «lønn» i teksten
                 (f"{m}-20", "Lønn Fjellsiden Konsult AS", 14500.0),
                 (f"{m}-28", "Rema 1000", -300.0)]
    df = pd.DataFrame(rows, columns=["date", "text", "amount"])
    db.insert_transactions(conn, df, aid, "t.csv")
    categorize.refresh(conn)
    names = {i["navn"] for i in plan.income_sources(db.load_transactions(conn))}
    assert names == {"Lønn Fjellsiden", "Statens Lånekasse", "Fjordbris Konsult"}



def test_student_salary_depends_on_season(conn):
    """Sommerjobb gir mye høyere lønn – forslaget for desember skal bygge på månedene utenom sommeren."""
    aid = db.get_or_create_account(conn, "Brukskonto", "DNB", None)
    pay = {"2025-11": 8000, "2025-12": 7000, "2026-01": 9000, "2026-02": 8500, "2026-03": 6000, "2026-04": 7500,
           "2026-05": 8000, "2026-06": 20000, "2026-07": 22000, "2026-08": 40000, "2026-09": 6000, "2026-10": 7000}
    rows = [(f"{m}-20", "Fjordbris Konsult AS", float(a)) for m, a in pay.items()]
    rows += [("2025-11-01", "Rema 1000", -200.0), ("2026-10-31", "Rema 1000", -200.0)]
    db.insert_transactions(conn, pd.DataFrame(rows, columns=["date", "text", "amount"]), aid, "t.csv")
    categorize.refresh(conn)
    df = db.load_transactions(conn)
    dec = plan.income_sources(df, month="2026-12")[0]["beløp"]
    jul = plan.income_sources(df, month="2027-07")[0]["beløp"]
    assert dec == 7500                     # median av september–mai
    assert jul == 22000                    # median av juni–august
    assert "lavere utenom sommeren" in plan.season_note("2026-12")


def test_money_in_from_annet_place_is_not_negative_spending(conn):
    """En regel lært fra et kjøp («Annet») skal ikke gjøre lønn fra samme sted til minus-forbruk."""
    from forbruk import analysis
    aid = db.get_or_create_account(conn, "Brukskonto", "DNB", None)
    categorize.add_rule(conn, "universitetet i", "Annet")
    rows = [("2026-10-29", "Universitetet i Agder", -750.0), ("2026-11-11", "UNIVERSITETET I AGDER", 13755.0)]
    db.insert_transactions(conn, pd.DataFrame(rows, columns=["date", "text", "amount"]), aid, "t.csv")
    categorize.refresh(conn)
    df = db.load_transactions(conn)
    assert df.set_index("amount").loc[13755.0, "category"] == "Inntekt annet"
    assert (analysis.spending(df).groupby("category")["spend"].sum() >= 0).all()


def test_payments_to_people_are_not_subscriptions(conn):
    aid = db.get_or_create_account(conn, "Brukskonto", "DNB", None)
    rows = []
    for m in ("2026-07", "2026-08", "2026-09", "2026-10"):
        rows += [(f"{m}-03", "Vipps*Kari Nordmann", -110.0), (f"{m}-05", "Netflix.com", -199.0),
                 (f"{m}-07", "Hbo Max", -129.0)]
    db.insert_transactions(conn, pd.DataFrame(rows, columns=["date", "text", "amount"]), aid, "t.csv")
    categorize.refresh(conn)
    names = {s.name for s in subscriptions.find_subscriptions(db.load_transactions(conn))}
    assert {"Netflix", "Hbo Max"} <= names and not any("Kari" in n for n in names)
