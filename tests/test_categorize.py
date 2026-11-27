import pandas as pd
import pytest

from forbruk import categorize, db

RULES = [categorize.Rule(p, c, s, "default") for p, c, s in categorize.DEFAULT_RULES] + \
        [categorize.Rule(p, c, s, "generic") for p, c, s in categorize.GENERIC_RULES]


@pytest.mark.parametrize("text, amount, expected", [
    ("Varekjøp Rema 1000 Grünerløkka Dato 03.11", -250, "Dagligvarer"),
    ("*4821 05.11 NOK 129,00 HBO MAX Kurs: 1.0000", -129, "Abonnementer"),
    ("Max Burgers Storo", -150, "Restaurant og takeaway"),
    ("Vipps*Foodora", -300, "Restaurant og takeaway"),
    ("Vipps*Ola Nordmann", -200, "Vipps"),
    ("Lønn Fjellsiden AS", 38500, "Lønn"),
    ("Lønnsinnbetaling", 38500, "Lønn"),
    ("Lånekassen", -1870, "Lån"),
    ("Lånekassen stipend", 5000, "Inntekt annet"),
    ("Sparing fond", -1000, "Sparing"),
    ("Spar Majorstuen", -100, "Dagligvarer"),
    ("Revolut transfer", -100, "Ukategorisert"),   # «evo» skal ikke treffe «revolut»
    ("Ukjent firma", 500, "Inntekt annet"),
    ("Purregebyr Fjordkraft", -35, "Gebyrer og renter"),
])
def test_default_rules(text, amount, expected):
    assert categorize.categorize(text, amount, RULES) == expected


def test_user_rule_beats_default(conn):
    categorize.add_rule(conn, "rema 1000", "Annet")
    rules = categorize.all_rules(conn)
    assert categorize.categorize("Rema 1000 Storo", -100, rules) == "Annet"


def test_prefix_and_regex_rules(conn):
    categorize.add_rule(conn, "abc*", "Fritid")
    categorize.add_rule(conn, r"re:^giro \d+", "Bolig")
    rules = categorize.all_rules(conn)
    assert categorize.categorize("ABCDEF butikk", -1, rules) == "Fritid"
    assert categorize.categorize("Giro 12345", -1, rules) == "Bolig"


@pytest.mark.parametrize("text, key", [
    ("Varekjøp Rema 1000 Grünerløkka Dato 03.11", "rema 1000"),
    ("*4821 05.11 NOK 129,00 HBO MAX Kurs: 1.0000", "hbo max"),
    ("Netflix.com", "netflix"),
    ("Spotify P2F8K1L9", "spotify"),
    ("Vipps*Ola Nordmann", "vipps ola nordmann"),
])
def test_merchant_key(text, key):
    assert categorize.merchant_key(text) == key


def test_manual_category_is_never_overwritten(conn):
    acc = db.get_or_create_account(conn, "Brukskonto")
    db.insert_transactions(conn, pd.DataFrame([("2026-10-01", "Rema 1000", -50.0)],
                                              columns=["date", "text", "amount"]), acc, "a")
    categorize.refresh(conn)
    tid = int(db.load_transactions(conn)["id"][0])
    categorize.set_manual_category(conn, tid, "Gaver")
    categorize.refresh(conn)
    assert db.load_transactions(conn)["category"][0] == "Gaver"


def test_transfer_pairs_between_own_accounts(conn):
    a = db.get_or_create_account(conn, "Brukskonto")
    b = db.get_or_create_account(conn, "Sparekonto")
    f = lambda rows: pd.DataFrame(rows, columns=["date", "text", "amount"])
    db.insert_transactions(conn, f([("2026-10-25", "Nettbank overført", -3000.0),
                                    ("2026-10-26", "Kiwi", -3000.0)]), a, "a")
    db.insert_transactions(conn, f([("2026-10-26", "Innskudd", 3000.0)]), b, "b")
    categorize.refresh(conn)
    df = db.load_transactions(conn).set_index("text")
    assert bool(df.loc["Nettbank overført", "is_transfer"])
    assert bool(df.loc["Innskudd", "is_transfer"])
    assert not bool(df.loc["Kiwi", "is_transfer"])     # bare ett par per overføring
