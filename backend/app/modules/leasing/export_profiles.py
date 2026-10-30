# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data-only lease export profiles (``core/country_data/lease_export_profiles.json``).

A profile is a CSV column map over the enriched lease row: the lease fields plus the
tenant's name and identifier, Hijri dates, annual rent and payment counts. A profile
prepares an upload file for a national lease registry; it does not talk to one.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.modules.leasing.schedule import FREQUENCY_MONTHS

logger = logging.getLogger(__name__)

_DATA = Path(__file__).resolve().parents[2] / "core" / "country_data" / "lease_export_profiles.json"
_PERSON_SCHEMES = ("national_id",)


@lru_cache(maxsize=1)
def load_profiles() -> dict[str, dict[str, Any]]:
    """Profiles shipped as data, by lower-case name."""
    try:
        raw = json.loads(_DATA.read_text(encoding="utf-8")).get("profiles") or {}
    except (OSError, ValueError):
        logger.warning("lease export profiles unreadable", exc_info=True)
        return {}
    return {str(k).lower(): v for k, v in raw.items() if isinstance(v, dict) and v.get("columns")}


def to_hijri(iso: str | None) -> str:
    """ISO Gregorian date as ``YYYY-MM-DD`` Umm al-Qura Hijri, or empty when out of range."""
    if not iso:
        return ""
    try:
        from hijridate import Gregorian  # type: ignore[import]

        d = date.fromisoformat(iso)
        h = Gregorian(d.year, d.month, d.day).to_hijri()
    except (ImportError, ValueError, OverflowError):
        return ""
    return f"{h.year:04d}-{h.month:02d}-{h.day:02d}"


def enrich_row(row: dict[str, Any], tenant: dict[str, Any] | None) -> dict[str, Any]:
    """Add the derived fields every profile may read."""
    out = dict(row)
    tenant = tenant or {}
    idents = tenant.get("identifiers") or []
    person = next((i for i in idents if i.get("scheme") in _PERSON_SCHEMES), None)
    chosen = person or (idents[0] if idents else None)
    out["tenant_name"] = tenant.get("name", "")
    out["tenant_phone"] = tenant.get("phone", "")
    out["tenant_kind"] = "individual" if person or not tenant.get("is_company") else "establishment"
    out["tenant_id_scheme"] = (chosen or {}).get("scheme", "")
    out["tenant_id_number"] = (chosen or {}).get("value", "")
    out["start_date_hijri"] = to_hijri(row.get("start_date"))
    out["end_date_hijri"] = to_hijri(row.get("end_date"))
    step = FREQUENCY_MONTHS.get(str(row.get("frequency") or ""), 0)
    per_year = 12 // step if step else 0
    out["payments_per_year"] = per_year
    term = int(row.get("term_months") or 0)
    out["payments_count"] = -(-term // step) if step and term else 0
    try:
        out["annual_rent"] = format(Decimal(str(row.get("rent_amount") or "0")) * per_year, "f")
    except InvalidOperation:
        out["annual_rent"] = ""
    out["contract_type"] = (
        "residential" if (row.get("ext_refs") or {}).get("use", "residential") == "residential" else "commercial"
    )
    try:
        out["vat_rate_percent"] = format(Decimal(str(row.get("tax_rate") or "0")).normalize(), "f")
    except InvalidOperation:
        out["vat_rate_percent"] = ""
    return out


def render_csv(profile: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[bytes, str, str]:
    """One CSV in the profile's column order; UTF-8 with BOM so spreadsheet tools read Arabic."""
    columns = [(str(h), str(f)) for h, f in profile["columns"]]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([h for h, _ in columns])
    for row in rows:
        writer.writerow(["" if row.get(f) is None else row.get(f) for _, f in columns])
    return ("﻿" + buf.getvalue()).encode("utf-8"), "text/csv", "csv"
