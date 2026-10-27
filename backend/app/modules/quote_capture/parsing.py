# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rules-only​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ quote parser: header, line items and flagged conditions.

This is the parser that always runs. With no AI provider configured it is the
whole extraction; with one, the model's answer is merged over it (see
:mod:`app.modules.quote_capture.extraction`). Labels are matched in the platform's
main quote languages (English, German, French, Spanish, Italian, Dutch, Arabic,
Russian); values are read with the locale-aware number parser, so a line priced
``1.234,50`` and one priced ``1,234.50`` read the same.

Confidence here is deliberately modest (at most 0.8): a rule found the value, a
human still has to look at it.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.modules.quote_capture.documents import DocLine
from app.modules.quote_capture.numbers import looks_numeric, parse_number, plain
from app.modules.quote_capture.units import is_known_unit, normalise_unit

_CURRENCY_SIGNS = {"€": "EUR", "$": "USD", "£": "GBP", "¥": "JPY", "₹": "INR", "₽": "RUB", "zł": "PLN", "₺": "TRY"}
_CURRENCY_WORDS = {"ر.س": "SAR", "د.إ": "AED", "ريال": "SAR", "درهم": "AED", "fr.": "CHF", "sfr": "CHF"}
_ISO = re.compile(r"\b(EUR|USD|GBP|CHF|AED|SAR|QAR|KWD|OMR|BHD|EGP|PLN|CZK|SEK|NOK|DKK|HUF|RON|BGN|TRY|INR|CNY|JPY|"
                  r"KRW|AUD|NZD|CAD|SGD|ZAR|BRL|MXN|RUB|UAH|KZT|IDR|MYR|THB|VND|PHP|NGN|KES|MAD|TND)\b")  # fmt: skip

_L = {
    "supplier": r"(supplier|vendor|from|company|lieferant|anbieter|firma|von|fournisseur|soci[ée]t[ée]|proveedor|"
    r"fornitore|leverancier|المورد|الشركة|من|поставщик)",
    "date": r"(date|datum|fecha|data|التاريخ|дата|quote date|angebotsdatum|date du devis)",
    "validity": r"(valid|validity|g[üu]ltig|bindefrist|validit[ée]|valable|validez|v[áa]lid[oa]|geldig|صالح|"
    r"صلاحية|действител)",
    "payment": r"(payment|zahlung|zahlungsbedingung|paiement|r[èe]glement|pago|pagamento|betaling|الدفع|السداد|оплат)",
    "delivery": r"(delivery|lead time|lieferung|lieferzeit|livraison|d[ée]lai|entrega|consegna|levering|التسليم|"
    r"التوريد|поставк|срок)",
    "total": r"(grand total|total amount|total|summe|gesamt|gesamtbetrag|endbetrag|angebotssumme|montant total|"
    r"total g[ée]n[ée]ral|importe total|totale|totaal|الإجمالي|المجموع|итого|всего)",
    "subtotal": r"(sub-?total|zwischensumme|nettosumme|sous-total|subtotal|المجموع الفرعي)",
    "tax": r"(vat|gst|hst|sales tax|mwst|ust|tva|iva|btw|ضريبة القيمة المضافة|ضريبة|ндс)",
    "gross": r"(gross|brutto|ttc|incl\.? (vat|tax|mwst)|inkl\.? mwst|شامل الضريبة|с ндс)",
    "net": r"(net|netto|\bht\b|hors taxes?|excl\.? (vat|tax|mwst)|zzgl\.? mwst|exkl\.? mwst|غير شامل الضريبة|без ндс)",
}
_RE = {k: re.compile(v, re.IGNORECASE) for k, v in _L.items()}

