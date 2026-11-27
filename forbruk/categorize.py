"""Kategorisering med regler, butikknøkler og gjenkjenning av overføringer mellom egne kontoer.

Regelsyntaks (små/store bokstaver spiller ingen rolle):
  rema 1000     – må stå som eget ord/uttrykk i teksten
  lønn*         – stjerne på slutten = alt som begynner med «lønn» (lønnsinnbetaling …)
  re:^giro \\d+  – regulært uttrykk
Regler med fortegn gjelder bare for inn (+) eller ut (-).
Prioritet: dine egne regler > godkjente AI-forslag > innebygde regler > generelle regler (Vipps o.l.).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

import pandas as pd

from . import db

# ---------------------------------------------------------------- kategorier
EXPENSE_CATEGORIES = [
    "Dagligvarer", "Restaurant og takeaway", "Transport", "Bil", "Abonnementer", "Bolig",
    "Lån", "Klær og sko", "Personlig pleie", "Helse", "Elektronikk", "Alkohol", "Fritid",
    "Reise", "Husholdning", "Barn", "Gaver", "Vipps", "Kontantuttak", "Gebyrer og renter",
    "Annet", "Ukategorisert",
]
INCOME_CATEGORIES = ["Lønn", "Inntekt annet"]
SPECIAL_CATEGORIES = ["Sparing", "Overføring"]
ALL_CATEGORIES = EXPENSE_CATEGORIES + INCOME_CATEGORIES + SPECIAL_CATEGORIES

# Kategorier som ikke er forbruk
NON_SPEND = set(INCOME_CATEGORIES) | set(SPECIAL_CATEGORIES)

PRIORITY = {"user": 300, "ai": 200, "default": 100, "generic": 50}

# (mønster, kategori, fortegn) – fortegn: None = begge, "+" = inn, "-" = ut
_D: list[tuple[str, str, str | None]] = []


def _add(category: str, patterns: str, sign: str | None = None) -> None:
    for p in patterns.split(","):
        p = p.strip()
        if p:
            _D.append((p, category, sign))


_add("Dagligvarer", "rema 1000, rema, kiwi, extra, coop, coop extra, coop mega, coop prix, coop obs, "
     "obs, mega, prix, meny, spar, eurospar, joker, bunnpris, oda, kolonial.no, matkroken, "
     "nærbutikken, holdbart, fudi, mat.se, safari, gigaboks")
_add("Restaurant og takeaway", "foodora, wolt, just eat, justeat, mcdonalds, mcdonald's, mcd, "
     "burger king, max burgers, peppes, dolly dimples, egon, starbucks, espresso house, "
     "kaffebrenneriet, joe & the juice, joe and the juice, 7-eleven, 7 eleven, narvesen, "
     "deli de luca, baker brun, godt brød, w.b. samson, wb samson, pizzabakeren, domino's, "
     "dominos, subway, kfc, taco bell, sushi*, pizza*, kebab*, restaurant*, cafe*, kafé*, "
     "kaffe*, bar, pub, grill*, burger*, thai*, too good to go")
_add("Transport", "ruter, vy, skyss, atb, kolumbus, brakar, akt, flytoget, bolt, uber, taxi*, "
     "oslo taxi, norgestaxi, voi, tier, ryde, bysykkel*, entur")
_add("Bil", "circle k, shell, esso, uno-x, uno x, yx, st1, best stasjon, fjellinjen, autopass, "
     "bompeng*, bomring*, easypark, apcoa, onepark, europark, aimo, parkering*, mekonomen, "
     "biltema, bilverksted*, dekkhotell*, tesla, ionity, recharge, mer norway, fortum charge, "
     "statens vegvesen, trafikkforsikring*")
_add("Abonnementer", "netflix, spotify, hbo, max, viaplay, disney, disney plus, disneyplus, "
     "tv 2 play, tv2 play, tv 2, prime video, amazon prime, apple.com, apple.com/bill, itunes, "
     "icloud, google one, google storage, youtube premium, youtube, google *youtube, storytel, "
     "bookbeat, audible, nextory, tidal, dropbox, microsoft*, office 365, chatgpt, openai, "
     "anthropic, claude.ai, adobe, patreon, playstation plus, xbox game pass, nintendo online, "
     "skyshowtime, discovery+, strim, allente, telia, telenor, ice, talkmore, chilimobil, onecall, "
     "mycall, happybytes, sats, evo, fresh fitness, 3t, elixia, actic, spenst, family sports club, "
     "impulse, aftenposten, vg+, dagbladet, schibsted, amedia, linkedin premium, duolingo")
_add("Bolig", "husleie, leie*, felleskostnader, felleskost*, obos, usbl, boligbyggelag, sameie*, "
     "borettslag, tibber, fjordkraft, fortum, hafslund, elvia, lyse, ishavskraft, motkraft, "
     "norgesenergi, nettleie, altibox, get, globalconnect, nextgentel, gjensidige, if skadeforsikring, "
     "if forsikring, tryg, fremtind, storebrand forsikring, codan, frende, eika forsikring, "
     "verisure, sector alarm, kommunale avgifter, eiendomsskatt, strøm*, renovasjon*")
_add("Lån", "avdrag*, termin*, boliglån*, studielån, lånekassen, billån*, forbrukslån*", "-")
_add("Klær og sko", "h&m, hm, zara, cubus, dressmann, carlings, bik bok, kappahl, lindex, vero moda, "
     "jack & jones, skoringen, eurosko, din sko, zalando, boozt, nelly, weekday, monki, arket, cos, "
     "uniqlo, mango, follestad, ferner jacobsen, urban outfitters, asos, shein, nike, adidas")
_add("Personlig pleie", "vita, kicks, normal, lyko, blivakker, cocopanda, frisør*, cutters, "
     "barber*, neglesalong*, hudpleie*")
_add("Helse", "apotek 1, apotek1, vitusapotek, vitus apotek, boots, apotek*, legevakt*, lege*, "
     "legesenter*, tannlege*, tannklinikk*, fysioterapi*, kiropraktor*, helfo, dr.dropin, "
     "dr dropin, specsavers, synsam, brilleland, interoptik, psykolog*")
_add("Elektronikk", "elkjøp, elkjop, power, komplett, netonnet, proshop, apple store, "
     "kjell & company, kjell and company, dustin, multicom")
_add("Alkohol", "vinmonopolet, polet")
_add("Fritid", "xxl, stadium, sport 1, sport1, g-sport, gsport, intersport, kino*, nordisk film, "
     "odeon, ticketmaster, billettservice, tikkio, steam, playstation store, bokhandel*, ark, "
     "norli, adlibris, tanum, outland, bowling*, skisenter*, alpinanlegg*, golf*, padel*, "
     "klatre*, svømmehall*, museum*")
_add("Reise", "sas, norwegian, wideroe, widerøe, flyr, booking.com, hotels.com, airbnb, hotel*, "
     "hotell*, scandic, thon, nordic choice, strawberry, clarion, quality hotel, comfort hotel, "
     "ving, tui, apollo, momondo, expedia, color line, fjord line, hurtigruten, ryanair, "
     "easyjet, flytaxi*, avinor")
_add("Husholdning", "ikea, jysk, clas ohlson, europris, nille, rusta, jula, obs bygg, maxbo, "
     "byggmakker, montér, monter, kid interiør, princess, tilbords, kitchn, bohus, skeidar, "
     "plantasjen, hageland, bauhaus, megaflis, jernia, søstrene grene, flying tiger")
_add("Barn", "barnehage*, sfo, aks, babyshop, jollyroom, babyland, br-leker, br leker, "
     "lekia, ringo")
_add("Sparing", "sparing, sparekonto*, bsu, aksjesparekonto, fondssparing, nordnet, firi, kron, "
     "spareavtale*, fond*, dnb spar*", "-")
_add("Gebyrer og renter", "gebyr*, årsavgift*, purring*, purregebyr*, inkasso*, renter, "
     "rente*, termingebyr*, omkostning*, kortavgift*, lindorff, intrum, kredinor, sergel, svea, "
     "lowell, overtrekk*, forsinkelsesrente*", "-")
_add("Kontantuttak", "minibank*, kontantuttak*, atm, kontanter, uttak minibank")
_add("Lønn", "lønn*, lonn*, feriepenger*", "+")
_add("Inntekt annet", "nav, skatteetaten, skatt tilbake*, lånekassen, stipend*, utbytte*", "+")
_add("Gaver", "interflora, gave*")

DEFAULT_RULES = _D

# Generelle regler: brukes bare når ingen mer spesifikk regel treffer
GENERIC_RULES: list[tuple[str, str, str | None]] = [
    ("vipps*", "Vipps", None),
    ("vipps", "Vipps", None),
    ("mobilepay*", "Vipps", None),
]

# Tekst som tyder sterkt på overføring mellom egne kontoer
TRANSFER_PATTERNS = ["overføring mellom egne kontoer", "egen konto", "egne kontoer",
                     "fra egen konto", "til egen konto", "overført til sparekonto",
                     "overføring egen konto", "nettbank til:", "nettbank fra:"]


# ---------------------------------------------------------------- mønstermatching
_WORD = "a-z0-9æøåäöéü"


@lru_cache(maxsize=4096)
def compile_pattern(pattern: str) -> re.Pattern:
    p = pattern.strip().lower()
    if p.startswith("re:"):
        return re.compile(p[3:])
    prefix = p.endswith("*")
    core = re.escape(p.rstrip("*"))
    end = "" if prefix else f"(?![{_WORD}])"
    return re.compile(f"(?<![{_WORD}]){core}{end}")


@dataclass(frozen=True)
class Rule:
    pattern: str
    category: str
    sign: str | None
    source: str

    @property
    def priority(self) -> int:
        return PRIORITY[self.source]


def all_rules(conn) -> list[Rule]:
    rules = [Rule(p, c, s, "default") for p, c, s in DEFAULT_RULES]
    rules += [Rule(p, c, s, "generic") for p, c, s in GENERIC_RULES]
    for r in conn.execute("SELECT pattern, category, source FROM rules"):
        rules.append(Rule(r["pattern"], r["category"], None, r["source"]))
    return rules


def match_category(text: str, amount: float, rules: list[Rule]) -> str | None:
    t = db.normalize_text(text)
    best: Rule | None = None
    for r in rules:
        if r.sign == "+" and amount < 0 or r.sign == "-" and amount > 0:
            continue
        try:
            if not compile_pattern(r.pattern).search(t):
                continue
        except re.error:
            continue
        if best is None or (r.priority, len(r.pattern)) > (best.priority, len(best.pattern)):
            best = r
    return best.category if best else None


def categorize(text: str, amount: float, rules: list[Rule]) -> str:
    cat = match_category(text, amount, rules)
    if cat:
        return cat
    return "Inntekt annet" if amount > 0 else "Ukategorisert"


# ---------------------------------------------------------------- butikknøkkel
_CLEANERS = [
    r"kurs:?\s*[\d.,]+",
    r"\b(nok|sek|eur|usd|dkk|gbp)\s*[\d.,]+",
    r"[\d.,]+\s*(nok|sek|eur|usd|dkk|gbp)\b",
    r"\*\d{4}\b",
    r"\b\d{1,2}\.\d{1,2}(\.\d{2,4})?\b",
    r"\b(visa|mastercard|maestro)\s*\d*",
    r"\bnotanr\.?\s*\S+",
    r"\b(varekjøp|varekjop|kortkjøp|kortkjop|betaling|debit|reservert|transaksjon|dato|"
    r"bet\.|betal\.|til:|fra:|kjøp|kjop|nettgiro|efaktura|e-faktura|avtalegiro|giro)\b",
    r"\b\d{5,}\b",
    r"\b(?=[a-z]*\d)(?=\d*[a-z])[a-z0-9]{6,}\b",   # referansekoder som p1a2b3c4
    r"https?://|www\.",
    r"\.(com|no|se|dk|net|org|io)\b",
]
_CLEAN_RE = [re.compile(c) for c in _CLEANERS]


def merchant_key(text: str) -> str:
    t = db.normalize_text(text)
    for rx in _CLEAN_RE:
        t = rx.sub(" ", t)
    t = re.sub(r"[^a-z0-9æøåäöéü&+' ]", " ", t)
    words = [w for w in t.split() if w not in {"as", "asa", "ab", "ltd", "inc", "no", "nor", "oslo", "com", "bill", "www", "nok"}]
    if not words:
        return db.normalize_text(text)[:30] or "ukjent"
    n = 3 if words[0] in {"vipps", "mobilepay"} else 2
    return " ".join(words[:n])


def merchant_label(key: str) -> str:
    return " ".join(w.capitalize() if not w.isdigit() else w for w in key.split())


# ---------------------------------------------------------------- regelhåndtering
def add_rule(conn, pattern: str, category: str, source: str = "user") -> None:
    pattern = pattern.strip().lower()
    if not pattern:
        raise ValueError("Mønsteret kan ikke være tomt")
    compile_pattern(pattern)   # feiler ved ugyldig regex
    with db.tx(conn):
        conn.execute(
            "INSERT INTO rules(pattern, category, source, created_at) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(pattern, source) DO UPDATE SET category = excluded.category",
            (pattern, category, source, datetime.now().isoformat(timespec="seconds")),
        )


def delete_rule(conn, rule_id: int) -> None:
    with db.tx(conn):
        conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))


def list_user_rules(conn) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT id, pattern AS mønster, category AS kategori, source AS kilde, created_at AS opprettet "
        "FROM rules ORDER BY created_at DESC", conn)


def list_default_rules() -> pd.DataFrame:
    rows = [(p, c, {"+": "kun inn", "-": "kun ut"}.get(s, "")) for p, c, s in DEFAULT_RULES + GENERIC_RULES]
    return pd.DataFrame(rows, columns=["mønster", "kategori", "gjelder"])


# ---------------------------------------------------------------- kjør kategorisering
def recategorize_all(conn) -> int:
    """Kategoriserer alle transaksjoner som ikke er satt manuelt. Returnerer antall endret."""
    rules = all_rules(conn)
    rows = conn.execute(
        "SELECT id, text, amount, category, is_transfer FROM transactions WHERE category_source != 'manual'"
    ).fetchall()
    changed = 0
    with db.tx(conn):
        for r in rows:
            cat = "Overføring" if r["is_transfer"] else categorize(r["text"], r["amount"], rules)
            if cat != r["category"]:
                conn.execute("UPDATE transactions SET category = ?, category_source = 'rule' WHERE id = ?",
                             (cat, r["id"]))
                changed += 1
    return changed


def set_manual_category(conn, tx_id: int, category: str) -> None:
    db.update_transaction(conn, tx_id, category=category, category_source="manual")


def detect_transfers(conn, max_days: int = 3) -> int:
    """Markerer overføringer mellom egne kontoer.

    1) Tekst som tydelig sier «egen konto» o.l.
    2) Teksten inneholder kontonummeret til en av dine egne kontoer.
    3) Par: samme beløp ut fra én av dine kontoer og inn på en annen av dine kontoer
       innen `max_days` dager (kontoene må ha samme eier).
    Transaksjoner du har satt manuelt, røres ikke.
    """
    df = pd.read_sql_query(
        """SELECT t.id, t.account_id, t.date, t.text, t.amount, t.is_transfer, t.transfer_manual,
                  a.owner FROM transactions t JOIN accounts a ON a.id = t.account_id""", conn)
    if df.empty:
        return 0
    df["date"] = pd.to_datetime(df["date"])
    auto = df[df["transfer_manual"] == 0]
    own_numbers = [re.sub(r"\D", "", n or "") for (n,) in
                   conn.execute("SELECT account_number FROM accounts").fetchall()]
    own_numbers = [n for n in own_numbers if len(n) >= 8]

    flagged: set[int] = set()
    for r in auto.itertuples():
        t = db.normalize_text(r.text)
        if any(p in t for p in TRANSFER_PATTERNS):
            flagged.add(r.id)
            continue
        digits = re.sub(r"\D", "", r.text)
        if own_numbers and any(n in digits for n in own_numbers):
            flagged.add(r.id)

    # Parvis matching mellom kontoer
    if df["account_id"].nunique() > 1:
        cents = (df["amount"].abs() * 100).round().astype(int)
        work = df.assign(cents=cents)
        outs = work[(work["amount"] < 0) & (work["transfer_manual"] == 0)]
        ins = work[(work["amount"] > 0) & (work["transfer_manual"] == 0)]
        used_in: set[int] = set()
        ins_by_cents = {c: g for c, g in ins.groupby("cents")}
        for o in outs.sort_values("date").itertuples():
            cand = ins_by_cents.get(o.cents)
            if cand is None:
                continue
            cand = cand[(cand["account_id"] != o.account_id) & (cand["owner"] == o.owner)
                        & ((cand["date"] - o.date).abs().dt.days <= max_days)
                        & (~cand["id"].isin(used_in))]
            if cand.empty:
                continue
            best = cand.iloc[(cand["date"] - o.date).abs().argsort()].iloc[0]
            used_in.add(int(best["id"]))
            flagged.update({int(o.id), int(best["id"])})

    changed = 0
    with db.tx(conn):
        for r in auto.itertuples():
            new = 1 if r.id in flagged else 0
            if new != r.is_transfer:
                conn.execute("UPDATE transactions SET is_transfer = ? WHERE id = ?", (new, r.id))
                changed += 1
    return changed


def refresh(conn) -> None:
    """Kjør etter import eller når regler/kontoer endres."""
    detect_transfers(conn)
    recategorize_all(conn)
