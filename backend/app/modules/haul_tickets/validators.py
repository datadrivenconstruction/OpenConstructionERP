# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Haul​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ tickets validation rules (rule sets ``haul_tickets`` and ``haul_invoice``).

* ``haul_tickets.net_weight_consistent`` - ERROR. Net is not gross minus tare.
* ``haul_tickets.overweight`` - WARNING. Gross above the vehicle or project limit.
* ``haul_tickets.unique_number_per_haulier`` - ERROR. Ticket number repeats for one haulier.
* ``haul_tickets.delivered_signed`` - ERROR. Delivered without the receiver's signature.
* ``haul_tickets.cost_allocated`` - WARNING. No BOQ position and no cost code.
* ``haul_tickets.rate_present`` - WARNING. A hired truck without a rate.
* ``haul_tickets.quantity_vs_capacity`` - WARNING. Quantity above truck capacity plus tolerance.
* ``haul_tickets.mandatory_fields`` - ERROR. A field the project made mandatory is empty.
* ``haul_tickets.waste_destination`` - ERROR. A disposal ticket without waste code or facility.
* ``haul_invoice.line_has_ticket`` - ERROR. An invoice line names no ticket.

Errors block verification; warnings are shown and the verifier decides.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
    validation_engine,
)
from app.modules.haul_tickets.logic import dec, resolve_weights

logger = logging.getLogger(__name__)

RULE_SET = "haul_tickets"
INVOICE_RULE_SET = "haul_invoice"
DELIVERED_OR_LATER = ("delivered", "verified", "invoiced")


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _ticket(context: ValidationContext) -> dict[str, Any]:
    t = _data(context).get("ticket")
    return t if isinstance(t, dict) else {}


def _settings(context: ValidationContext) -> dict[str, Any]:
    s = _data(context).get("settings")
    return s if isinstance(s, dict) else {}


def _result(rule: ValidationRule, passed: bool, message: str, ref: str | None = None, **details: Any) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=ref,
        details=details,
    )


class _TicketRule(ValidationRule):
    standard = "custom"

    def check(self, t: dict[str, Any], s: dict[str, Any], data: dict[str, Any]) -> tuple[bool, str] | None:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        t = _ticket(context)
        if not t or t.get("status") == "rejected":
            return []
        verdict = self.check(t, _settings(context), _data(context))
        if verdict is None:
            return []
        ok, msg = verdict
        return [_result(self, ok, "OK" if ok else msg, t.get("id"))]


class NetWeightConsistent(_TicketRule):
    rule_id = "haul_tickets.net_weight_consistent"
    name = "Net Equals Gross Minus Tare"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Gross, tare and net weight agree within 20 kg and net is not negative."

    def check(self, t: dict[str, Any], s: dict[str, Any], data: dict[str, Any]) -> tuple[bool, str] | None:
        if dec(t.get("net_t")) is None and dec(t.get("gross_t")) is None:
            return None
        w = resolve_weights(t.get("gross_t"), t.get("tare_t"), t.get("net_t"))
        return w.consistent, f"Gross {w.gross} - tare {w.tare} does not give net {w.net}."


class Overweight(_TicketRule):
    rule_id = "haul_tickets.overweight"
    name = "Gross Weight Within The Limit"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Gross weight does not exceed the vehicle maximum or the project's legal limit."

    def check(self, t: dict[str, Any], s: dict[str, Any], data: dict[str, Any]) -> tuple[bool, str] | None:
        gross = dec(t.get("gross_t"))
        limits = [v for v in (dec(t.get("vehicle_max_gross_t")), dec(s.get("max_gross_t"))) if v]
        if gross is None or not limits:
            return None
        limit = min(limits)
        return gross <= limit, f"Gross {gross} t exceeds the limit of {limit} t."


class UniqueNumberPerHaulier(_TicketRule):
    rule_id = "haul_tickets.unique_number_per_haulier"
    name = "Ticket Number Unique Per Haulier"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A haulier's ticket number appears on one ticket only."

    def check(self, t: dict[str, Any], s: dict[str, Any], data: dict[str, Any]) -> tuple[bool, str] | None:
        if not t.get("ticket_number"):
            return None
        n = int(data.get("same_number_count") or 0)
        return n == 0, f"Ticket {t.get('ticket_number')} of {t.get('haulier_name')} exists {n + 1} times."


class DeliveredSigned(_TicketRule):
    rule_id = "haul_tickets.delivered_signed"
    name = "Delivered Ticket Signed By The Receiver"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A delivered ticket carries the receiver's name and signature."

    def check(self, t: dict[str, Any], s: dict[str, Any], data: dict[str, Any]) -> tuple[bool, str] | None:
        if t.get("status") not in DELIVERED_OR_LATER:
            return None
        return bool(t.get("signature")) and bool(t.get("receiver_name")), "Delivered without a receiver signature."


