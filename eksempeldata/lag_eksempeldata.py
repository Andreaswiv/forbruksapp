"""Lager falske kontoutskrifter i tre ulike bankformater for testing.

Profil: «Emma Hansen», 20 år, student med deltidsjobb og hybel i Oslo.

Kjør:  python eksempeldata/lag_eksempeldata.py

Filer som lages:
  dnb_brukskonto_mai-aug.csv   DNB-format, Windows-1252, semikolon, desimalkomma
  dnb_brukskonto_jul-nov.csv   DNB-format, overlapper jul–aug med filen over (tester duplikater)
  sbanken_sparekonto.xlsx      Sbanken-format (Excel), overføringer fra brukskontoen
  nordea_partner.csv           Nordea-format, UTF-8, én beløpskolonne, yyyy/mm/dd (partnerens konto)
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
START, END = date(2026, 5, 1), date(2026, 11, 25)
BRUKSKONTO, SPAREKONTO = "1203.45.67890", "1203.98.76543"
OWN_NAME = "Emma Hansen"


def days():
    d = START
    while d <= END:
        yield d
        d += timedelta(days=1)


def build_main(rng: random.Random) -> list[tuple[date, str, float]]:
    tx: list[tuple[date, str, float]] = []
    for d in days():
        # Faste ting
        if d.day == 1:
            tx.append((d, "Husleie hybel Sagene avtalegiro", -6500))
        if d.day == 3:
            tx.append((d, "Netflix.com", -179 if d < date(2026, 9, 1) else -199))   # prisøkning
            tx.append((d, "Spotify P2F8K1L9", -139))
        if d.day == 5:
            tx.append((d, "*4821 05.%02d NOK 129,00 HBO MAX Kurs: 1.0000" % d.month, -129))
        if d.day == 7:
            tx.append((d, "Telia Norge AS mobil", -399))
        if d.day == 8 and d < date(2026, 9, 1):
            tx.append((d, "Viaplay Group", -449))                                      # sagt opp i sept
        if d.day == 10:
            tx.append((d, "SATS Norway medlemskap", -549))
        if d.day == 12:
            tx.append((d, "Apple.com/bill iCloud", -39))
            tx.append((d, "Google One storage", -25))
        if d.day == 15:
            tx.append((d, "Lånekassen utbetaling", 11000))
        if d.day == 25:
            tx.append((d, f"Overføring til egen konto {SPAREKONTO}", -1000))
        # Penger mellom egne kontoer i en annen bank (kjennes igjen på navnet)
        if d.day == 26:
            tx.append((d, f"Overføring til {OWN_NAME}", -1500))
        if d.day == 9 and d.month % 2 == 0:
            tx.append((d, f"Fra: {OWN_NAME}", 800))
        # Lønn den 20. (fredag før hvis helg)
        payday = date(d.year, d.month, 20)
        while payday.weekday() >= 5:
            payday -= timedelta(days=1)
        if d == payday:
            tx.append((d, "Lønn Fjellsiden Konsult AS", 14500))
        # Dagligvarer
        if rng.random() < 0.55:
            store = rng.choice(["Rema 1000 Grünerløkka", "Kiwi 505 Torshov", "Coop Extra Storo",
                                "Meny Storo", "Joker Sagene"])
            amount = round(rng.uniform(60, 450), 2)
            tx.append((d, f"Varekjøp {store} Dato {d:%d.%m}", -amount))
        # Takeaway – mer i helgene
        if rng.random() < (0.45 if d.weekday() >= 4 else 0.12):
            place = rng.choice(["Foodora", "Wolt", "Vipps*Foodora", "Peppes Pizza Storo", "McDonald's Storo"])
            tx.append((d, place, -round(rng.uniform(149, 420), 2)))
        # Kaffe – to like kjøp samme dag noen ganger (ekte duplikat)
        if d.weekday() < 5 and rng.random() < 0.6:
            tx.append((d, "Espresso House Oslo S", -52))
            if rng.random() < 0.15:
                tx.append((d, "Espresso House Oslo S", -52))
        if rng.random() < 0.2:
            tx.append((d, "7-Eleven Torggata", -round(rng.uniform(25, 95), 2)))
        # Transport
        if d.day == 2:
            tx.append((d, "Ruter 30-dagersbillett student", -612))
        if rng.random() < 0.04:
            tx.append((d, "Bolt Operations", -round(rng.uniform(120, 350), 2)))
        # Diverse
        if rng.random() < 0.05:
            tx.append((d, rng.choice(["H&M Oslo City", "Zalando SE", "Cubus Storo"]), -round(rng.uniform(199, 1200), 2)))
        if rng.random() < 0.04:
            tx.append((d, "Vinmonopolet Storo", -round(rng.uniform(250, 700), 2)))
        if rng.random() < 0.03:
            tx.append((d, "Apotek 1 Storo", -round(rng.uniform(60, 320), 2)))
        if rng.random() < 0.03:
            tx.append((d, "Vipps*Ola Nordmann", -round(rng.choice([150, 200, 350, 500]), 2)))
        if rng.random() < 0.02:
            tx.append((d, "Elkjøp Storo", -round(rng.uniform(300, 2500), 2)))
        if rng.random() < 0.02:
            tx.append((d, "Kontantuttak DNB Minibank Storo", -500))
        if d == date(2026, 10, 14):
            tx.append((d, "Purregebyr Fjordkraft", -35))
        if d == date(2026, 8, 2):
            tx.append((d, "Norwegian Air Shuttle", -2340))
        if rng.random() < 0.015:
            tx.append((d, "Ukjent Butikk Nettbutikk 4471", -round(rng.uniform(100, 600), 2)))
    tx.sort(key=lambda x: x[0])
    return tx


def write_dnb(tx, path: Path, start: date, end: date) -> None:
    rows = []
    for d, text, amt in tx:
        if start <= d <= end:
            fmt = lambda v: f"{abs(v):,.2f}".replace(",", " ").replace(".", ",")
            rows.append({"Dato": f"{d:%d.%m.%Y}", "Forklaring": text, "Rentedato": f"{d:%d.%m.%Y}",
                         "Uttak": fmt(amt) if amt < 0 else "", "Innskudd": fmt(amt) if amt > 0 else ""})
    # Nyeste først, som i nettbanken
    pd.DataFrame(rows[::-1]).to_csv(path, sep=";", index=False, encoding="cp1252")


def write_sbanken(tx, path: Path) -> None:
    rows = []
    for d, text, amt in tx:
        if "egen konto" in text:
            rows.append({"BOKFØRINGSDATO": d, "RENTEDATO": d, "ARKIVREFERANSE": random.randint(10**8, 10**9),
                         "TYPE": "Overføring", "TEKST": f"Fra {BRUKSKONTO}", "UT FRA KONTO": None,
                         "INN PÅ KONTO": abs(amt)})
    rows.append({"BOKFØRINGSDATO": date(2026, 11, 1), "RENTEDATO": date(2026, 11, 1), "ARKIVREFERANSE": 1,
                 "TYPE": "Renter", "TEKST": "Renter", "UT FRA KONTO": None, "INN PÅ KONTO": 41.37})
    head = pd.DataFrame([["Sbanken – Sparekonto", "", "", "", "", "", ""],
                         [f"Kontonummer: {SPAREKONTO}", "", "", "", "", "", ""],
                         ["", "", "", "", "", "", ""]])
    body = pd.DataFrame(rows)
    with pd.ExcelWriter(path) as xw:
        head.to_excel(xw, index=False, header=False, startrow=0)
        body.to_excel(xw, index=False, startrow=3)


def write_nordea(rng: random.Random, path: Path) -> None:
    rows = []
    for d in days():
        if rng.random() < 0.3:
            amt = -round(rng.uniform(150, 1100), 2)
            rows.append((d, amt, "REMA 1000 SAGENE" if rng.random() < 0.6 else "COOP MEGA STORO"))
        if d.day == 10:
            rows.append((d, -rng.randint(400, 1100), "FJORDKRAFT AS"))
        if d.day == 21:
            rows.append((d, 34200.0, "LØNN OSLO KOMMUNE"))
        if rng.random() < 0.05:
            rows.append((d, -round(rng.uniform(300, 900), 2), "IKEA FURUSET"))
    # Reservert beløp uten dato (skal hoppes over)
    out = [{"Bokføringsdato": "Reservert", "Beløp": "-89,00", "Avsender": "", "Mottaker": "",
            "Navn": "", "Tittel": "NARVESEN OSLO S", "Valuta": "NOK", "Betalingstype": "Kortkjøp"}]
    for d, amt, title in sorted(rows, reverse=True):
        out.append({"Bokføringsdato": f"{d:%Y/%m/%d}", "Beløp": f"{amt:.2f}".replace(".", ","),
                    "Avsender": "", "Mottaker": "", "Navn": "", "Tittel": title, "Valuta": "NOK",
                    "Betalingstype": "Kortkjøp" if amt < 0 else "Innbetaling"})
    pd.DataFrame(out).to_csv(path, sep=";", index=False, encoding="utf-8")


def main() -> None:
    rng = random.Random(42)
    random.seed(42)
    tx = build_main(rng)
    write_dnb(tx, OUT / "dnb_brukskonto_mai-aug.csv", date(2026, 5, 1), date(2026, 8, 31))
    write_dnb(tx, OUT / "dnb_brukskonto_jul-nov.csv", date(2026, 7, 1), END)
    write_sbanken(tx, OUT / "sbanken_sparekonto.xlsx")
    write_nordea(random.Random(7), OUT / "nordea_partner.csv")
    print(f"Laget eksempelfiler i {OUT} ({len(tx)} transaksjoner på brukskontoen)")


if __name__ == "__main__":
    main()