_NOTE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "exclusion",
        re.compile(
            r"(\bexcl\.?\b|\bexcluding\b|\bexclusive of\b|\bnot included\b|\bexcluded\b|\bby others\b|"
            r"\bausgenommen\b|\bnicht enthalten\b|\bnicht im (angebot|preis)\b|\bexkl\.?\b|\bohne\b|bauseits|"
            r"\bnon compris\b|\bnon inclus\b|\bhors\b|\bexclu|\bà l'exclusion\b|\bno incluid|\bexcluid|"
            r"\besclus|\bniet inbegrepen\b|غير شامل|لا يشمل|باستثناء|مستثنى|не включ|исключ)",
            re.IGNORECASE,
        ),
    ),
    (
        "escalation",
        re.compile(
            r"(escalation|price adjustment|price variation|indexation|index-linked|preisgleit|lohngleit|"
            r"materialpreisgleit|r[ée]vision de prix|actualisation|revisi[óo]n de precios|revisione prezzi|"
            r"تعديل الأسعار|تصعيد الأسعار|индексац)",
            re.IGNORECASE,
        ),
    ),
    (
        "qualification",
        re.compile(
            r"(\bsubject to\b|\bassum(es|ing|ption)\b|\bprovided that\b|\bconditional\b|vorbehaltlich|"
            r"\bunter der voraussetzung\b|\bsous r[ée]serve\b|\bà condition\b|\bsujeto a\b|\bsalvo\b|"
            r"\bsoggett[oa] a\b|بشرط|مع مراعاة|при условии)",
            re.IGNORECASE,
        ),
    ),
]
_TAX_WORD = re.compile(r"(vat|gst|mwst|ust\b|tva|iva|btw|tax|steuer|ضريبة|ндс)", re.IGNORECASE)
_ORDINAL = re.compile(r"^(pos\.?\s*)?\d{1,4}([.\-/]\d{1,4}){0,4}\.?\s+", re.IGNORECASE)
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DATE_DMY = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})\b")
_DAYS = re.compile(r"(\d{1,3})\s*(days?|tage[n]?|jours?|d[íi]as|giorni|dagen|يوم|أيام|дн)", re.IGNORECASE)
_PERCENT = re.compile(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%")


def field(value: Any, confidence: float, anchor: dict | None, source: str = "rules") -> dict[str, Any]:
    """One extracted value with its confidence, source anchor and the machine's own reading."""
    return {
        "value": value,
        "confidence": round(float(confidence), 2),
        "anchor": anchor,
        "machine_value": value,
        "source": source,
    }


def detect_currency(text: str) -> str | None:
    m = _ISO.search(text)
    if m:
        return m.group(1)
    for sign, code in {**_CURRENCY_WORDS, **_CURRENCY_SIGNS}.items():
        if sign in text:
            return code
    return None


def parse_date(text: str) -> date | None:
    m = _DATE_ISO.search(text)
    try:
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _DATE_DMY.search(text)
        if m:
            year = int(m.group(3))
            year += 2000 if year < 100 else 0
            day, month = int(m.group(1)), int(m.group(2))
            if month > 12 >= day:  # US order (MM/DD)
                day, month = month, day
            return date(year, month, day)
    except ValueError:
        return None
    return None


def _value_after_label(text: str, label: re.Pattern[str]) -> str:
    m = label.search(text)
    if not m:
        return ""
    rest = text[m.end() :]
    return rest.lstrip(" :.-\t").strip()


_AMOUNT = re.compile(r"\(?-?\d{1,3}(?:[ \u00a0\u202f'\u2019]\d{3})+(?:[.,]\d+)?\)?|\(?-?\d[\d.,'\u2019]*\)?")


def _amount_on(line: DocLine, locale: str | None) -> Decimal | None:
    """The last amount printed on a line; space-grouped amounts (``5 992,00``) stay whole."""
    text = line.text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")).replace("٫", ".").replace("٬", ",")
    for m in reversed(list(_AMOUNT.finditer(text))):
        tail = text[m.end() : m.end() + 2]
        if "%" in tail:
            continue
        value = parse_number(m.group(0), locale)
        if value is not None:
            return value
    return None


_SPACED_AMOUNT = re.compile(r"^-?\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?$")


def _is_currency_token(token: str) -> bool:
    t = token.strip()
    return bool(_ISO.fullmatch(t)) or t in _CURRENCY_SIGNS or t in _CURRENCY_WORDS


def _tokens(line: DocLine, locale: str | None = None) -> list[str]:
    cells = [c for c in line.cells if c]
    if len(cells) >= 3:
        out: list[str] = []
        for cell in cells:
            # A cell holding "12,5 m2" or "38.50 9,625.00" splits; "4 620,00" is one amount.
            parts = [p for p in cell.split() if not _is_currency_token(p)]
            if _SPACED_AMOUNT.match(cell.strip()) or len(parts) < 2:
                out.append(" ".join(parts) or cell)
            elif all(looks_numeric(p) or is_known_unit(p, locale) for p in parts):
                out.extend(parts)
            else:
                out.append(cell)
        return [t for t in out if not _is_currency_token(t)]
    return [t for t in line.text.split() if not _is_currency_token(t)]


def parse_line_item(line: DocLine, locale: str | None) -> dict[str, Any] | None:
    """Read one line as ``description qty unit rate [total]`` (or ``unit qty``); None if it is not one."""
    tokens = _tokens(line, locale)
    if len(tokens) < 4:
        return None
    nums: list[Decimal] = []
    i = len(tokens) - 1
    while i >= 0 and looks_numeric(tokens[i]) and len(nums) < 3:
        value = parse_number(tokens[i], locale)
        if value is None:
            break
        nums.insert(0, value)
        i -= 1
    unit_raw = ""
    qty: Decimal | None = None
    if len(nums) == 3:  # qty rate total, unit before qty
        qty, rate, total = nums
        if i >= 0 and is_known_unit(tokens[i], locale):
            unit_raw = tokens[i]
            i -= 1
    elif len(nums) in (1, 2) and i >= 1 and is_known_unit(tokens[i], locale) and looks_numeric(tokens[i - 1]):
        unit_raw = tokens[i]
        qty = parse_number(tokens[i - 1], locale)
        rate, total = (nums[0], nums[1]) if len(nums) == 2 else (nums[0], None)
        i -= 2
    else:
        return None
    if qty is None or not unit_raw:
        return None
    description = " ".join(tokens[: i + 1]).strip()
    description = _ORDINAL.sub("", description).strip(" -:")
    if not description or not re.search(r"[^\W\d_]", description):
        return None
    if _RE["total"].match(description) or _RE["subtotal"].match(description):
        return None
    computed = qty * rate
    if total is None:
        confidence, total = 0.55, computed
    elif abs(computed - total) <= max(Decimal("0.02"), abs(total) * Decimal("0.0005")):
        confidence = 0.8
    else:
        confidence = 0.45
    return {
        "description": description,
        "quantity": plain(qty),
        "unit_raw": unit_raw,
        "unit": normalise_unit(unit_raw, locale),
        "unit_rate": plain(rate),
        "total": plain(total),
        "confidence": confidence,
        "anchor": line.anchor,
    }


def _xlsx_columns(lines: list[DocLine]) -> tuple[int, dict[str, int]] | None:
    """Find a spreadsheet header row and map description, quantity, unit, rate and total columns."""
    names = {
        "description": r"(description|item|text|bezeichnung|beschreibung|kurztext|leistung|d[ée]signation|libell[ée]|"
        r"descripci[óo]n|descrizione|omschrijving|الوصف|البند|наименование)",
        "quantity": r"(qty|quantity|menge|quantit[ée]|cantidad|quantit[àa]|hoeveelheid|الكمية|кол)",
        "unit": r"(unit|uom|einheit|me|unit[ée]|unidad|unit[àa]|eenheid|الوحدة|ед)",
        "unit_rate": r"(rate|unit price|price|ep|einheitspreis|prix unitaire|p\.?u\.?|precio|prezzo|eenheidsprijs|"
        r"سعر الوحدة|السعر|цена)",
        "total": r"(total|amount|gp|gesamtpreis|betrag|montant|importe|importo|bedrag|الإجمالي|المبلغ|сумма)",
    }
    compiled = {k: re.compile(rf"^\s*{v}\b", re.IGNORECASE) for k, v in names.items()}
    for idx, line in enumerate(lines[:40]):
        cols: dict[str, int] = {}
        for c_idx, cell in enumerate(line.cells):
            for key, rx in compiled.items():
                if key not in cols and cell and rx.search(cell):
                    cols[key] = c_idx
                    break
        if {"description", "quantity", "unit_rate"} <= cols.keys():
            return idx, cols
    return None


def _parse_xlsx_items(lines: list[DocLine], locale: str | None) -> list[dict[str, Any]] | None:
    found = _xlsx_columns(lines)
    if found is None:
        return None
    start, cols = found
    items: list[dict[str, Any]] = []
    for line in lines[start + 1 :]:
        cells = line.cells

        def cell(key: str, cells: list[str] = cells) -> str:
            pos = cols.get(key)
            return cells[pos] if pos is not None and pos < len(cells) else ""

        desc = cell("description")
        qty = parse_number(cell("quantity"), locale)
        rate = parse_number(cell("unit_rate"), locale)
        if not desc or qty is None or rate is None:
            continue
        total = parse_number(cell("total"), locale)
        computed = qty * rate
        if total is None:
            conf, total = 0.6, computed
        else:
            conf = 0.8 if abs(computed - total) <= Decimal("0.02") else 0.45
        unit_raw = cell("unit")
        anchors = {
            k: {**line.anchor, "cell": line.anchor.get("cells", {}).get(_col(cols[k]))} for k in cols if k in cols
        }
        items.append(
            {
                "description": desc,
                "quantity": plain(qty),
                "unit_raw": unit_raw,
                "unit": normalise_unit(unit_raw, locale),
                "unit_rate": plain(rate),
                "total": plain(total),
                "confidence": conf,
                "anchor": line.anchor,
                "field_anchors": anchors,
            }
        )
    return items


def _col(index: int) -> str:
    from app.modules.quote_capture.documents import _col_letter

    return _col_letter(index)


def detect_notes(lines: list[DocLine]) -> list[dict[str, Any]]:
    """Flag exclusions, qualifications and escalation clauses; 'excl. VAT' is tax, not scope."""
    notes: list[dict[str, Any]] = []
    for line in lines:
        text = line.text
        for kind, rx in _NOTE_PATTERNS:
            m = rx.search(text)
            if not m:
                continue
            if kind == "exclusion" and _TAX_WORD.search(text[m.end() : m.end() + 24]):
                continue
            notes.append(
                {"kind": kind, "text": text[:500], "confidence": 0.7, "anchor": line.anchor, "source": "rules"}
            )
            break
    return notes


def parse_header(lines: list[DocLine], locale: str | None, *, today: date | None = None) -> dict[str, dict]:
    """Supplier, date, validity, currency, payment terms, delivery, totals, tax basis."""
    header: dict[str, dict] = {}
    text = "\n".join(line.text for line in lines)
    currency = detect_currency(text)
    if currency:
        first = next((ln for ln in lines if detect_currency(ln.text) == currency), None)
        header["currency"] = field(currency, 0.7, first.anchor if first else None)
    for line in lines[:60]:
        t = line.text
        if "supplier" not in header and _RE["supplier"].match(t):
            value = _value_after_label(t, _RE["supplier"])
            if value:
                header["supplier"] = field(value[:255], 0.6, line.anchor)
        if "quote_date" not in header and _RE["date"].search(t) and not _RE["validity"].search(t):
            d = parse_date(t)
            if d:
                header["quote_date"] = field(d.isoformat(), 0.7, line.anchor)
        if "payment_terms" not in header and _RE["payment"].search(t):
            value = _value_after_label(t, _RE["payment"]) or t
            header["payment_terms"] = field(value[:255], 0.6, line.anchor)
        if "delivery" not in header and _RE["delivery"].search(t):
            value = _value_after_label(t, _RE["delivery"]) or t
            header["delivery"] = field(value[:255], 0.55, line.anchor)
    if "supplier" not in header:
        first = next((ln for ln in lines[:8] if re.search(r"[^\W\d_]{3,}", ln.text) and len(ln.text) < 80), None)
        if first:
            header["supplier"] = field(first.text.split("  ")[0][:255], 0.35, first.anchor)
    for line in lines:
        t = line.text
        if _RE["validity"].search(t):
            d = parse_date(t)
            days = _DAYS.search(t)
            base = (
                date.fromisoformat(header["quote_date"]["value"]) if "quote_date" in header else (today or date.today())
            )
            if d:
                header["valid_until"] = field(d.isoformat(), 0.7, line.anchor)
            elif days:
                header["valid_until"] = field((base + timedelta(days=int(days.group(1)))).isoformat(), 0.6, line.anchor)
            if "valid_until" in header:
                break
    for line in reversed(lines):
        t = line.text
        if "quote_total" not in header and _RE["total"].search(t) and not _RE["subtotal"].search(t):
            amount = _amount_on(line, locale)
            if amount is not None:
                header["quote_total"] = field(plain(amount), 0.65, line.anchor)
        if "tax_rate" not in header and _RE["tax"].search(t):
            m = _PERCENT.search(t)
            if m:
                header["tax_rate"] = field(plain(parse_number(m.group(1), locale)), 0.65, line.anchor)
    basis = "net"
    for line in lines:
        if _RE["gross"].search(line.text):
            basis = "gross"
            header["tax_basis"] = field("gross", 0.55, line.anchor)
            break
        if _RE["net"].search(line.text):
            header["tax_basis"] = field("net", 0.6, line.anchor)
            break
    header.setdefault("tax_basis", field(basis, 0.3, None))
    return header


def parse_quote(lines: list[DocLine], locale: str | None, *, today: date | None = None) -> dict[str, Any]:
    """Run the whole rules pass: ``{"header": ..., "lines": [...], "notes": [...]}``."""
    items = _parse_xlsx_items(lines, locale) if lines and "sheet" in lines[0].anchor else None
    if items is None:
        items = [item for line in lines if (item := parse_line_item(line, locale)) is not None]
    return {"header": parse_header(lines, locale, today=today), "lines": items, "notes": detect_notes(lines)}
