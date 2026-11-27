import pytest

from forbruk import importer


@pytest.mark.parametrize("raw, expected", [
    ("1 234,50", 1234.5), ("-1 234,50", -1234.5), ("1.234,50", 1234.5), ("1,234.50", 1234.5),
    ("1234.5", 1234.5), ("1.234", 1234.0), ("12,5", 12.5), ("(50,00)", -50.0), ("123,00-", -123.0),
    ("−1 000,00", -1000.0), ("kr 89,00", 89.0), ("", None), ("abc", None), (42, 42.0),
])
def test_parse_amount(raw, expected):
    assert importer.parse_amount(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("03.11.2026", "2026-11-03"), ("03.11.26", "2026-11-03"), ("2026-11-03", "2026-11-03"),
    ("2026/11/03", "2026-11-03"), ("Reservert", None), ("", None),
])
def test_parse_date(raw, expected):
    assert importer.parse_date(raw) == expected


def test_semicolon_cp1252_with_in_out_columns():
    csv = "Dato;Forklaring;Rentedato;Uttak;Innskudd\n03.11.2026;Rema 1000 Grünerløkka;03.11.2026;1 234,50;\n04.11.2026;Lønn;04.11.2026;;38 500,00\n"
    r = importer.parse_file(csv.encode("cp1252"), "dnb.csv")
    assert list(r.df["amount"]) == [-1234.5, 38500.0]
    assert r.df["text"][0] == "Rema 1000 Grünerløkka"
    assert r.df["date"][0] == "2026-11-03"


def test_comma_separated_single_amount_utf8_bom():
    csv = '﻿Bokføringsdato,Beløp,Tittel\n2026/11/03,"-89,00",NARVESEN\nReservert,"-10,00",KIOSK\n'
    r = importer.parse_file(csv.encode("utf-8"), "nordea.csv")
    assert len(r.df) == 1 and r.df["amount"][0] == -89.0
    assert r.skipped_rows == 1


def test_preamble_rows_before_header():
    csv = "Kontoutskrift;;\nKonto 1234.56.78901;;\n;;\nDato;Tekst;Beløp\n01.10.2026;Kiwi;-55,90\n"
    r = importer.parse_file(csv.encode("utf-8"), "x.csv")
    assert r.df["amount"].tolist() == [-55.9]


def test_unknown_columns_need_mapping():
    csv = "A;B;C\n01.10.2026;Kiwi;-55,90\n"
    with pytest.raises(importer.NeedMapping) as e:
        importer.parse_file(csv.encode("utf-8"), "x.csv")
    mapping = {"date": "A", "text": "B", "amount": "C", "out": None, "in": None}
    r = importer.parse_file(csv.encode("utf-8"), "x.csv", manual_mapping=mapping)
    assert r.df["amount"].tolist() == [-55.9]
    assert e.value.columns == ["A", "B", "C"]


def test_demo_files_parse(demo_dir):
    for f in demo_dir.glob("*.*"):
        if f.suffix in {".csv", ".xlsx"}:
            r = importer.parse_file(f.read_bytes(), f.name)
            assert len(r.df) > 0, f.name
            assert r.df["date"].notna().all()
