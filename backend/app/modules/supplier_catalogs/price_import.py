# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Reading a vendor price list file (Excel, CSV, SAP condition export) into rows.

The file reading (encoding, delimiter, xlsx sheets, zip guard) and the number
parsing (decimal comma or point, grouping) come from the cost-data importer in
``app.modules.costs.pricelists``; this module only adds the column mapping and
the presets an estimator picks from.

A mapping is ``{field: column header}``. Fields:

    vendor_sku, mpn, gtin, sku      - how a row finds its catalog item
    unit_price                      - list (gross) price, required
    price_unit                      - "per" quantity, the price is for this many units (SAP KPEIN)
    currency, valid_from, valid_to  - per row, else the price list's own
    min_order_qty, lead_time_days, unit, name, notes
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.modules.boq.units import is_registry_unit
from app.modules.costs.pricelists.base import BrokenNumber, NumberConvention, parse_amount
from app.modules.costs.pricelists.containers import ContainerRefused, Member
from app.modules.costs.pricelists.tabular import iter_tables, normalise_header

MAX_ROWS = 50_000
PREVIEW_ROWS = 200
MATCH_KEYS = ("vendor_sku", "mpn", "gtin", "sku")
FIELDS = (
    "vendor_sku",
    "mpn",
    "gtin",
    "sku",
    "unit_price",
    "price_unit",
    "currency",
    "valid_from",
    "valid_to",
    "min_order_qty",
    "lead_time_days",
    "unit",
    "discount_pct",
    "name",
    "notes",
)

# Spellings vendors and SAP exports use for units the platform registry lacks.
_EXTRA_UNITS = frozenset(
    {
        "st",
        "stk",
        "stck",
        "stueck",
        "stuck",
        "pc",
        "pce",
        "pcs",
        "pak",
        "pkg",
        "pack",
        "set",
        "rol",
        "roll",
        "bdl",
        "bag",
        "sack",
        "sak",
    }
)

# Header spellings each preset recognises, compared after normalise_header().
PRESETS: dict[str, dict[str, tuple[str, ...]]] = {
    "generic": {
        "vendor_sku": ("vendor sku", "article", "article no", "art nr", "artikelnummer", "item no", "supplier sku"),
        "mpn": ("mpn", "manufacturer part number", "herstellernummer", "part number"),
        "gtin": ("gtin", "ean", "ean code", "upc", "barcode"),
        "sku": ("sku", "our sku", "internal sku"),
        "unit_price": ("unit price", "price", "list price", "listenpreis", "preis", "gross price", "rrp"),
        "price_unit": ("per", "price unit", "preiseinheit", "pe"),
        "currency": ("currency", "waehrung", "wahrung", "cur"),
        "valid_from": ("valid from", "gueltig ab", "gultig ab", "from"),
        "valid_to": ("valid to", "valid until", "gueltig bis", "gultig bis", "to"),
        "min_order_qty": ("moq", "min order qty", "minimum order", "mindestmenge"),
        "lead_time_days": ("lead time", "lead time days", "lieferzeit"),
        "unit": ("unit", "uom", "einheit", "me"),
        "discount_pct": ("discount", "discount pct", "discount %", "rabatt", "rabatt %", "disc"),
        "name": ("name", "description", "bezeichnung", "text"),
        "notes": ("notes", "remark", "bemerkung"),
    },
    # A typical condition record export (table KONP/A-tables via SE16, ALV list to Excel):
    # MATNR material, KBETR condition amount, KPEIN per, KMEIN unit, KONWA currency, DATAB/DATBI validity.
    "sap_condition": {
        "vendor_sku": ("matnr", "material", "material number", "materialnummer", "idnlf", "vendor material number"),
        "mpn": ("mfrpn", "manufacturer part no", "herstellerteilenummer"),
        "gtin": ("ean11", "ean upc", "ean"),
        "unit_price": ("kbetr", "amount", "condition amount", "konditionsbetrag", "betrag", "rate"),
        "price_unit": ("kpein", "pricing unit", "per", "preiseinheit", "konditionspreiseinheit"),
        "currency": ("konwa", "waers", "currency", "rate unit", "waehrung", "wahrung"),
        "valid_from": ("datab", "valid from", "gueltig ab", "gultig ab"),
        "valid_to": ("datbi", "valid to", "gueltig bis", "gultig bis"),
        "unit": ("kmein", "meins", "unit of measure", "uom", "mengeneinheit"),
        "name": ("maktx", "material description", "materialkurztext", "short text"),
    },
}


