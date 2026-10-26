# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Time clock validation rules (part of the ``field_time`` rule set)​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

They read the ``clock_events`` block that the field time service puts on a
timesheet payload built from the clock, or on a clock day being checked on its
own. A payload without that block (every desk-entered timesheet) makes each of
them return nothing. The arithmetic lives in
:mod:`app.modules.field_time.geofence_math`, imported lazily so a disabled
field_time module never breaks rule loading.
"""

from __future__ import annotations

from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
)
from app.core.validation.messages import translate
from app.core.validation.rules import _get_locale


def _payload(context: ValidationContext) -> dict[str, Any]:
    data = context.data
    return data if isinstance(data, dict) else {}


def _names(events: list[dict[str, Any]]) -> dict[str, str]:
    return {str(e.get("worker")): str(e.get("worker_name") or e.get("worker")) for e in events}


def _fail(rule: ValidationRule, locale: str, key: str, element_ref: str, **params: str) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=False,
        message=translate(f"{key}.fail", locale=locale, **params),
        element_ref=element_ref,
        suggestion=translate(f"{key}.suggestion", locale=locale),
    )


class FieldClockOutsideUnapproved(ValidationRule):
    """A clock outside the site fence needs a supervisor's approval."""

    rule_id = "field_time.clock_outside_unapproved"
    name = "Field Time Clock Outside Fence Approved"
    standard = "field_time"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Flags clock-ins and clock-outs outside the site geofence that no supervisor has approved."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        if "clock_events" not in payload:
            return []
        from app.modules.field_time import geofence_math as gm

        locale = _get_locale(context)
        events, _now = gm.read_clock_payload(payload)
        names = _names(events)
        return [
            _fail(
                self,
                locale,
                "field_time.clock_outside_unapproved",
                str(e.get("id")),
                worker=names.get(str(e.get("worker")), ""),
                time=e["occurred_at"].strftime("%H:%M"),
                distance=f"{float(e.get('distance_m') or 0):.0f}",
            )
            for e in gm.unapproved_outside(events)
        ]


class FieldClockOverlappingShifts(ValidationRule):
    """One worker cannot be on two shifts at once."""

    rule_id = "field_time.clock_overlapping_shifts"
    name = "Field Time Clock Overlapping Shifts"
    standard = "field_time"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags a worker whose clocked shifts overlap in time."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        if "clock_events" not in payload:
            return []
        from app.modules.field_time import geofence_math as gm

        locale = _get_locale(context)
        events, _now = gm.read_clock_payload(payload)
        names = _names(events)
        return [
            _fail(
                self,
                locale,
                "field_time.clock_overlapping_shifts",
                a.in_event_id,
                worker=names.get(a.worker, a.worker),
                first=a.started_at.strftime("%H:%M"),
                second=b.started_at.strftime("%H:%M"),
            )
            for a, b in gm.overlapping_shifts(gm.pair_shifts(events))
        ]


class FieldClockMissingClockOut(ValidationRule):
    """A shift that was never closed has no end and so no hours."""

    rule_id = "field_time.clock_missing_clock_out"
    name = "Field Time Clock Missing Clock-Out"
    standard = "field_time"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags a clock-in that has no clock-out after 16 hours or before the next clock-in."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        if "clock_events" not in payload:
            return []
        from datetime import UTC, datetime

        from app.modules.field_time import geofence_math as gm

        locale = _get_locale(context)
        events, now = gm.read_clock_payload(payload)
        names = _names(events)
        return [
            _fail(
                self,
                locale,
                "field_time.clock_missing_clock_out",
                s.in_event_id,
                worker=names.get(s.worker, s.worker),
                time=s.started_at.strftime("%Y-%m-%d %H:%M"),
            )
            for s in gm.missing_clock_outs(gm.pair_shifts(events), now or datetime.now(UTC))
        ]


FIELD_CLOCK_RULES: list[ValidationRule] = [
    FieldClockOutsideUnapproved(),
    FieldClockOverlappingShifts(),
    FieldClockMissingClockOut(),
]
