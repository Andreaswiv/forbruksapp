"""Innlesing av kontoutskrifter fra norske banker (CSV og Excel).

Håndterer semikolon/komma/tab, desimalkomma, tusenskille, dd.mm.yyyy,
UTF-8 og Windows-1252, innledende rader før overskriften, og enten én
beløpskolonne eller separate kolonner for inn og ut.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

# Kolonnenavn vi kjenner igjen (små bokstaver). Rekkefølgen er prioritet.
DATE_NAMES = ["dato", "bokføringsdato", "bokført dato", "bokført", "transaksjonsdato",
              "utført dato", "kjøpsdato", "date", "booking date", "transaction date"]
TEXT_NAMES = ["forklaring", "beskrivelse", "tekst", "transaksjonstekst", "tittel",
              "spesifikasjon", "melding", "navn", "mottaker", "description", "text"]
AMOUNT_NAMES = ["beløp", "belop", "beløp i nok", "beløp nok", "amount", "sum"]
OUT_NAMES = ["ut fra konto", "ut av konto", "uttak", "ut", "debet", "belastet", "utgående"]
IN_NAMES = ["inn på konto", "innskudd", "inn", "kredit", "godskrevet", "inngående"]

ENCODINGS = ["utf-8-sig", "cp1252", "latin-1"]


class NeedMapping(Exception):
    """Kolonnene kunne ikke gjenkjennes. Brukeren må velge selv."""

    def __init__(self, columns: list[str], preview: pd.DataFrame, signature: str):
        super().__init__("Kunne ikke gjenkjenne kolonnene automatisk")
        self.columns = columns
        self.preview = preview
        self.signature = signature


@dataclass
class ParseResult:
    df: pd.DataFrame                     # kolonner: date (ISO-str), text, amount (float)
    mapping: dict
    signature: str
    skipped_rows: int = 0
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- tall og datoer
_NUM_CLEAN = re.compile(r"[^\d,.\-+()]")


def parse_amount(value) -> float | None:
    """'1 234,50' → 1234.5, '-1.234,50' → -1234.5, '1,234.50' → 1234.5, '(50)' → -50."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if pd.isna(value) else float(value)
    s = str(value).strip().replace("−", "-").replace(" ", "").replace(" ", "")
    if not s or s in {"-", "--"}:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.endswith("-"):                      # «123,00-»
        negative, s = True, s[:-1]
    s = _NUM_CLEAN.sub("", s).replace("(", "").replace(")", "")
    if s.startswith("-"):
        negative, s = True, s[1:]
    s = s.lstrip("+")
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):      # 1.234,50
            s = s.replace(".", "").replace(",", ".")
        else:                                # 1,234.50
            s = s.replace(",", "")
    elif "," in s:
        if s.count(",") > 1:                 # 1,234,567
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif "." in s and re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")               # 1.234 = tusen
    try:
        num = float(s)
    except ValueError:
        return None
    return -num if negative else num


_DATE_FORMATS = ["%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y.%m.%d",
                 "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%y", "%Y/%m/%d"]