class CostAllocated(_TicketRule):
    rule_id = "haul_tickets.cost_allocated"
    name = "Ticket Allocated To A Cost Code"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "The ticket points at a BOQ position or a cost code."

    def check(self, t: dict[str, Any], s: dict[str, Any], data: dict[str, Any]) -> tuple[bool, str] | None:
        return bool(t.get("boq_position_id") or t.get("cost_code")), "No BOQ position or cost code."


class RatePresent(_TicketRule):
    rule_id = "haul_tickets.rate_present"
    name = "Hired Haulage Has A Rate"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A hired truck ticket carries a rate (per t, m3, load or hour)."

    def check(self, t: dict[str, Any], s: dict[str, Any], data: dict[str, Any]) -> tuple[bool, str] | None:
        if t.get("truck_source") != "hired":
            return None
        return dec(t.get("rate")) is not None, "No haulier rate."


class QuantityVsCapacity(_TicketRule):
    rule_id = "haul_tickets.quantity_vs_capacity"
    name = "Quantity Within Truck Capacity"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "The load does not exceed the truck capacity by more than the project tolerance."

    def check(self, t: dict[str, Any], s: dict[str, Any], data: dict[str, Any]) -> tuple[bool, str] | None:
        cap = dec(t.get("vehicle_capacity"))
        qty = dec(t.get("quantity"))
        if not cap or qty is None or t.get("unit") == "load":
            return None
        limit = cap * (1 + Decimal(int(s.get("capacity_tolerance_pct") or 10)) / 100)
        return qty <= limit, f"{qty} {t.get('unit')} is above the truck capacity of {cap}."


class MandatoryFields(_TicketRule):
    rule_id = "haul_tickets.mandatory_fields"
    name = "Mandatory Fields Filled"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every field the project declared mandatory is filled."

    def check(self, t: dict[str, Any], s: dict[str, Any], data: dict[str, Any]) -> tuple[bool, str] | None:
        fields = [f for f in (s.get("mandatory_fields") or []) if isinstance(f, str)]
        if not fields:
            return None
        missing = [f for f in fields if t.get(f) in (None, "", [])]
        return not missing, "Missing: " + ", ".join(missing)


class WasteDestination(_TicketRule):
    rule_id = "haul_tickets.waste_destination"
    name = "Disposal Ticket Names Waste Code And Facility"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A waste or spoil ticket carries a waste code and the receiving facility."

    def check(self, t: dict[str, Any], s: dict[str, Any], data: dict[str, Any]) -> tuple[bool, str] | None:
        if t.get("haul_type") != "waste":
            return None
        return bool(t.get("waste_code") and t.get("receiving_facility")), "Waste code or receiving facility missing."


class InvoiceLineHasTicket(ValidationRule):
    rule_id = "haul_invoice.line_has_ticket"
    name = "Every Invoice Line Has A Ticket"
    standard = "custom"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Each haulier invoice line matches a ticket of that haulier."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for line in _data(context).get("lines") or []:
            if not isinstance(line, dict):
                continue
            ok = line.get("status") != "missing_ticket"
            msg = "OK" if ok else f"Invoice line {line.get('ticket_number') or '?'} has no ticket."
            out.append(_result(self, ok, msg, str(line.get("index"))))
        return out


_TICKET_RULES: tuple[ValidationRule, ...] = (
    NetWeightConsistent(),
    Overweight(),
    UniqueNumberPerHaulier(),
    DeliveredSigned(),
    CostAllocated(),
    RatePresent(),
    QuantityVsCapacity(),
    MandatoryFields(),
    WasteDestination(),
)
_INVOICE_RULES: tuple[ValidationRule, ...] = (InvoiceLineHasTicket(),)
RULE_IDS: tuple[str, ...] = tuple(r.rule_id for r in _TICKET_RULES + _INVOICE_RULES)


def register_haul_tickets_rules() -> None:
    for rule in _TICKET_RULES:
        rule_registry.register(rule, [RULE_SET])
    for rule in _INVOICE_RULES:
        rule_registry.register(rule, [INVOICE_RULE_SET])


async def evaluate(snapshot: dict[str, Any], *, rule_set: str = RULE_SET, target_id: str = "") -> list[RuleResult]:
    """Failed findings; an engine failure logs and returns none."""
    try:
        report = await validation_engine.validate(
            data=snapshot, rule_sets=[rule_set], target_type=rule_set, target_id=target_id
        )
    except Exception:  # noqa: BLE001 - findings augment a read, never break it
        logger.warning("haul ticket validation failed for %s", target_id, exc_info=True)
        return []
    return [r for r in report.results if not r.passed and not r.is_engine_error]
