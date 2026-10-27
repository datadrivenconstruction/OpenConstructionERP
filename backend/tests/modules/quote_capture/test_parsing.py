# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rules​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ parser on German, English, French and Arabic quotes, Excel and PDF."""

from __future__ import annotations

import io
from datetime import date

from app.modules.quote_capture.documents import read_document, read_text
from app.modules.quote_capture.parsing import detect_notes, parse_quote

DE = """Musterbau Fassaden GmbH
Angebotsdatum: 03.10.2026
Angebot gültig bis 02.11.2026
Pos  Beschreibung                      Menge  Einheit  EP        GP
01   Wärmedämmverbundsystem 160 mm     420,00  m²      68,50     28.770,00
02   Fensterbankabdeckung Aluminium    85,5    lfm     42,00     3.591,00
03   Anschlussprofile Fenster          36      Stk     18,40     662,40
Gerüst ist bauseits zu stellen und nicht im Angebot enthalten.
Zahlungsbedingungen: 30 Tage netto
Lieferzeit: 4 Wochen nach Auftrag
Preise netto zzgl. MwSt 19 %
Angebotssumme netto 33.023,40 EUR
"""

EN = """Northgate Drylining Ltd
Quote date: 2026-10-05
This quotation is valid for 30 days.
1  Metal stud partition 100 mm   250 m2   38.50   9,625.00
2  Plasterboard ceiling           120 sqm  41.25   4,950.00
3  Access panels 600x600          8 ea     95.00   760.00
Excluding scaffolding and out-of-hours working.
Prices subject to a price adjustment clause for steel studs.
Payment terms: 30 days from invoice
Total excl. VAT GBP 15,335.00
"""

FR = """Société Atelier Menuiserie
Date du devis : 07/10/2026
Validité : 60 jours
1  Porte intérieure bois      12  u   385,00   4 620,00
2  Plinthe chêne              140 ml  9,80     1 372,00
Non compris : peinture et mise en teinte.
Montant total HT 5 992,00 €
"""

AR = """المورد: شركة الخليج للمقاولات
التاريخ: 2026-10-08
صالح لمدة 30 يوم
1  بلاط سيراميك للأرضيات   300   م2   ٤٥٫٠٠   ١٣٥٠٠٫٠٠
2  وزرة سيراميك             120   م    ١٢٫٥٠   ١٥٠٠٫٠٠
لا يشمل أعمال العزل المائي
الإجمالي 15000.00 SAR
"""


def _q(text: str, locale: str) -> dict:
    return parse_quote(read_text(text).lines, locale, today=date(2026, 10, 10))


def test_german_quote() -> None:
    q = _q(DE, "de")
    h = {k: v["value"] for k, v in q["header"].items()}
    assert h["supplier"] == "Musterbau Fassaden GmbH"
    assert h["quote_date"] == "2026-10-03"
    assert h["valid_until"] == "2026-11-02"
    assert h["currency"] == "EUR"
    assert h["quote_total"] == "33023.40"
    assert h["tax_rate"] == "19.00"
    assert h["tax_basis"] == "net"
    assert "30 Tage" in h["payment_terms"]
    assert "4 Wochen" in h["delivery"]
    lines = q["lines"]
    assert [ln["unit"] for ln in lines] == ["m2", "lm", "pcs"]
    assert lines[0]["quantity"] == "420.00" and lines[0]["total"] == "28770.00"
    assert lines[1]["quantity"] == "85.50"
    assert all(ln["confidence"] == 0.8 for ln in lines)
    assert all(ln["anchor"]["line"] > 0 for ln in lines)
    assert any(n["kind"] == "exclusion" and "bauseits" in n["text"] for n in q["notes"])


