import pandas as pd

from forbruk import subscriptions


def tx(rows):
    df = pd.DataFrame(rows, columns=["date", "text", "amount", "category"])
    df["date"] = pd.to_datetime(df["date"])
    df["is_transfer"] = False
    return df


def months(text, amounts, day=3, category="Abonnementer", start=5):
    return [(f"2026-{start + i:02d}-{day:02d}", text, -a, category) for i, a in enumerate(amounts)]


def test_detects_monthly_subscription_and_price_increase():
    df = tx(months("Netflix.com", [179, 179, 179, 179, 199, 199]))
    subs = subscriptions.find_subscriptions(df)
    assert len(subs) == 1
    s = subs[0]
    assert s.interval == "månedlig" and s.active
    assert s.price_change == 20
    assert round(s.yearly) == round(199 * 12 * 30.44 / 30.4)


def test_cancelled_subscription_is_inactive():
    df = tx(months("Viaplay", [449, 449, 449]) + [("2026-11-20", "Rema 1000", -300, "Dagligvarer")])
    s = subscriptions.find_subscriptions(df)[0]
    assert not s.active


def test_variable_shopping_is_not_a_subscription():
    rows = [(f"2026-{m:02d}-{d:02d}", "Elkjøp Storo", -a, "Elektronikk")
            for m, d, a in [(5, 3, 200), (6, 9, 1500), (7, 1, 99), (8, 20, 3000)]]
    assert subscriptions.find_subscriptions(tx(rows)) == []


def test_overlap_groups():
    df = tx(months("Netflix.com", [199] * 4) + months("HBO Max", [129] * 4, day=5) +
            months("Spotify", [139] * 4, day=7))
    subs = subscriptions.find_subscriptions(df)
    ov = subscriptions.overlaps(subs)
    assert list(ov) == ["Strømmetjenester (TV/film)"]
    assert {s.name for s in ov["Strømmetjenester (TV/film)"]} == {"Netflix", "Hbo Max"}


def test_yearly_subscription():
    df = tx([("2025-03-01", "Dropbox", -1190, "Abonnementer"), ("2026-03-02", "Dropbox", -1190, "Abonnementer")])
    s = subscriptions.find_subscriptions(df, reference_date=pd.Timestamp("2026-11-01"))[0]
    assert s.interval == "årlig" and s.active and round(s.monthly) == 99
