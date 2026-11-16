# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Writer for the publicly documented EXTF posting batch format (DACH pack).

"DATEV" names a file format here and nothing else. Header position, field lengths and file
encoding are kept in the constants below; entries marked UNSOURCED are not verified against
the public field list and are configurable per connector (``header_columns``,
``posting_columns``), never enforced.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

from app.modules.finance.booking_export import BookingRow, BookingWriter

# Source: developer.datev.de, format header page: "EXTF";700;21;"Buchungsstapel";<format version>
EXTF_PREFIX = ("EXTF", 700, 21, "Buchungsstapel")
FORMAT_VERSIONS = (12, 13)
DEFAULT_FORMAT_VERSION = 13  # default 13; 12 selectable in the connector settings
LINE_END = "\r\n"  # source: format introduction
DELIMITER = ";"
# UNSOURCED until checked against the field list: header field order after the version,
# maximum lengths and file encoding.
DEFAULT_HEADER_COLUMNS = (
    "advisor",
    "client",
    "fiscal_year_start",
    "account_length",
    "period_from",
    "period_to",
    "name",
)
DEFAULT_POSTING_COLUMNS = (
    "amount",
    "side",
    "currency",
    "account",
    "counter_account",
    "tax_key",
    "date",
    "document",
    "text",
    "cost1",
    "cost2",
)
POSTING_HEADINGS = {
    "amount": "Umsatz",
    "side": "Soll/Haben-Kennzeichen",
    "currency": "WKZ Umsatz",
    "account": "Konto",
    "counter_account": "Gegenkonto",
    "tax_key": "BU-Schluessel",
    "date": "Belegdatum",
    "document": "Belegfeld 1",
    "text": "Buchungstext",
    "cost1": "KOST1",
    "cost2": "KOST2",
}
UNSOURCED_TEXT_LIMIT: int | None = None
ENCODING = "cp1252"  # UNSOURCED


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def header_problems(settings: dict[str, Any]) -> list[str]:
    need = ("advisor", "client", "fiscal_year_start", "account_length")
    return [k for k in need if not str(settings.get(k) or "").strip()]


def fiscal_year_of(start: str, day: date) -> int:
    """Fiscal year number of ``day`` for a year starting on ``start`` (YYYYMMDD)."""
    month, dom = int(start[4:6]), int(start[6:8])
    return day.year if (day.month, day.day) >= (month, dom) else day.year - 1


def _gl_accounts(settings: dict[str, Any]) -> list[str]:
    from app.modules.finance.booking_export import Mapping

    return [v.get("account", "") for v in Mapping.from_settings(settings).accounts.values()]


def _issue(key: str, **details: Any) -> dict[str, Any]:
    return {"rule_id": f"datev.{key}", "severity": "error", "invoice": "", "details": details}


class DatevWriter(BookingWriter):
    connector_type: ClassVar[str] = "datev_extf"
    required_markets: ClassVar[tuple[str, ...]] = ("DE", "AT", "CH")
    rule_prefix: ClassVar[str] = "datev"
    text_limit: ClassVar[int | None] = UNSOURCED_TEXT_LIMIT
    encoding: ClassVar[str] = ENCODING

    @classmethod
    def check_settings(cls, settings: dict[str, Any], period_from: date, period_to: date) -> list[dict[str, Any]]:
        missing = header_problems(settings)
        if missing:
            return [_issue("header_incomplete", fields=missing)]
        found: list[dict[str, Any]] = []
        start = str(settings["fiscal_year_start"])
        if fiscal_year_of(start, period_from) != fiscal_year_of(start, period_to):
            found.append(_issue("period_crosses_fiscal_year"))
        length = int(str(settings["account_length"]))
        found += [_issue("account_length", account=a) for a in _gl_accounts(settings) if len(a) > length]
        return found

    @classmethod
    def render(cls, rows: list[BookingRow], settings: dict[str, Any], period_from: date, period_to: date) -> bytes:
        version = int(settings.get("format_version") or DEFAULT_FORMAT_VERSION)
        if version not in FORMAT_VERSIONS:
            version = DEFAULT_FORMAT_VERSION
        sources = {
            "advisor": str(settings.get("advisor", "")),
            "client": str(settings.get("client", "")),
            "fiscal_year_start": str(settings.get("fiscal_year_start", "")),
            "account_length": str(settings.get("account_length", "")),
            "period_from": period_from.strftime("%Y%m%d"),
            "period_to": period_to.strftime("%Y%m%d"),
            "name": _quote(str(settings.get("batch_name", ""))),
        }
        head_cols = settings.get("header_columns") or DEFAULT_HEADER_COLUMNS
        header = [
            _quote(EXTF_PREFIX[0]),
            str(EXTF_PREFIX[1]),
            str(EXTF_PREFIX[2]),
            _quote(EXTF_PREFIX[3]),
            str(version),
        ]
        header += [sources.get(str(c), "") for c in head_cols]
        cols = [str(c) for c in (settings.get("posting_columns") or DEFAULT_POSTING_COLUMNS)]
        lines = [DELIMITER.join(header), DELIMITER.join(POSTING_HEADINGS.get(c, c) for c in cols)]
        for r in rows:
            values = {
                "amount": f"{r.amount:.2f}".replace(".", ","),
                "side": _quote(r.side),
                "currency": _quote(r.currency),
                "account": r.account,
                "counter_account": r.counter_account,
                "tax_key": _quote(r.tax_key),
                "date": r.date.strftime("%d%m") if r.date else "",
                "document": _quote(r.invoice_number),
                "text": _quote(r.text),
                "cost1": _quote(r.cost1),
                "cost2": _quote(r.cost2),
            }
            lines.append(DELIMITER.join(values.get(c, "") for c in cols))
        encoding = str(settings.get("encoding") or cls.encoding)
        return (LINE_END.join(lines) + LINE_END).encode(encoding, errors="replace")
