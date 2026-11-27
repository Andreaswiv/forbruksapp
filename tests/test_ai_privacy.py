"""Sjekker at ingenting personlig sendes til Claude."""
import json
import re
import subprocess
import sys

import pandas as pd
import pytest

from forbruk import ai_categorize, categorize, claude_connect, db
from forbruk.anonymize import Anonymizer

PROJECT = __import__("pathlib").Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("text, must_not_contain", [
    ("Vipps*Ola Nordmann", ["ola", "nordmann"]),
    ("VIPPS*OLA NORDMANN", ["ola", "nordmann"]),
    ("Fra: Kari Nordmann 12345678", ["kari", "nordmann"]),
    ("Overføring til 1203.45.67890 Kari", ["kari", "1203"]),
    ("Til: Trygve Sletten", ["trygve", "sletten"]),
    ("Betaling til Ole Brumm Pettersen", ["ole", "brumm", "pettersen"]),
    ("Straksbetaling til Nils", ["nils"]),
    ("Gave til Sofie Berg fra Emma", ["sofie", "berg", "emma"]),
    ("Hansen Emma", ["hansen", "emma"]),
    ("Overføring til Emma Hansen", ["emma", "hansen"]),
    ("Tannlege Kristin Berg AS", ["kristin", "berg"]),
    ("post@kari.no Kiosk 98765432", ["kari", "9876", "@"]),
    ("*4821 05.11 NOK 129,00 Ukjent Nettbutikk", ["4821", "129", "05.11"]),
    # Fornavn som ikke står på listen, uten «Vipps»/«Til:» foran
    ("Olai Bergh Oldeide", ["olai", "bergh", "oldeide"]),
    ("Caroline Støa Helland", ["caroline", "støa", "helland"]),
    ("Torbjørn Aas Kvam Lie penger tilbake", ["torbjørn", "aas", "kvam", "lie"]),
    ("Middag med Ingvild Støa", ["ingvild", "støa"]),
    # Mange etternavn og navnepartikler
    ("Kari Mc Dermott", ["kari", "dermott"]),
    ("Ola Per Nordmann Hansen Vik", ["ola", "nordmann", "hansen", "vik"]),
    ("Anne-Lise van der Berg", ["anne", "lise", "berg"]),
    ("fra emma", ["emma"]),
    # Små butikker der kortterminalen står på eieren
    ("SUMUP *NASKO ATANASOV", ["nasko", "atanasov"]),
    ("SumUp  *Milen Velikov Sta", ["milen", "velikov"]),
    # Enkeltpersonforetak med STORE bokstaver og utenlandske navn
    ("HOSSAIN KAMAL", ["hossain", "kamal"]),
    ("HOSSEIN MD ANOWER", ["hossein", "anower"]),
    ("CECCONI ROBERTA", ["cecconi", "roberta"]),
])
def test_names_and_numbers_are_removed(text, must_not_contain):
    out = Anonymizer("Emma Hansen").anonymize(text).lower()
    for bad in must_not_contain:
        assert bad not in out, (text, out)
    assert not re.search(r"\d", re.sub(r"person \d+", "", out))


def test_rules_match_texts_with_symbols_and_numbers(conn):
    aid = db.get_or_create_account(conn, "Brukskonto", "DNB", None)
    df = pd.DataFrame({"date": ["2026-10-01", "2026-10-02", "2026-10-03"],
                       "text": ["NYX*StudentsamskipnadenAg", "Småsparing 1 stk fast beløp", "Småsparing 7 stk fast beløp"],
                       "amount": [-50.0, -100.0, -100.0]})
    db.insert_transactions(conn, df, aid, "t.csv")
    for t in df["text"]:
        categorize.add_rule(conn, categorize.merchant_key(t), "Sparing" if "spar" in t.lower() else "Restaurant og takeaway")
    categorize.refresh(conn)
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE category = 'Ukategorisert'").fetchone()[0] == 0
    assert categorize.merchant_key("Småsparing 1 stk") == categorize.merchant_key("Småsparing 12 stk") == "småsparing"


def test_businesses_are_kept():
    a = Anonymizer("Emma Hansen", lambda t: "foodora" in t.lower())
    assert a.anonymize("Vipps*Foodora") == "Vipps Foodora"
    assert "Kafe Hjerte" in a.anonymize("Vipps*Kafe Hjerte")
    assert a.anonymize("Varekjøp Ukjent Butikk 12345678 Dato 03.11") == "Ukjent Butikk"
    assert a.anonymize("Tannlege Kristin Berg AS").startswith("Tannlege Person")
    assert a.anonymize("SumUp *PIZZERIA VALLE") == "SumUp PIZZERIA VALLE"


