# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory checks service: run the neutral engines on one jurisdiction's law.

Stateless. The caller states the facts of a project (sector, contract value,
dates, the retention on a payment, the bid's tax lines, the events that start
lien clocks) and gets back the deadlines, the retention verdict, the tax split
and the findings, each with its source. Nothing is stored and nothing is filed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.contracts.retention_cap import check_retention, parse_table
from app.modules.deadlines.notice_calendar import CalendarInput, compute_calendar, parse_rules
from app.modules.statutory import repository
from app.modules.statutory.tax_engine import TaxLine, compute
from app.modules.statutory.validators import run_checks


class UnknownJurisdictionError(LookupError):
    """No loaded pack carries the requested jurisdiction."""


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def compute_notices(table: dict[str, Any], facts: dict[str, Any]) -> list[dict[str, Any]]:
    """The notice calendar for ``facts`` under ``table``."""
    notices = facts.get("notices")
    if not notices:
        return []
    months = []
    for raw in notices.get("work_months") or []:
        year, _, month = str(raw).partition("-")
        months.append((int(year), int(month)))
    calendar_input = CalendarInput(
        events={k: d for k, v in (notices.get("events") or {}).items() if (d := _date(v))},
        work_months=months,
        role=notices.get("role"),
        project_type=facts.get("project_type"),
        sector=facts.get("sector"),
        today=_date(notices.get("today")),
    )
    return [d.as_dict() for d in compute_calendar(parse_rules(table.get("notice_calendar") or []), calendar_input)]


def compute_retention(table: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any] | None:
    """The retention verdict for ``facts`` under ``table``."""
    retention = facts.get("retention")
    if not retention:
        return None
    check = check_retention(
        parse_table(table.get("retention") or []),
        sector=facts.get("sector"),
        contract_value=_dec(facts.get("contract_value")),
        agreement_date=_date(facts.get("agreement_date")),
        project_type=facts.get("project_type"),
        payment_amount=_dec(retention.get("payment_amount")),
        retention_amount=_dec(retention.get("retention_amount")),
        retention_pct=_dec(retention.get("retention_pct")),
    )
    return check.as_dict()


def compute_tax(table: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any] | None:
    """The tax split for ``facts`` under ``table``."""
    tax = facts.get("tax")
    profile = table.get("tax")
    if not tax or not isinstance(profile, dict):
        return None
    result = compute(
        profile,
        [TaxLine.from_dict(line) for line in tax.get("lines") or []],
        contract_form=tax.get("contract_form"),
        rate_pct=_dec(tax.get("rate_pct")),
        surtax_pct=_dec(tax.get("surtax_pct")),
        exemption_certificate_on_file=bool(tax.get("exemption_certificate_on_file")),
    )
    return result.as_dict()


def evaluate_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Run every engine and check for the facts' jurisdiction.

    Raises:
        UnknownJurisdictionError: When no loaded pack carries the jurisdiction.
    """
    code = str(facts.get("jurisdiction") or "")
    table = repository.get_table(code)
    if table is None:
        raise UnknownJurisdictionError(code)
    computed = {
        "notices": compute_notices(table, facts),
        "retention": compute_retention(table, facts),
        "tax": compute_tax(table, facts),
    }
    findings = run_checks(table, facts, computed)
    return {
        "jurisdiction": table["code"],
        "name": table["name"],
        **computed,
        "findings": [f.as_dict() for f in findings],
        "verify_note": table.get("verify_note") or "",
    }
