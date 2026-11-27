"""Månedsrapport som PDF (lagres lokalt)."""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate,  # noqa: E402
                                Spacer, Table, TableStyle)

from . import analysis, config  # noqa: E402

BLUE = colors.HexColor("#2563eb")
GREY = colors.HexColor("#6b7280")
LIGHT = colors.HexColor("#f3f4f6")


def kr(x: float) -> str:
    return f"{x:,.0f} kr".replace(",", " ")


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("H1x", parent=ss["Heading1"], fontSize=20, textColor=BLUE, spaceAfter=4))
    ss.add(ParagraphStyle("H2x", parent=ss["Heading2"], fontSize=13, spaceBefore=12, spaceAfter=6))
    ss.add(ParagraphStyle("Small", parent=ss["Normal"], fontSize=8, textColor=GREY))
    ss.add(ParagraphStyle("Body", parent=ss["Normal"], fontSize=9.5, leading=13))
    return ss


def _table(data, col_widths, header=True, align_right_from=1):
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (align_right_from, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    return t


def _bar_chart(series: pd.Series, title: str) -> Image:
    s = series.sort_values()
    fig, ax = plt.subplots(figsize=(7, max(2.2, 0.32 * len(s) + 0.8)), dpi=150)
    ax.barh(s.index, s.values, color="#2563eb", height=0.6)
    for i, v in enumerate(s.values):
        ax.text(v, i, f"  {v:,.0f}".replace(",", " "), va="center", fontsize=7.5, color="#374151")
    ax.set_title(title, fontsize=10, loc="left")
    ax.spines[["top", "right", "bottom"]].set_visible(False)
    ax.tick_params(axis="both", labelsize=8)
    ax.xaxis.set_visible(False)
    ax.set_xlim(0, s.max() * 1.22 if len(s) and s.max() > 0 else 1)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    w = 17 * cm
    return Image(buf, width=w, height=w * fig.get_figheight() / fig.get_figwidth())


def build(df: pd.DataFrame, period: str, *, subs=None, budget: pd.DataFrame | None = None,
          sifo_cmp: pd.DataFrame | None = None, findings=None, variant: str = "meg",
          shared: dict | None = None, partner_name: str = "Partner", my_name: str = "Meg",
          out_dir: Path | None = None) -> Path:
    ss = _styles()
    out_dir = Path(out_dir) if out_dir else config.REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    pt = analysis.period_table(df)
    label = pt.loc[pt["period"] == period, "period_label"].iloc[0]
    cols = pt["period"].tolist()
    prev = cols[cols.index(period) - 1] if cols.index(period) > 0 else None
    summary = analysis.period_summary(df).set_index("period")
    cur = summary.loc[period]

    story = [Paragraph(f"Forbruksrapport – {label}", ss["H1x"]),
             Paragraph(f"Laget {datetime.now():%d.%m.%Y}. "
                       f"{'Felles økonomi' if variant == 'felles' else 'Personlig rapport'}. "
                       "Generert lokalt på din maskin.", ss["Small"]),
             Spacer(1, 10)]

    # Nøkkeltall
    def delta(col):
        if prev is None:
            return ""
        d = cur[col] - summary.loc[prev, col]
        return f"{'+' if d >= 0 else '−'}{kr(abs(d))}"

    kt = [["", "Denne perioden", "Endring fra forrige"],
          ["Inn", kr(cur["Inn"]), delta("Inn")],
          ["Forbruk", kr(cur["Forbruk"]), delta("Forbruk")],
          ["Sparing", kr(cur["Sparing"]), delta("Sparing")],
          ["Netto (inn − forbruk − sparing)", kr(cur["Netto"]), delta("Netto")]]
    if cur["Inn"] > 0:
        kt.append(["Sparerate", f"{(cur['Sparing'] + max(cur['Netto'], 0)) / cur['Inn'] * 100:.0f} %", ""])
    story += [Paragraph("Nøkkeltall", ss["H2x"]), _table(kt, [7 * cm, 4.5 * cm, 4.5 * cm])]

    # Kategorier
    piv = analysis.by_category(df)
    if not piv.empty and period in piv.columns:
        curcat = piv[period][piv[period] > 0]
        if not curcat.empty:
            story += [Paragraph("Forbruk per kategori", ss["H2x"]), _bar_chart(curcat, f"Forbruk {label} (kr)")]
            bud = dict(zip(budget["category"], budget["amount"])) if budget is not None and not budget.empty else {}
            rows = [["Kategori", "Denne", "Forrige", "Budsjett", "Avvik budsjett"]]
            for cat, v in curcat.sort_values(ascending=False).items():
                pv = piv[prev][cat] if prev and prev in piv.columns else None
                b = bud.get(cat)
                rows.append([cat, kr(v), kr(pv) if pv is not None else "–", kr(b) if b else "–",
                             (f"{'+' if v - b >= 0 else '−'}{kr(abs(v - b))}") if b else "–"])
            story.append(_table(rows, [5.5 * cm, 2.8 * cm, 2.8 * cm, 2.8 * cm, 3.1 * cm]))

    # SIFO
    if sifo_cmp is not None and not sifo_cmp.empty:
        rows = [["SIFO-post", "Mitt snitt", "SIFO", "Differanse"]]
        for r in sifo_cmp.itertuples():
            rows.append([r.Kategori, kr(r.Mitt_snitt), kr(r.SIFO),
                         f"{'+' if r.Differanse >= 0 else '−'}{kr(abs(r.Differanse))}"])
        story += [Paragraph("Sammenlignet med SIFO-referansebudsjettet", ss["H2x"]),
                  _table(rows, [6 * cm, 3.5 * cm, 3.5 * cm, 4 * cm])]

    # Abonnementer
    if subs:
        active = [s for s in subs if s.active]
        if active:
            rows = [["Abonnement / fast trekk", "Intervall", "Per måned", "Per år", "Merknad"]]
            for s in active[:20]:
                note = []
                if s.price_change and s.price_change > 0:
                    note.append(f"Pris opp {kr(s.price_change)}")
                if s.overlap_group:
                    note.append(s.overlap_group)
                rows.append([s.name, s.interval, kr(s.monthly), kr(s.yearly), Paragraph(", ".join(note), ss["Small"])])
            tot = sum(s.monthly for s in active)
            rows.append(["Sum", "", kr(tot), kr(tot * 12), ""])
            story += [Paragraph("Abonnementer og faste trekk", ss["H2x"]),
                      _table(rows, [5 * cm, 2.4 * cm, 2.6 * cm, 2.6 * cm, 4.4 * cm])]

    # Avvik
    an = analysis.anomalies(df, period)
    if an:
        rows = [["Kategori", "Denne perioden", "Vanlig nivå", "Endring"]]
        for a in an[:8]:
            rows.append([a.category, kr(a.current), kr(a.baseline), f"{a.pct:+.0f} %"])
        story += [Paragraph("Største avvik fra vanlig nivå", ss["H2x"]),
                  _table(rows, [6 * cm, 3.5 * cm, 3.5 * cm, 4 * cm])]

    # Anbefalinger
    if findings:
        story.append(Paragraph("Viktigste anbefalinger", ss["H2x"]))
        for f in findings[:6]:
            block = [Paragraph(f"<b>{f.title}</b> – mulig besparelse {kr(f.saving_monthly)}/mnd "
                               f"({kr(f.saving_yearly)}/år)", ss["Body"]),
                     Paragraph(f.detail, ss["Body"]),
                     Paragraph(f"<i>{f.recommendation}</i>", ss["Body"]), Spacer(1, 6)]
            story.append(KeepTogether(block))

    # Felles økonomi
    if variant == "felles" and shared:
        story.append(Paragraph("Felles økonomi", ss["H2x"]))
        rows = [["", my_name, partner_name, "Totalt"],
                ["Betalt av felles utgifter", kr(shared["betalt_meg"]), kr(shared["betalt_partner"]), kr(shared["total"])],
                ["Andel som skal betales", kr(shared["min_andel"]), kr(shared["partner_andel"]), kr(shared["total"])]]
        story.append(_table(rows, [6 * cm, 3.6 * cm, 3.6 * cm, 3.8 * cm]))
        owe = shared["jeg_skylder"]
        if abs(owe) < 1:
            txt = "Dere er skuls denne perioden."
        elif owe > 0:
            txt = f"<b>{my_name} skylder {partner_name} {kr(owe)}</b>."
        else:
            txt = f"<b>{partner_name} skylder {my_name} {kr(-owe)}</b>."
        story += [Spacer(1, 6), Paragraph(txt, ss["Body"])]
        pc = shared["per_kategori"]
        if not pc.empty:
            rows = [["Kategori", my_name, partner_name]]
            for cat, r in pc.iterrows():
                rows.append([cat, kr(r.get("meg", 0)), kr(r.get("partner", 0))])
            story += [Spacer(1, 6), _table(rows, [7 * cm, 5 * cm, 5 * cm])]

    story += [Spacer(1, 14), Paragraph(
        "SIFO-sammenligningen bygger på satsene i data/sifo_satser.json. Sjekk at de er oppdatert "
        "med offisielle tall fra OsloMet.", ss["Small"])]

    fname = f"forbruksrapport_{period}_{variant}.pdf"
    path = out_dir / fname
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                            title=f"Forbruksrapport {label}", author="Forbruksapp")
    doc.build(story)
    return path