def test_same_person_gets_same_number():
    a = Anonymizer()
    assert a.anonymize("Vipps*Ola Nordmann") == a.anonymize("VIPPS*OLA NORDMANN") == "Vipps Person 1"
    assert a.anonymize("Til: Kari Holm") == "Til Person 2"


@pytest.fixture
def unknown_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("FORBRUKSAPP_DIR", str(tmp_path))
    conn = db.connect(tmp_path / "forbruk.db")      # samme fil som MCP-serveren åpner
    db.set_setting(conn, "user_name", "Emma Hansen")
    db.set_setting(conn, "ai_enabled", True)
    aid = db.get_or_create_account(conn, "Brukskonto", "DNB", "1203.45.67890")
    df = pd.DataFrame({
        "date": ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"],
        "text": ["Betaling til Ole Brumm Pettersen", "Ukjent Nettbutikk 4471 Dato 03.10",
                 "Kristin Berg Frisør", "Ukjent Nettbutikk 4471 Dato 05.10", "Rema 1000 Storo"],
        "amount": [-450.0, -899.0, -650.0, -120.0, -300.0]})
    db.insert_transactions(conn, df, aid, "t.csv")
    categorize.refresh(conn)
    yield conn
    conn.close()


def _env(conn):
    import os
    from pathlib import Path
    return dict(os.environ, FORBRUKSAPP_DIR=str(Path(conn.execute("PRAGMA database_list").fetchone()[2]).parent))


def test_only_anonymous_text_is_sent(unknown_conn):
    items = ai_categorize.build_items(unknown_conn)
    sent = json.dumps([i.public() for i in items], ensure_ascii=False).lower()
    for bad in ["ole", "brumm", "pettersen", "kristin", "berg", "emma", "hansen", "1203", "4471",
                "450", "899", "650", "2026", "rema"]:
        assert bad not in sent, bad
    assert "ukjent nettbutikk" in sent
    assert all(set(i.public()) == {"id", "tekst", "retning"} for i in items)


def test_suggestions_are_saved_locally_by_id(unknown_conn):
    items = ai_categorize.build_items(unknown_conn)
    shop = next(i for i in items if "Nettbutikk" in i.text)
    n = ai_categorize.save_suggestions(unknown_conn, items, {shop.id: "Klær og sko", "kfalsk": "Bil"})
    assert n == 1
    cats = dict(unknown_conn.execute("SELECT text, category FROM transactions").fetchall())
    assert cats["Ukjent Nettbutikk 4471 Dato 03.10"] == "Klær og sko"


def _mcp(env, *messages):
    p = subprocess.run([sys.executable, str(PROJECT / "mcp_server.py")], capture_output=True, text=True, env=env,
                       input="\n".join(json.dumps(m) for m in messages) + "\n", timeout=60)
    return [json.loads(line) for line in p.stdout.splitlines()]


def test_mcp_server(unknown_conn):
    env = _env(unknown_conn)
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
    out = _mcp(env, init, {"jsonrpc": "2.0", "method": "notifications/initialized"},
               {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
               {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "hent_ukjente_utgifter", "arguments": {}}})
    assert out[0]["result"]["serverInfo"]["name"] == "forbruksapp"
    assert {t["name"] for t in out[1]["result"]["tools"]} == {"hent_ukjente_utgifter", "lagre_kategorier"}
    data = out[2]["result"]["structuredContent"]
    text = json.dumps(data, ensure_ascii=False).lower()
    assert "pettersen" not in text and "kristin" not in text and "1203" not in text
    shop = next(u for u in data["utgifter"] if "nettbutikk" in u["tekst"].lower())
    out = _mcp(env, init, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
        "name": "lagre_kategorier", "arguments": {"forslag": [{"id": shop["id"], "kategori": "Elektronikk"}]}}})
    assert out[1]["result"]["structuredContent"]["lagret"] == 1


def test_mcp_refuses_when_ai_is_off(unknown_conn):
    db.set_setting(unknown_conn, "ai_enabled", False)
    out = _mcp(_env(unknown_conn), {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": "hent_ukjente_utgifter", "arguments": {}}})
    assert out[0]["result"]["isError"] is True
    assert "utgifter" not in out[0]["result"]["structuredContent"]


def test_connect_keeps_other_settings(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"preferences": {"x": 1}, "mcpServers": {"annen": {"command": "a"}}}))
    claude_connect.connect(cfg)
    data = json.loads(cfg.read_text())
    assert data["preferences"] == {"x": 1} and "annen" in data["mcpServers"]
    assert data["mcpServers"]["forbruksapp"]["args"][0].endswith("mcp_server.py")
    assert claude_connect.is_connected(cfg)
    assert (tmp_path / "claude_desktop_config.json.bak").exists()
    claude_connect.disconnect(cfg)
    assert not claude_connect.is_connected(cfg) and "annen" in json.loads(cfg.read_text())["mcpServers"]
