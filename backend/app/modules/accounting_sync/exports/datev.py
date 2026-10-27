# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DATEV​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ EXTF export: Buchungsstapel and Debitoren/Kreditoren Stammdaten.

The layout (format version, categories, column order, encoding) is data in
``country_data/accounting_charts.json`` under ``file_formats.datev_extf``; the
account numbers and BU keys come from the connection's mapping, seeded from the
SKR03 or SKR04 template. One posting line per document line: ``Konto`` is the
debtor or creditor, ``Gegenkonto`` the revenue or cost account, the BU key
carries the tax, and ``KOST1`` the project cost centre.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.modules.accounting_sync.postings import Mapping, SyncContact, SyncDocument, money
from app.modules.accounting_sync.templates import file_format


def _text(value: str, limit: int) -> str:
    clean = (value or "").replace('"', "'").replace("\r", " ").replace("\n", " ")
    return f'"{clean[:limit]}"'


def _amount(value: Decimal) -> str:
    return f"{money(value):.2f}".replace(".", ",")


def _header(fmt: dict[str, Any], kind: dict[str, Any], settings: dict[str, Any], extra: list[str]) -> list[str]:
    created = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")[:17]
    return [
        '"EXTF"',
        str(fmt["format_version"]),
        str(kind["category"]),
        f'"{kind["name"]}"',
        str(kind["version"]),
        created,
        "",
        '"OE"',
        '""',
        '""',
        str(settings.get("consultant_number") or ""),
        str(settings.get("client_number") or ""),
        *extra,
    ]


def _write(rows: list[list[str]], fmt: dict[str, Any]) -> bytes:
    terminator = fmt["line_terminator"]
    text = terminator.join(fmt["delimiter"].join(r) for r in rows) + terminator
    return text.encode(fmt["encoding"], errors="replace")


def buchungsstapel(
    docs: list[SyncDocument],
    mapping: Mapping,
    accounts: dict[str, int],
    *,
    settings: dict[str, Any],
    period: tuple[date, date],
    skr: str,
    currency: str = "EUR",
) -> bytes:
    """Encode a DATEV EXTF Buchungsstapel (category 21)."""
    fmt = file_format("datev_extf")
    kind = fmt["buchungsstapel"]
    columns: list[str] = kind["columns"]
    fy_start = settings.get("fiscal_year_start") or f"{period[0].year}0101"
    header = _header(
        fmt,
        kind,
        settings,
        [
            str(fy_start).replace("-", ""),
            str(settings.get("account_length") or 4),
            period[0].strftime("%Y%m%d"),
            period[1].strftime("%Y%m%d"),
            _text(settings.get("batch_label") or "OpenConstructionERP", 30),
            '""',
            "1",
            "0",
            "0",
            f'"{currency}"',
            "",
            '""',
            "",
            "",
            f'"{skr}"',
            "",
            "",
            '""',
            '""',
        ],
    )
    rows = [header, list(columns)]
    idx = {name: i for i, name in enumerate(columns)}
    for doc in sorted(docs, key=lambda d: (d.doc_date, d.number)):
        personal = accounts.get(f"{doc.contact.kind}:{doc.contact.record_id}")
        for ln in doc.lines:
            row = [""] * len(columns)
            gross = money(ln.net) + doc.line_tax(ln)
            counter, _name = mapping.account(ln.category)
            row[idx["Umsatz (ohne Soll/Haben-Kz)"]] = _amount(gross)
            row[idx["Soll/Haben-Kennzeichen"]] = '"S"' if doc.is_sales else '"H"'
            row[idx["WKZ Umsatz"]] = f'"{doc.currency}"'
            row[idx["Konto"]] = str(personal or "")
            row[idx["Gegenkonto (ohne BU-Schlüssel)"]] = counter
            row[idx["BU-Schlüssel"]] = _text(mapping.tax_key(ln.tax_code, doc.tax_direction) or "", 4)
            row[idx["Belegdatum"]] = doc.doc_date.strftime("%d%m")
            row[idx["Belegfeld 1"]] = _text(doc.number, 36)
            row[idx["Belegfeld 2"]] = _text(doc.due_date.strftime("%d%m%y") if doc.due_date else "", 12)
            row[idx["Buchungstext"]] = _text(ln.description or doc.contact.name, 60)
            row[idx["KOST1 - Kostenstelle"]] = _text(doc.project_code, 36)
            row[idx["Festschreibung"]] = "0"
            rows.append(row)
    return _write(rows, fmt)


def stammdaten(contacts: list[SyncContact], accounts: dict[str, int], *, settings: dict[str, Any]) -> bytes:
    """Encode DATEV EXTF Debitoren/Kreditoren master data (category 16)."""
    fmt = file_format("datev_extf")
    kind = fmt["stammdaten"]
    columns: list[str] = kind["columns"]
    idx = {name: i for i, name in enumerate(columns)}
    rows = [_header(fmt, kind, settings, [str(date.today().year) + "0101", str(settings.get("account_length") or 4)])]
    rows.append(list(columns))
    seen: set[str] = set()
    for c in sorted(contacts, key=lambda c: accounts.get(f"{c.kind}:{c.record_id}", 0)):
        key = f"{c.kind}:{c.record_id}"
        if key in seen or key not in accounts:
            continue
        seen.add(key)
        row = [""] * len(columns)
        row[idx["Konto"]] = str(accounts[key])
        row[idx["Name (Adressattyp Unternehmen)"]] = _text(c.name, 50)
        row[idx["Adressattyp"]] = '"2"' if c.is_business else '"1"'
        row[idx["Kurzbezeichnung"]] = _text(c.name, 15)
        if c.tax_id[:2].isalpha():
            row[idx["EU-Land"]] = _text(c.tax_id[:2].upper(), 2)
            row[idx["EU-UStID"]] = _text(c.tax_id[2:], 13)
        row[idx["Land"]] = _text(c.country_code, 2)
        row[idx["E-Mail"]] = _text(c.email, 60)
        rows.append(row)
    return _write(rows, fmt)
