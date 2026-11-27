import pandas as pd

from forbruk import db


def frame(rows):
    return pd.DataFrame(rows, columns=["date", "text", "amount"])


def test_overlapping_files_skip_duplicates(conn):
    acc = db.get_or_create_account(conn, "Brukskonto")
    a = frame([("2026-10-01", "Kiwi", -50.0), ("2026-10-02", "Rema", -80.0)])
    b = frame([("2026-10-02", "Rema", -80.0), ("2026-10-03", "Meny", -120.0)])
    assert db.insert_transactions(conn, a, acc, "a.csv")["added"] == 2
    res = db.insert_transactions(conn, b, acc, "b.csv")
    assert res == {**res, "added": 1, "skipped": 1}
    assert len(db.load_transactions(conn)) == 3


def test_real_duplicates_within_file_are_kept(conn):
    """To like kaffekjøp samme dag er to ekte kjøp."""
    acc = db.get_or_create_account(conn, "Brukskonto")
    coffee = frame([("2026-10-01", "Espresso House", -52.0)] * 2)
    assert db.insert_transactions(conn, coffee, acc, "a.csv")["added"] == 2
    # Ny fil med de samme to kjøpene + ett nytt likt kjøp samme dag
    again = frame([("2026-10-01", "Espresso House", -52.0)] * 3)
    res = db.insert_transactions(conn, again, acc, "b.csv")
    assert res["added"] == 1 and res["skipped"] == 2
    assert len(db.load_transactions(conn)) == 3


def test_same_transaction_on_different_accounts(conn):
    a1 = db.get_or_create_account(conn, "Konto 1")
    a2 = db.get_or_create_account(conn, "Konto 2")
    t = frame([("2026-10-01", "Kiwi", -50.0)])
    db.insert_transactions(conn, t, a1, "a.csv")
    assert db.insert_transactions(conn, t, a2, "b.csv")["added"] == 1


def test_whitespace_and_case_do_not_create_duplicates(conn):
    acc = db.get_or_create_account(conn, "Brukskonto")
    db.insert_transactions(conn, frame([("2026-10-01", "REMA 1000  Storo", -50.0)]), acc, "a")
    assert db.insert_transactions(conn, frame([("2026-10-01", "rema 1000 storo", -50.0)]), acc, "b")["added"] == 0


def test_delete_import_and_all(conn, tmp_path):
    acc = db.get_or_create_account(conn, "Brukskonto")
    r = db.insert_transactions(conn, frame([("2026-10-01", "Kiwi", -50.0)]), acc, "a")
    assert db.delete_import(conn, r["import_id"]) == 1
    db.delete_all_data(tmp_path / "test.db")
    assert not (tmp_path / "test.db").exists()