class ImportFileError(ValueError):
    """The upload cannot be read as a table; ``code`` names why."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class ParsedRow:
    """One data row after mapping, before matching."""

    row: int
    values: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class ParsedTable:
    headers: list[str]
    sample: list[list[str]]
    rows: list[ParsedRow]
    sheet: str


def _member(name: str, raw: bytes) -> Member:
    return Member(name=name or "upload.csv", size=len(raw), opener=lambda: io.BytesIO(raw))


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime | date):
        return value.isoformat()[:10]
    return str(value).strip()


def _first_table(name: str, raw: bytes) -> tuple[str, list[list[Any]]]:
    try:
        for title, rows in iter_tables(_member(name, raw)):
            out: list[list[Any]] = []
            for row in rows:
                if any(_text(c) for c in row):
                    out.append(list(row))
                if len(out) > MAX_ROWS:
                    raise ImportFileError("too_many_rows")
            if out:
                return title, out
    except ContainerRefused as exc:
        raise ImportFileError(getattr(exc, "code", "unreadable")) from exc
    except (ValueError, KeyError, OSError) as exc:
        if isinstance(exc, ImportFileError):
            raise
        raise ImportFileError("unreadable") from exc
    raise ImportFileError("empty")


def suggest_mapping(headers: list[str], preset: str = "generic") -> dict[str, str]:
    """Guess ``{field: header}`` from the header row using a preset's spellings."""
    spellings = PRESETS.get(preset) or PRESETS["generic"]
    normalised = {normalise_header(h): h for h in headers if h}
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for fld, names in spellings.items():
        for n in names:
            header = normalised.get(n)
            if header and header not in used:
                mapping[fld] = header
                used.add(header)
                break
    return mapping


def detect_preset(headers: list[str]) -> str:
    """``sap_condition`` when the header row carries SAP field names, else ``generic``."""
    norm = {normalise_header(h) for h in headers}
    return "sap_condition" if {"kbetr", "matnr"} <= norm or {"kbetr", "kpein"} <= norm else "generic"


_DMY = re.compile(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})$")
_YMD8 = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def _fold_unit(unit: str) -> str:
    return unit.strip().casefold().replace("ü", "ue").replace(".", "")


def parse_day(value: Any) -> str | None:
    """ISO date from a cell: a date, ``2026-01-31``, ``31.01.2026`` or SAP ``20260131``."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime | date):
        return value.isoformat()[:10]
    text = _text(value)
    if text in {"99991231", "31.12.9999", "9999-12-31"}:
        return None  # SAP's "open end"
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        pass
    for rx, order in ((_DMY, "dmy"), (_YMD8, "ymd")):
        m = rx.match(text)
        if m:
            a, b, c = (int(x) for x in m.groups())
            try:
                d = date(c, b, a) if order == "dmy" else date(a, b, c)
            except ValueError:
                return "invalid"
            return d.isoformat()
    return "invalid"


def read_table(
    name: str, raw: bytes, mapping: dict[str, str] | None, preset: str | None
) -> tuple[ParsedTable, dict[str, str], str]:
    """Read the upload, settle the mapping and turn every data row into a :class:`ParsedRow`.

    Returns the table, the mapping actually used and the preset name.
    """
    sheet, rows = _first_table(name, raw)
    headers = [_text(c) for c in rows[0]]
    preset_name = preset if preset in PRESETS else detect_preset(headers)
    used = {k: v for k, v in (mapping or {}).items() if k in FIELDS and v in headers} or suggest_mapping(
        headers, preset_name
    )
    index = {fld: headers.index(h) for fld, h in used.items()}
    body = rows[1:]
    convention = NumberConvention()
    for r in body[:2000]:
        for fld in ("unit_price", "price_unit", "min_order_qty", "discount_pct"):
            if fld in index and index[fld] < len(r):
                convention.observe(r[index[fld]])
    parsed: list[ParsedRow] = []
    for offset, r in enumerate(body, start=2):
        pr = ParsedRow(row=offset)

        def cell(fld: str, r: list[Any] = r) -> Any:
            i = index.get(fld)
            return r[i] if i is not None and i < len(r) else None

        for key in ("vendor_sku", "mpn", "gtin", "sku", "currency", "unit", "name", "notes"):
            v = _text(cell(key))
            if v:
                pr.values[key] = v[:500]
        for key in ("unit_price", "price_unit", "min_order_qty", "lead_time_days", "discount_pct"):
            raw_v = cell(key)
            try:
                num = parse_amount(raw_v, convention=convention)
            except BrokenNumber:
                pr.errors.append(f"bad_number:{key}")
                continue
            if num is not None:
                pr.values[key] = num
        for key in ("valid_from", "valid_to"):
            d = parse_day(cell(key))
            if d == "invalid":
                pr.errors.append(f"bad_date:{key}")
            elif d:
                pr.values[key] = d
        unit = pr.values.get("unit")
        if unit and not (is_registry_unit(unit) or _fold_unit(unit) in _EXTRA_UNITS):
            pr.errors.append("unknown_unit")
        pct = pr.values.get("discount_pct")
        if pct is not None and not (Decimal(0) <= pct <= Decimal(100)):
            pr.errors.append("discount_out_of_range")
        price = pr.values.get("unit_price")
        per = pr.values.pop("price_unit", None)
        if price is None:
            pr.errors.append("missing_price")
        elif price < 0:
            pr.errors.append("negative_price")
        elif per is not None:
            if per <= 0:
                pr.errors.append("bad_number:price_unit")
            else:
                pr.values["unit_price"] = (price / per).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if not any(pr.values.get(k) for k in MATCH_KEYS):
            pr.errors.append("missing_key")
        parsed.append(pr)
    sample = [[_text(c) for c in r] for r in body[:5]]
    return ParsedTable(headers=headers, sample=sample, rows=parsed, sheet=sheet), used, preset_name


def iter_keys(values: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """``(match key, normalised value)`` pairs of a row in match order."""
    for key in MATCH_KEYS:
        v = values.get(key)
        if v:
            yield key, str(v).strip().upper()
