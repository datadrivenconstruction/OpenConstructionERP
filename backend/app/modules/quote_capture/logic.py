# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quote​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ capture vocabulary, tax handling and the review audit trail.

Tax comes from country data, never from a constant: the project's country gives
the standard rate (:func:`app.core.tax.get_vat_rate`) and the name of the tax
(VAT, GST or sales tax). A quote may be printed net or gross; levelling and every
confirm path work on net amounts, so a gross quote is converted with the rate
the quote states, or the country rate when it states none.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.modules.quote_capture.numbers import plain, to_decimal

STATUSES = ("draft", "in_review", "confirmed", "rejected")
TARGETS = ("bid", "price_list", "po_draft")
NOTE_KINDS = ("exclusion", "qualification", "escalation", "validity", "payment", "delivery")
LOW_CONFIDENCE = 0.7
LINE_FIELDS = ("description", "quantity", "unit", "unit_rate", "total")

_GST = frozenset({"AU", "NZ", "IN", "SG", "CA", "MY"})
_SALES_TAX = frozenset({"US"})


def tax_name(country: str | None) -> str:
    cc = (country or "").upper()
    if cc in _SALES_TAX:
        return "sales_tax"
    return "gst" if cc in _GST else "vat"


def country_tax_rate(country: str | None) -> Decimal | None:
    """Standard rate in percent for the country, or None where there is no national VAT/GST."""
    if not country:
        return None
    from app.core.tax import VATNotApplicable, get_vat_rate

    try:
        return get_vat_rate(country) * 100
    except VATNotApplicable:
        return None


def tax_view(header: dict[str, Any], country: str | None) -> dict[str, Any]:
    """Net, tax and gross of the quote total, with the basis and where the rate came from."""
    total = to_decimal((header.get("quote_total") or {}).get("value"))
    basis = str((header.get("tax_basis") or {}).get("value") or "net")
    stated = to_decimal((header.get("tax_rate") or {}).get("value"))
    rate = stated if stated is not None else country_tax_rate(country)
    source = "quote" if stated is not None else ("country" if rate is not None else "none")
    out: dict[str, Any] = {"basis": basis, "rate": plain(rate) if rate is not None else None, "rate_source": source}
    out["tax_name"] = tax_name(country)
    if total is None:
        return {**out, "net": None, "tax": None, "gross": None}
    factor = (rate or Decimal("0")) / 100
    if basis == "gross":
        net = (total / (1 + factor)) if factor else total
        gross = total
    else:
        net = total
        gross = total * (1 + factor)
    return {**out, "net": plain(net), "tax": plain(gross - net), "gross": plain(gross)}


def net_factor(header: dict[str, Any], country: str | None) -> Decimal:
    """Multiply a printed amount by this to get it net of tax."""
    view = tax_view(header, country)
    if view["basis"] != "gross" or not view["rate"]:
        return Decimal("1")
    return 1 / (1 + Decimal(view["rate"]) / 100)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def apply_line_edit(line: dict[str, Any], changes: dict[str, Any], user_id: str | None) -> dict[str, Any]:
    """Apply a reviewer's edit; the machine values stay frozen under ``machine``."""
    edited = dict(line)
    for key in LINE_FIELDS:
        if key in changes and changes[key] is not None:
            edited[key] = str(changes[key])
    if changes.get("position_id") is not None or changes.get("clear_match"):
        match = dict(edited.get("match") or {})
        if changes.get("clear_match"):
            match = {
                "position_id": None,
                "status": "rejected",
                "confidence": 0.0,
                "alternatives": match.get("alternatives", []),
            }
        else:
            match.update({"position_id": str(changes["position_id"]), "status": "confirmed"})
        edited["match"] = match
    if changes.get("reviewed") is not None:
        edited["reviewed"] = bool(changes["reviewed"])
        edited["reviewed_by"] = user_id
        edited["reviewed_at"] = now_iso()
    return edited


def audit_trail(header: dict[str, Any], lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every value where the confirmed figure differs from what the machine read."""
    trail: list[dict[str, Any]] = []
    for key, f in header.items():
        if isinstance(f, dict) and str(f.get("value")) != str(f.get("machine_value")):
            trail.append({"field": f"header.{key}", "machine": f.get("machine_value"), "human": f.get("value")})
    for line in lines:
        machine = line.get("machine") or {}
        for key in LINE_FIELDS:
            if str(machine.get(key)) != str(line.get(key)):
                trail.append(
                    {"field": f"line.{line.get('id')}.{key}", "machine": machine.get(key), "human": line.get(key)}
                )
        match = line.get("match") or {}
        if match.get("status") == "confirmed" and match.get("suggested_position_id") not in (
            None,
            match.get("position_id"),
        ):
            trail.append(
                {
                    "field": f"line.{line.get('id')}.match",
                    "machine": match.get("suggested_position_id"),
                    "human": match.get("position_id"),
                }
            )
    return trail


def header_value(header: dict[str, Any], key: str) -> Any:
    f = header.get(key)
    return f.get("value") if isinstance(f, dict) else None


def validation_snapshot(
    *,
    header: dict[str, Any],
    lines: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    project_currency: str | None,
    today: str,
) -> dict[str, Any]:
    """Plain dict the validation rules read; no ORM objects."""
    return {
        "header": {k: header_value(header, k) for k in header},
        "header_confidence": {k: (v or {}).get("confidence") for k, v in header.items() if isinstance(v, dict)},
        "lines": lines,
        "notes": notes,
        "project_currency": (project_currency or "").upper(),
        "today": today,
        "low_confidence": LOW_CONFIDENCE,
    }
