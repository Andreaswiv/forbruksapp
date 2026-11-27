from pathlib import Path

import pandas as pd

from forbruk import analysis, budget, categorize, db, importer, report, sifo, subscriptions


def load_demo(conn, demo_dir):
    for f, acc, num, owner in [("dnb_brukskonto_mai-aug.csv", "DNB brukskonto", "1203.45.67890", "meg"),
                               ("dnb_brukskonto_jul-nov.csv", "DNB brukskonto", "1203.45.67890", "meg"),
                               ("sbanken_sparekonto.xlsx", "Sbanken sparekonto", "1203.98.76543", "meg"),
                               ("nordea_partner.csv", "Partner", None, "partner")]:
        r = importer.parse_file((demo_dir / f).read_bytes(), f)
        db.insert_transactions(conn, r.df, db.get_or_create_account(conn, acc, None, num, owner), f)
    categorize.refresh(conn)
    return db.load_transactions(conn)


def test_demo_end_to_end(conn, demo_dir, tmp_path):
    df = load_demo(conn, demo_dir)
    d = analysis.add_periods(df, "kalender")
    summ = analysis.period_summary(d)
    assert (summ[summ["complete"]]["Sparing"] == 3000).all()     # overføring til sparekonto = sparing
    assert not summ.iloc[-1]["complete"]                          # november pågår
    subs = subscriptions.find_subscriptions(d)
    names = {s.name for s in subs}
    assert {"Netflix", "Spotify", "Hbo Max", "Sats Norway"} <= names
    assert not any("Rema" in n or "Meny" in n for n in names)
    netflix = next(s for s in subs if s.name == "Netflix")
    assert netflix.price_change == 20
    assert not next(s for s in subs if s.name.startswith("Viaplay")).active
    cmp = sifo.compare(analysis.monthly_average_by_category(d),
                       {"medlemmer": [{"alder": 29, "kjønn": "mann"}, {"alder": 28, "kjønn": "kvinne"}]},
                       sifo.load_rates())
    fs = analysis.findings(d, subs, cmp)
    assert any(f.title == "Restaurant og takeaway" for f in fs)
    b, info = budget.suggest(d, cmp, sifo.DEFAULT_MAPPING, subs)
    assert info["inntekt"] > 0 and "Sparing" in set(b["category"])
    shared = budget.shared_split(d[d["period"] == "2026-10"], 50, ["Dagligvarer"])
    assert shared["betalt_partner"] > 0
    p = report.build(d, "2026-10", subs=subs, budget=b, sifo_cmp=cmp, findings=fs, variant="felles",
                     shared=shared, out_dir=tmp_path)
    assert p.read_bytes()[:4] == b"%PDF"


def test_pay_periods_use_actual_salary_date(conn, demo_dir):
    d = analysis.add_periods(load_demo(conn, demo_dir), "lønn", 20)
    # Lønn 20. juni 2026 er lørdag → kom fredag 19.
    assert "2026-06-19" in set(d["period"])


def test_what_if():
    r = analysis.what_if(pd.Series({"Restaurant og takeaway": 2000.0}), {"Restaurant og takeaway": 50},
                         cancelled_monthly=100, years=5)
    assert r["per_måned"] == 1100 and r["totalt"] == 1100 * 60
    assert analysis.what_if(pd.Series({"A": 1000.0}), {"A": 100}, years=1, annual_rate=5)["med_avkastning"] > 12000


def test_sifo_matches_official_example_family():
    """SIFOs eksempelfamilie 2026: mor (K 25–50), far (M 25–50), jente 11, gutt 5, bensinbil."""
    hh = {"medlemmer": [{"alder": 40, "kjønn": "kvinne"}, {"alder": 40, "kjønn": "mann"},
                        {"alder": 11, "kjønn": "kvinne"}, {"alder": 5, "kjønn": "mann"}], "bil": "bensin"}
    b = sifo.household_budget(hh, sifo.load_rates())
    assert b["Mat og drikke"] == 4280 + 4760 + 3750 + 2585
    assert b["Personlig pleie"] == 1020 + 820 + 520 + 240
    assert b["Lek, sport og mediebruk"] == 1080 + 1080 + 1570 + 810
    # SIFOs eksempelfamilie tar bare med voksnes billetter; tabellen har 338 kr for 6–19 år
    assert b["Reisekostnader"] == 1019 * 2 + 338
    assert (b["Andre dagligvarer"], b["Husholdningsartikler"], b["Møbler"], b["Mediebruk og fritid"],
            b["Bilkostnader"]) == (760, 920, 990, 2850, 3375)


def test_sifo_household():
    rates = sifo.load_rates()
    one = sifo.household_budget({"medlemmer": [{"alder": 30, "kjønn": "mann"}]}, rates)
    two = sifo.household_budget({"medlemmer": [{"alder": 30, "kjønn": "mann"}, {"alder": 4, "kjønn": "kvinne"}],
                                 "bil": True}, rates)
    assert two["Mat og drikke"] > one["Mat og drikke"]
    assert "Bilkostnader" in two and "Bilkostnader" not in one