def parse_date(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- filinnlesing
def _decode(raw: bytes) -> tuple[str, str]:
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace"), "latin-1"


def _detect_sep(text: str) -> str:
    sample = "\n".join(text.splitlines()[:30])
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        counts = {sep: sample.count(sep) for sep in [";", "\t", ","]}
        return max(counts, key=counts.get)


def _norm(col) -> str:
    return " ".join(str(col).strip().strip('"').lower().split())


def _header_score(values) -> int:
    known = set(DATE_NAMES + TEXT_NAMES + AMOUNT_NAMES + OUT_NAMES + IN_NAMES)
    return sum(1 for v in values if _norm(v) in known)


def _promote_header(raw: pd.DataFrame) -> pd.DataFrame:
    """Finn overskriftsraden (banker legger ofte inn kontonavn o.l. øverst)."""
    best_row, best_score = None, 0
    for i in range(min(15, len(raw))):
        score = _header_score(raw.iloc[i].tolist())
        if score > best_score:
            best_row, best_score = i, score
    if best_row is None or best_score < 2:
        best_row = 0
    header = [str(c).strip() if not pd.isna(c) and str(c).strip() else f"Kolonne {j + 1}"
              for j, c in enumerate(raw.iloc[best_row].tolist())]
    # Unike kolonnenavn
    seen: dict[str, int] = {}
    for j, h in enumerate(header):
        if h in seen:
            seen[h] += 1
            header[j] = f"{h} ({seen[h]})"
        else:
            seen[h] = 0
    body = raw.iloc[best_row + 1:].reset_index(drop=True)
    body.columns = header
    body = body.dropna(how="all")
    return body


def read_table(raw: bytes, filename: str) -> tuple[pd.DataFrame, list[str]]:
    """Leser fil til en tabell med strenger/rå verdier og riktig overskrift."""
    warnings: list[str] = []
    is_excel = raw[:4] == b"PK\x03\x04" or filename.lower().endswith((".xlsx", ".xlsm", ".xls"))
    if is_excel:
        engine = None if raw[:4] == b"PK\x03\x04" else "xlrd"
        try:
            table = pd.read_excel(io.BytesIO(raw), header=None, dtype=object, engine=engine)
        except ImportError:
            raise ValueError("Gamle .xls-filer støttes ikke. Lagre filen som .xlsx eller .csv.")
    else:
        text, enc = _decode(raw)
        if enc != "utf-8-sig":
            warnings.append(f"Filen var lagret som {enc}, konvertert til UTF-8.")
        sep = _detect_sep(text)
        table = pd.read_csv(io.StringIO(text), sep=sep, header=None, dtype=str,
                            keep_default_na=False, engine="python", on_bad_lines="skip",
                            quotechar='"')
        table = table.replace("", None)
    return _promote_header(table), warnings


def columns_signature(columns) -> str:
    return "|".join(_norm(c) for c in columns)


def _find(cols_norm: dict[str, str], names: list[str], exclude: set[str]) -> str | None:
    for n in names:
        for orig, norm in cols_norm.items():
            if norm == n and orig not in exclude:
                return orig
    return None


def guess_mapping(columns: list[str]) -> dict | None:
    cols_norm = {c: _norm(c) for c in columns}
    used: set[str] = set()
    m: dict[str, str | None] = {}
    m["date"] = _find(cols_norm, DATE_NAMES, used)
    if m["date"]:
        used.add(m["date"])
    m["text"] = _find(cols_norm, TEXT_NAMES, used)
    if m["text"]:
        used.add(m["text"])
    m["amount"] = _find(cols_norm, AMOUNT_NAMES, used)
    m["out"] = m["in"] = None
    if not m["amount"]:
        m["out"] = _find(cols_norm, OUT_NAMES, used)
        m["in"] = _find(cols_norm, IN_NAMES, used | {m["out"]})
    has_amount = bool(m["amount"]) or bool(m["out"] or m["in"])
    if not (m["date"] and m["text"] and has_amount):
        return None
    return m


def apply_mapping(table: pd.DataFrame, mapping: dict) -> tuple[pd.DataFrame, int]:
    dates = table[mapping["date"]].map(parse_date)
    texts = table[mapping["text"]].fillna("").astype(str).str.strip()
    if mapping.get("amount"):
        amounts = table[mapping["amount"]].map(parse_amount)
    else:
        out = table[mapping["out"]].map(parse_amount) if mapping.get("out") else None
        inn = table[mapping["in"]].map(parse_amount) if mapping.get("in") else None
        vals = []
        for i in range(len(table)):
            o = out.iloc[i] if out is not None else None
            n = inn.iloc[i] if inn is not None else None
            if o is not None and not pd.isna(o) and o != 0:
                vals.append(-abs(o))         # ut er alltid negativt
            elif n is not None and not pd.isna(n) and n != 0:
                vals.append(abs(n))
            else:
                vals.append(None)
        amounts = pd.Series(vals, index=table.index, dtype=object)
    out_df = pd.DataFrame({"date": dates, "text": texts, "amount": amounts})
    valid = out_df["date"].notna() & out_df["amount"].notna()
    skipped = int((~valid).sum())
    out_df = out_df[valid].copy()
    out_df["amount"] = out_df["amount"].astype(float)
    # Fyll tom tekst så vi har noe å kategorisere på
    out_df.loc[out_df["text"] == "", "text"] = "(uten tekst)"
    return out_df.reset_index(drop=True), skipped


def parse_file(raw: bytes, filename: str, saved_mapping: dict | None = None,
               manual_mapping: dict | None = None) -> ParseResult:
    table, warnings = read_table(raw, filename)
    signature = columns_signature(table.columns)
    mapping = manual_mapping or saved_mapping or guess_mapping(list(table.columns))
    if not mapping:
        raise NeedMapping(list(table.columns), table.head(8), signature)
    missing = [v for v in mapping.values() if v and v not in table.columns]
    if missing:
        raise NeedMapping(list(table.columns), table.head(8), signature)
    df, skipped = apply_mapping(table, mapping)
    if skipped:
        warnings.append(f"{skipped} rader manglet gyldig dato eller beløp og ble hoppet over "
                        "(f.eks. reserverte beløp eller summeringslinjer).")
    if df.empty:
        warnings.append("Fant ingen gyldige transaksjoner med dette kolonneoppsettet.")
    return ParseResult(df=df, mapping=mapping, signature=signature,
                       skipped_rows=skipped, warnings=warnings)
