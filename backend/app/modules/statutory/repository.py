# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for statutory checks: the jurisdiction tables loaded packs ship.

The module owns no table. Its data is the law the regional packs contribute
through :mod:`app.core.jurisdiction_rules`, read here and shaped for the UI.
"""

from __future__ import annotations

from typing import Any

from app.core.jurisdiction_rules import all_jurisdictions, get_jurisdiction
from app.modules.deadlines.notice_calendar import WORK_MONTH_EVENT

#: Fields of a tax contract form the UI may show; the treatment map stays server-side.
_FORM_FIELDS = ("label", "source", "exemption_certificate", "description")


def list_codes() -> list[str]:
    """Codes of every jurisdiction a loaded pack contributes."""
    return sorted(all_jurisdictions())


def get_table(code: str | None) -> dict[str, Any] | None:
    """The raw jurisdiction table, or ``None``."""
    return get_jurisdiction(code)


def summary(table: dict[str, Any]) -> dict[str, Any]:
    """The UI-facing shape of one table."""
    rules = table.get("notice_calendar") or []
    events: list[str] = []
    for rule in rules:
        event = str(rule.get("event") or "")
        if event and not event.startswith("rule:") and event != WORK_MONTH_EVENT and event not in events:
            events.append(event)
    tax = table.get("tax")
    tax_view = None
    if isinstance(tax, dict):
        tax_view = {
            "base_rate_pct": tax.get("base_rate_pct"),
            "rate_lookup_url": tax.get("rate_lookup_url"),
            "item_classes": tax.get("item_classes") or [],
            "surtax": tax.get("surtax"),
            "contract_forms": [
                {"code": code, **{k: form.get(k) for k in _FORM_FIELDS if form.get(k)}}
                for code, form in (tax.get("contract_forms") or {}).items()
            ],
        }
    return {
        "code": table["code"],
        "name": table["name"],
        "country": table["country"],
        "verify_note": table.get("verify_note") or "",
        "sectors": list(table.get("sectors") or []),
        "claimant_roles": list(table.get("claimant_roles") or []),
        "project_types": list(table.get("project_types") or []),
        "events": events,
        "monthly_notices": any(r.get("event") == WORK_MONTH_EVENT for r in rules),
        "tax": tax_view,
        "retention": list(table.get("retention") or []),
        "notice_rules": [
            {k: r.get(k) for k in ("code", "name", "kind", "source", "source_url", "claimant_roles", "project_types")}
            for r in rules
        ],
        "payroll_export_profiles": list(table.get("payroll_export_profiles") or []),
        "contract_clauses": list(table.get("contract_clauses") or []),
        "links": list(table.get("links") or []),
    }
