# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Daily diary validation rules (rule set ``daily_diary``).

Each rule reads one record under its own key, built by the service from the stored
record merged with the incoming change::

    {"weather": {"id", "project_id", "source", "captured_at", "sunrise", "sunset"}}
    {"diary": {"id", "project_id", "labour_count", "equipment_count"}}
    {"entry": {"id", "entry_time", "diary_date"}}
    {"survey": {"id", "flown_at"}}

A rule whose record is absent, or whose fields are not stated yet, passes.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import section, to_dec
from app.core.validation.site_rules import SiteRule, parse_instant

DAILY_DIARY_RULE_SET = "daily_diary"

#: Weather sources that record what was observed on site; a forecast may lie ahead, an observation cannot.
_OBSERVED_SOURCES = frozenset({"manual", "sensor"})


def _clock(value: Any) -> time | None:
    """The time of day of an ``HH:MM`` string or an ISO datetime, as written (no zone shift)."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return time.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text).time()
    except ValueError:
        return None


def _is_before_rise(sunrise: Any, sunset: Any) -> bool:
    """True when the stated sunset is not after the sunrise.

    Full datetimes are compared as instants, so a UTC-stamped day that wraps midnight
    (Australia, Asia) is not misjudged. Bare times are compared as written, and a sunset
    before 03:00 is read as after midnight (summer at high latitudes), not as an error.
    """
    rise_at, set_at = parse_instant(sunrise), parse_instant(sunset)
    if rise_at is not None and set_at is not None and "T" in str(sunrise) and "T" in str(sunset):
        return rise_at >= set_at
    rise, sset = _clock(sunrise), _clock(sunset)
    if rise is None or sset is None:
        return False
    return rise >= sset and sset >= time(3, 0)


class WeatherSunOrderRule(SiteRule):
    """The sun rises before it sets."""

    rule_id = "daily_diary.weather_sun_order"
    name = "Sunrise comes before sunset"
    standard = DAILY_DIARY_RULE_SET
    description = "When both are stated, sunrise must be earlier than sunset"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        w = section(context, "weather")
        ref = str(w.get("id", ""))
        if _is_before_rise(w.get("sunrise"), w.get("sunset")):
            return [self.fail(context, "dates_ordered", ref=ref, earlier=w.get("sunrise"), later=w.get("sunset"))]
        return [self.ok(ref)]


class ObservedWeatherNotFutureRule(SiteRule):
    """A manual or sensor reading cannot be taken tomorrow."""

    rule_id = "daily_diary.measurement_not_future"
    name = "Observed weather is not dated in the future"
    standard = DAILY_DIARY_RULE_SET
    description = "captured_at of a manual or sensor record must not be later than now (one day of slack)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        w = section(context, "weather")
        ref = str(w.get("id", ""))
        if w.get("source") in _OBSERVED_SOURCES:
            bad = self.future_date(context, ref, "captured_at", w.get("captured_at"))
            if bad:
                return [bad]
        return [self.ok(ref)]


class CrewConsistentRule(SiteRule):
    """Plant on site is run by someone; equipment with an empty crew is usually an omission."""

    rule_id = "daily_diary.crew_consistent"
    name = "Equipment on site has a crew"
    standard = DAILY_DIARY_RULE_SET
    severity = Severity.WARNING
    description = "equipment_count above zero with labour_count zero is reported (standby plant is legitimate)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = section(context, "diary")
        ref = str(d.get("id", ""))
        labour, equipment = to_dec(d.get("labour_count")), to_dec(d.get("equipment_count"))
        if labour is not None and equipment is not None and equipment > 0 and labour == 0:
            return [
                self.site_fail(
                    context,
                    "required_when",
                    ref=ref,
                    field="labour_count",
                    other_field="equipment_count",
                    other_value=equipment,
                )
            ]
        return [self.ok(ref)]


class EntryWithinDiaryDayRule(SiteRule):
    """An entry belongs to the day of its diary."""

    rule_id = "daily_diary.entry_within_day"
    name = "Entry time falls on the diary day"
    standard = DAILY_DIARY_RULE_SET
    severity = Severity.WARNING
    description = "entry_time more than a day away from diary_date is reported (shift work crosses midnight)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        e = section(context, "entry")
        ref = str(e.get("id", ""))
        moment, day = parse_instant(e.get("entry_time")), parse_instant(e.get("diary_date"))
        if moment is not None and day is not None and not (day - timedelta(days=1) <= moment < day + timedelta(days=2)):
            return [
                self.site_fail(
                    context,
                    "contradiction",
                    ref=ref,
                    field="entry_time",
                    value=moment.date().isoformat(),
                    other_field="diary_date",
                    other_value=day.date().isoformat(),
                )
            ]
        return [self.ok(ref)]


class SurveyNotFutureRule(SiteRule):
    """A drone survey that is on record has been flown."""

    rule_id = "daily_diary.survey_not_future"
    name = "Drone survey was not flown in the future"
    standard = DAILY_DIARY_RULE_SET
    description = "flown_at must not be later than now (one day of slack)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        s = section(context, "survey")
        ref = str(s.get("id", ""))
        bad = self.future_date(context, ref, "flown_at", s.get("flown_at"))
        return [bad] if bad else [self.ok(ref)]


DAILY_DIARY_RULES = (
    WeatherSunOrderRule,
    ObservedWeatherNotFutureRule,
    CrewConsistentRule,
    EntryWithinDiaryDayRule,
    SurveyNotFutureRule,
)


def register_daily_diary_validation_rules() -> None:
    """Register the daily diary rules with the platform rule registry."""
    for rule_class in DAILY_DIARY_RULES:
        rule_registry.register(rule_class(), [DAILY_DIARY_RULE_SET])


__all__ = ["DAILY_DIARY_RULES", "DAILY_DIARY_RULE_SET", "register_daily_diary_validation_rules"]