def test_english_quote_with_exclusion_and_escalation() -> None:
    q = _q(EN, "en")
    h = {k: v["value"] for k, v in q["header"].items()}
    assert h["currency"] == "GBP"
    assert h["valid_until"] == "2026-11-04"
    assert h["quote_total"] == "15335.00"
    assert [ln["unit"] for ln in q["lines"]] == ["m2", "m2", "pcs"]
    kinds = {n["kind"] for n in q["notes"]}
    assert {"exclusion", "escalation"} <= kinds
    # "excl. VAT" is tax, not a scope exclusion
    assert not any("VAT" in n["text"] for n in q["notes"] if n["kind"] == "exclusion")


def test_french_quote() -> None:
    q = _q(FR, "fr")
    h = {k: v["value"] for k, v in q["header"].items()}
    assert h["quote_date"] == "2026-10-07"
    assert h["valid_until"] == "2026-12-06"
    assert h["currency"] == "EUR"
    assert h["quote_total"] == "5992.00"
    assert [ln["unit"] for ln in q["lines"]] == ["pcs", "lm"]
    assert q["lines"][1]["total"] == "1372.00"
    assert any(n["kind"] == "exclusion" for n in q["notes"])


def test_arabic_quote() -> None:
    q = _q(AR, "ar")
    h = {k: v["value"] for k, v in q["header"].items()}
    assert h["supplier"] == "شركة الخليج للمقاولات"
    assert h["currency"] == "SAR"
    assert h["quote_total"] == "15000.00"
    assert [ln["unit"] for ln in q["lines"]] == ["m2", "m"]
    assert q["lines"][0]["total"] == "13500.00"
    assert any(n["kind"] == "exclusion" for n in q["notes"])


def test_tax_remark_is_not_an_exclusion() -> None:
    notes = detect_notes(read_text("All prices excl. VAT\nexcl. MwSt.").lines)
    assert notes == []


def test_excel_quote_has_cell_anchors() -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Angebot"
    ws.append(["Anbieter: Musterbau Fassaden GmbH"])
    ws.append(["Pos", "Beschreibung", "Menge", "Einheit", "EP", "GP"])
    ws.append(["1", "Dämmung 160 mm", 420, "m²", 68.5, 28770])
    ws.append(["2", "Fensterbank", 85.5, "lfm", 42, 3591])
    buf = io.BytesIO()
    wb.save(buf)
    doc = read_document(buf.getvalue(), "quote.xlsx")
    assert doc.kind == "xlsx"
    q = parse_quote(doc.lines, "de")
    assert [ln["unit"] for ln in q["lines"]] == ["m2", "lm"]
    first = q["lines"][0]
    assert first["field_anchors"]["unit_rate"]["cell"] == "E3"
    assert first["anchor"]["sheet"] == "Angebot"
    assert first["confidence"] == 0.8


def test_pdf_quote_has_page_and_box() -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    rows = [
        "Northgate Drylining Ltd",
        "Quote date: 2026-10-05",
        "1  Metal stud partition 100 mm   250 m2   38.50   9,625.00",
        "Total GBP 9,625.00",
    ]
    for i, row in enumerate(rows):
        c.drawString(60, 780 - i * 24, row)
    c.save()
    doc = read_document(buf.getvalue(), "quote.pdf")
    assert doc.kind == "pdf" and doc.pages[0]["page"] == 1
    q = parse_quote(doc.lines, "en")
    assert len(q["lines"]) == 1
    anchor = q["lines"][0]["anchor"]
    assert anchor["page"] == 1
    x0, y0, x1, y1 = anchor["bbox"]
    assert 0 < x0 < x1 and 0 < y0 < y1 < doc.pages[0]["height"]


def test_email_quote() -> None:
    raw = (
        b"From: offers@example.test\r\nSubject: Quote screed\r\nDate: Mon, 5 Oct 2026 10:00:00 +0000\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Floor screed 60 mm   300 m2   21.00   6,300.00\r\nTotal 6,300.00 EUR\r\n"
    )
    doc = read_document(raw, "offer.eml")
    assert doc.kind == "email"
    q = parse_quote(doc.lines, "en")
    assert q["lines"][0]["total"] == "6300.00"
