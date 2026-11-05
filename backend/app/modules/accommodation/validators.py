# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accommodation validation rules (rule set ``accommodation``).

Rules run over a plain dict context built by the caller; every section is optional and a
rule only judges the sections it finds::

    {
        "accommodation": {"id", "kind", "capacity_total", "rooms_capacity_total"},
        "rooms": [{"id", "label", "base_rate", "currency"}],
        "booking": {"id", "check_in", "check_out"},
        "charge": {"id", "amount", "currency", "period_start", "period_end", "stay_start", "stay_end"},
    }
"""

from __future__ import annotations

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, rows, section, to_dec
from app.core.validation.quality_rules import QualityRule, parse_day

ACCOMMODATION_RULE_SET = "accommodation"


class _SiteRule(QualityRule):
    message_section = "site_records"
    standard = ACCOMMODATION_RULE_SET


class BookingDatesOrderedRule(_SiteRule):
    """A stay ends after it starts, also when only one date was edited."""

    rule_id = "accommodation.booking_dates_ordered"
    name = "Booking check-out is after check-in"
    description = "check_out must come after check_in on the stored booking, not just in the request"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        booking = section(context, "booking")
        ref = str(booking.get("id", ""))
        start, end = parse_day(booking.get("check_in")), parse_day(booking.get("check_out"))
        if start and end and end <= start:
            return [self.fail(context, "dates_not_ordered", ref=ref, start=start.isoformat(), end=end.isoformat())]
        return [self.ok(ref)]


class ChargePeriodRule(_SiteRule):
    """A charge period runs forwards and sits inside the stay it is billed to."""

    rule_id = "accommodation.charge_period"
    name = "Charge period is ordered and inside the stay"
    description = "period_end must not precede period_start; a period outside the stay is flagged"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        charge = section(context, "charge")
        ref = str(charge.get("id", ""))
        start, end = parse_day(charge.get("period_start")), parse_day(charge.get("period_end"))
        if start and end and end < start:
            return [self.fail(context, "dates_not_ordered", ref=ref, start=start.isoformat(), end=end.isoformat())]
        stay_start, stay_end = parse_day(charge.get("stay_start")), parse_day(charge.get("stay_end"))
        outside = (start and stay_start and start < stay_start) or (end and stay_end and end > stay_end)
        shown = start or end
        if outside and shown:
            return [
                self.fail(
                    context,
                    "period_outside_stay",
                    ref=ref,
                    severity=Severity.WARNING,
                    start=shown.isoformat(),
                    end=(end or shown).isoformat(),
                    stay_start=stay_start.isoformat() if stay_start else "-",
                    stay_end=stay_end.isoformat() if stay_end else "-",
                )
            ]
        return [self.ok(ref)]


class ChargeCurrencyRule(_SiteRule):
    """A charge with an amount names its currency."""

    rule_id = "accommodation.charge_currency"
    name = "Charge with an amount has a currency"
    description = "A charge above zero needs a currency from the charge, the room rate or the project"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        charge = section(context, "charge")
        ref = str(charge.get("id", ""))
        amount = to_dec(charge.get("amount"))
        if amount is not None and amount > 0 and blank(charge.get("currency")):
            return [self.fail(context, "currency_missing", ref=ref, amount=amount)]
        return [self.ok(ref)]


class CapacityCoversRoomsRule(_SiteRule):
    """The rooms do not sleep more people than the accommodation is rated for."""

    rule_id = "accommodation.capacity_covers_rooms"
    name = "Room beds fit the rated capacity"
    severity = Severity.WARNING
    description = "The sum of room capacities should not exceed capacity_total when that is stated"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        accom = section(context, "accommodation")
        ref = str(accom.get("id", ""))
        cap, beds = to_dec(accom.get("capacity_total")), to_dec(accom.get("rooms_capacity_total"))
        if cap is not None and cap > 0 and beds is not None and beds > cap:
            return [self.fail(context, "capacity_exceeded", ref=ref, total=beds, capacity=cap)]
        return [self.ok(ref)]


class RoomRateMatchesKindRule(_SiteRule):
    """A rate on a room has a currency, and a worker camp room is not normally charged."""

    rule_id = "accommodation.room_rate"
    name = "Room rate has a currency and suits the kind"
    severity = Severity.WARNING
    description = "A base rate needs a currency; worker camp rooms are employer housing and normally free"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        kind = section(context, "accommodation").get("kind")
        out: list[RuleResult] = []
        for room in rows(context, "rooms"):
            rate = to_dec(room.get("base_rate"))
            if rate is None or rate <= 0:
                continue
            ref, label = str(room.get("id", "")), room.get("label", "")
            if blank(room.get("currency")):
                out.append(self.fail(context, "currency_missing", ref=ref, amount=rate))
            if kind == "worker_camp":
                out.append(self.fail(context, "camp_room_charged", ref=ref, label=label, rate=rate))
        return out or [self.ok(str(section(context, "accommodation").get("id", "")))]


ACCOMMODATION_RULES = (
    BookingDatesOrderedRule,
    ChargePeriodRule,
    ChargeCurrencyRule,
    CapacityCoversRoomsRule,
    RoomRateMatchesKindRule,
)


def register_accommodation_validation_rules() -> None:
    """Register the accommodation rules with the platform rule registry."""
    for rule_class in ACCOMMODATION_RULES:
        rule_registry.register(rule_class(), [ACCOMMODATION_RULE_SET])


__all__ = ["ACCOMMODATION_RULES", "ACCOMMODATION_RULE_SET", "register_accommodation_validation_rules"]
