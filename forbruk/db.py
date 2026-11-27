"""SQLite-lagring: transaksjoner, kontoer, opplastinger, regler, budsjett og innstillinger."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    bank TEXT,
    account_number TEXT,
    owner TEXT NOT NULL DEFAULT 'meg',     -- 'meg' eller 'partner'
    kind TEXT NOT NULL DEFAULT 'brukskonto' -- brukskonto / sparekonto / kredittkort
);

CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    rows_in_file INTEGER NOT NULL,
    rows_added INTEGER NOT NULL,
    rows_skipped INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    import_id INTEGER REFERENCES imports(id),
    date TEXT NOT NULL,                    -- ISO yyyy-mm-dd
    text TEXT NOT NULL,
    amount REAL NOT NULL,                  -- negativt = penger ut
    dedup_key TEXT NOT NULL,
    occurrence INTEGER NOT NULL,
    category TEXT,
    category_source TEXT NOT NULL DEFAULT 'none',   -- rule / manual / none
    is_transfer INTEGER NOT NULL DEFAULT 0,
    transfer_manual INTEGER NOT NULL DEFAULT 0,      -- 1 = brukeren har satt is_transfer selv
    is_shared INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    UNIQUE(account_id, dedup_key, occurrence)
);
CREATE INDEX IF NOT EXISTS ix_tx_date ON transactions(date);

CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL,
    category TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user',   -- default / user / ai
    created_at TEXT NOT NULL,
    UNIQUE(pattern, source)
);

CREATE TABLE IF NOT EXISTS column_mappings (
    signature TEXT PRIMARY KEY,
    mapping TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscription_status (
    sub_key TEXT PRIMARY KEY,
    status TEXT NOT NULL                   -- Beholde / Si opp / Vurder
);

CREATE TABLE IF NOT EXISTS budget (
    category TEXT PRIMARY KEY,
    amount REAL NOT NULL,
    kind TEXT NOT NULL DEFAULT 'variabel'  -- fast / variabel / sparing
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ---------------------------------------------------------------- innstillinger
def get_setting(conn, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(conn, key: str, value: Any) -> None:
    with tx(conn):
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )


# ---------------------------------------------------------------- kontoer
def guess_kind(name: str) -> str:
    n = name.lower()
    if "spar" in n or "bsu" in n:
        return "sparekonto"
    if "kreditt" in n or "visa" in n or "mastercard" in n:
        return "kredittkort"
    return "brukskonto"


def get_or_create_account(conn, name: str, bank: str | None = None,
                          account_number: str | None = None, owner: str = "meg",
                          kind: str | None = None) -> int:
    row = conn.execute("SELECT id FROM accounts WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO accounts(name, bank, account_number, owner, kind) VALUES(?, ?, ?, ?, ?)",
            (name, bank, account_number, owner, kind or guess_kind(name)),
        )
    return cur.lastrowid


def list_accounts(conn) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM accounts ORDER BY name", conn)


def update_account(conn, account_id: int, **fields) -> None:
    allowed = {"name", "bank", "account_number", "owner", "kind"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    cols = ", ".join(f"{k} = ?" for k in sets)
    with tx(conn):
        conn.execute(f"UPDATE accounts SET {cols} WHERE id = ?", (*sets.values(), account_id))


# ---------------------------------------------------------------- transaksjoner
def normalize_text(text: str) -> str:
    return " ".join(str(text).lower().split())


def make_dedup_key(date: str, amount: float, text: str) -> str:
    raw = f"{date}|{round(float(amount) * 100)}|{normalize_text(text)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def insert_transactions(conn, df: pd.DataFrame, account_id: int, filename: str) -> dict:
    """Legger inn rader (kolonner: date, text, amount) og hopper over duplikater.

    Duplikatlogikk: hver rad får en nøkkel (dato + beløp + tekst). Innen samme fil
    nummereres like nøkler 1, 2, 3 … (`occurrence`). Kombinasjonen
    (konto, nøkkel, occurrence) er unik i databasen. Slik blir to like kaffekjøp samme
    dag lagret som to kjøp, mens en overlappende fil med de samme to kjøpene ikke gir
    flere enn to.
    """
    work = df[["date", "text", "amount"]].copy()
    work["dedup_key"] = [make_dedup_key(d, a, t) for d, a, t in
                         zip(work["date"], work["amount"], work["text"])]
    work["occurrence"] = work.groupby("dedup_key").cumcount() + 1

    with tx(conn):
        cur = conn.execute(
            "INSERT INTO imports(filename, imported_at, account_id, rows_in_file, rows_added, rows_skipped) "
            "VALUES(?, ?, ?, ?, 0, 0)",
            (filename, datetime.now().isoformat(timespec="seconds"), account_id, len(work)),
        )
        import_id = cur.lastrowid
        added = 0
        for r in work.itertuples(index=False):
            c = conn.execute(
                "INSERT OR IGNORE INTO transactions(account_id, import_id, date, text, amount, dedup_key, occurrence) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (account_id, import_id, r.date, r.text, float(r.amount), r.dedup_key, int(r.occurrence)),
            )
            added += c.rowcount
        skipped = len(work) - added
        conn.execute("UPDATE imports SET rows_added = ?, rows_skipped = ? WHERE id = ?",
                     (added, skipped, import_id))
    return {"import_id": import_id, "added": added, "skipped": skipped, "total": len(work)}


def load_transactions(conn) -> pd.DataFrame:
    df = pd.read_sql_query(
        """SELECT t.*, a.name AS account, a.owner AS owner, a.kind AS account_kind
           FROM transactions t JOIN accounts a ON a.id = t.account_id
           ORDER BY t.date DESC, t.id DESC""",
        conn,
    )
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["category"] = df["category"].fillna("Ukategorisert")
    df["is_transfer"] = df["is_transfer"].astype(bool)
    df["is_shared"] = df["is_shared"].astype(bool)
    return df


def update_transaction(conn, tx_id: int, **fields) -> None:
    allowed = {"category", "category_source", "is_transfer", "transfer_manual", "is_shared", "note"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    cols = ", ".join(f"{k} = ?" for k in sets)
    with tx(conn):
        conn.execute(f"UPDATE transactions SET {cols} WHERE id = ?", (*sets.values(), tx_id))


def list_imports(conn) -> pd.DataFrame:
    return pd.read_sql_query(
        """SELECT i.id, i.filename, i.imported_at, a.name AS konto, i.rows_in_file,
                  i.rows_added, i.rows_skipped,
                  (SELECT COUNT(*) FROM transactions t WHERE t.import_id = i.id) AS rader_igjen
           FROM imports i JOIN accounts a ON a.id = i.account_id
           ORDER BY i.imported_at DESC""",
        conn,
    )


def delete_import(conn, import_id: int) -> int:
    with tx(conn):
        n = conn.execute("DELETE FROM transactions WHERE import_id = ?", (import_id,)).rowcount
        conn.execute("DELETE FROM imports WHERE id = ?", (import_id,))
    return n


def delete_period(conn, start: str, end: str) -> int:
    with tx(conn):
        return conn.execute("DELETE FROM transactions WHERE date BETWEEN ? AND ?", (start, end)).rowcount


# ---------------------------------------------------------------- kolonneoppsett per bank
def get_mapping(conn, signature: str) -> dict | None:
    row = conn.execute("SELECT mapping FROM column_mappings WHERE signature = ?", (signature,)).fetchone()
    return json.loads(row["mapping"]) if row else None


def save_mapping(conn, signature: str, mapping: dict) -> None:
    with tx(conn):
        conn.execute(
            "INSERT INTO column_mappings(signature, mapping) VALUES(?, ?) "
            "ON CONFLICT(signature) DO UPDATE SET mapping = excluded.mapping",
            (signature, json.dumps(mapping, ensure_ascii=False)),
        )


# ---------------------------------------------------------------- abonnement/budsjett
def get_subscription_statuses(conn) -> dict[str, str]:
    return {r["sub_key"]: r["status"] for r in conn.execute("SELECT * FROM subscription_status")}


def set_subscription_status(conn, sub_key: str, status: str) -> None:
    with tx(conn):
        conn.execute(
            "INSERT INTO subscription_status(sub_key, status) VALUES(?, ?) "
            "ON CONFLICT(sub_key) DO UPDATE SET status = excluded.status",
            (sub_key, status),
        )


def get_budget(conn) -> pd.DataFrame:
    return pd.read_sql_query("SELECT category, amount, kind FROM budget ORDER BY kind, category", conn)


def save_budget(conn, df: pd.DataFrame) -> None:
    with tx(conn):
        conn.execute("DELETE FROM budget")
        for r in df.itertuples(index=False):
            if not r.category or pd.isna(r.amount):
                continue
            conn.execute("INSERT OR REPLACE INTO budget(category, amount, kind) VALUES(?, ?, ?)",
                         (r.category, float(r.amount), r.kind or "variabel"))


# ---------------------------------------------------------------- sletting
def delete_all_data(db_path: Path | None = None) -> None:
    """Sletter databasen og alle genererte rapporter."""
    path = Path(db_path) if db_path else config.DB_PATH
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.unlink()
    if config.REPORT_DIR.exists():
        for f in config.REPORT_DIR.glob("*"):
            if f.is_file():
                f.unlink()
