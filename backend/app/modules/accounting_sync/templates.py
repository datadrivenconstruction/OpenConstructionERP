# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mapping​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ templates and tax codes, read from data, never hardcoded.

* Chart templates and file-format layouts: ``app/core/country_data/accounting_charts.json``.
* Tax codes and rates: the dated tax seed of i18n_foundation
  (``seed_data/tax_configurations.json``), the same source invoices use.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

_APP = Path(__file__).resolve().parents[2]
_CHARTS = _APP / "core" / "country_data" / "accounting_charts.json"
_TAX_SEED = _APP / "modules" / "i18n_foundation" / "seed_data" / "tax_configurations.json"


@lru_cache(maxsize=1)
def _charts() -> dict[str, Any]:
    return json.loads(_CHARTS.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _tax_seed() -> list[dict[str, Any]]:
    try:
        rows = json.loads(_TAX_SEED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict)]


def categories() -> list[str]:
    """Neutral posting categories every template maps."""
    return list(_charts()["categories"])


def list_templates(country_code: str | None = None) -> list[dict[str, Any]]:
    """Templates usable for a country: the neutral one plus that country's own."""
    out = []
    for key, tpl in _charts()["templates"].items():
        cc = tpl.get("country_code")
        if cc is None or (country_code and cc == country_code.upper()):
            out.append({"key": key, "label": tpl["label"], "country_code": cc, "formats": tpl["formats"]})
    return out


def get_template(key: str) -> dict[str, Any]:
    """Return one template by key, falling back to the neutral chart."""
    templates = _charts()["templates"]
    return templates.get(key) or templates["generic"]


def file_format(key: str) -> dict[str, Any]:
    """Layout data of a file format (for example the DATEV EXTF column list)."""
    return _charts()["file_formats"][key]


def tax_codes(country_code: str | None, on: date | None = None) -> list[dict[str, Any]]:
    """Tax codes in force for a country on a day, from the dated tax seed.

    Always includes ``ZERO`` and ``RC`` (reverse charge) with rate 0, which every
    market needs and the seed does not list as rows.
    """
    day = (on or date.today()).isoformat()
    out: dict[str, dict[str, Any]] = {}
    for row in _tax_seed():
        if not country_code or row.get("country_code") != country_code.upper():
            continue
        if row.get("subdivision_code"):
            continue
        start, end = row.get("effective_from") or "0000", row.get("effective_to")
        if start > day or (end and end < day):
            continue
        out[str(row["tax_code"])] = {
            "tax_code": str(row["tax_code"]),
            "name": row.get("tax_name") or row["tax_code"],
            "rate_pct": str(Decimal(str(row.get("rate_pct") or "0"))),
        }
    for code in ("ZERO", "RC"):
        out.setdefault(code, {"tax_code": code, "name": code, "rate_pct": "0"})
    return list(out.values())


def tax_rate(country_code: str | None, tax_code: str, on: date | None = None) -> Decimal | None:
    """Rate of a tax code in force on a day, or ``None`` when the seed has none."""
    for row in tax_codes(country_code, on):
        if row["tax_code"] == tax_code:
            return Decimal(row["rate_pct"])
    return None
