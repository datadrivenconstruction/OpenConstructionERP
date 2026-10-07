# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schedule service - business logic for 4D construction scheduling.

Stateless service layer. Handles:
- Schedule CRUD with project scoping
- Activity management with WBS hierarchy and BOQ linking
- Work order management
- Gantt chart data generation
- CPM (Critical Path Method) calculation
- PERT risk analysis
- Generate-from-BOQ automation
- Event publishing for inter-module communication
"""

import asyncio
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.core.calendar import _holidays_cn
from app.core.cpm import normalise_exception_date, readable_exception_dates, readable_work_days
from app.core.events import event_bus, publish_after_commit
from app.core.json_merge import merge_metadata

_logger_ev = __import__("logging").getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


def coded_http_error(status_code: int, code: str, message: str, **params: object) -> HTTPException:
    """An HTTP error the screen can translate.

    The detail is ``{"error": code, "message": message, **params}``: the client
    looks the code up in its own language and fills in ``params``, while API
    clients keep the English ``message``.

    Args:
        status_code: HTTP status.
        code: Stable machine-readable code, e.g. ``schedule_has_activities``.
        message: English sentence for API clients and logs.
        **params: Values the translated text needs (counts, dates).

    Returns:
        The exception to raise.
    """
    return HTTPException(status_code=status_code, detail={"error": code, "message": message, **params})


def _normalize_deps(deps: list | None) -> list[dict]:
    """Normalize dependencies to list[dict].

    Seeded/legacy data may store dependencies as plain UUID strings.
    This ensures a consistent dict format for Pydantic schemas.
    """
    if not deps:
        return []
    result: list[dict] = []
    for dep in deps:
        if isinstance(dep, str):
            result.append({"activity_id": dep, "type": "FS", "lag_days": 0})
        elif isinstance(dep, dict):
            result.append(dep)
        else:
            result.append({"activity_id": str(dep), "type": "FS", "lag_days": 0})
    return result


from app.modules.schedule.boq_plan import PlanFit
from app.modules.schedule.milestone_events import announce_if_milestone_reached
from app.modules.schedule.models import Activity, Schedule, ScheduleRelationship, WorkOrder
from app.modules.schedule.ordering import activity_order_terms
from app.modules.schedule.repository import (
    ActivityRepository,
    RelationshipRepository,
    ScheduleRepository,
    WorkOrderRepository,
)
from app.modules.schedule.schemas import (
    ActivityCreate,
    ActivityUpdate,
    CPMActivityResult,
    CriticalPathResponse,
    GanttActivity,
    GanttData,
    GanttSummary,
    RiskAnalysisResponse,
    ScheduleCreate,
    ScheduleUpdate,
    WorkOrderCreate,
    WorkOrderUpdate,
)
from app.modules.schedule.wbs_numbering import (
    order_with_block_under,
    sort_order_changes,
    subtree_ids,
    suggest_code,
)

# PERT distribution factors (from DDC_Toolkit reference)
_PERT_OPTIMISTIC = 0.75
_PERT_PESSIMISTIC = 1.60

logger = logging.getLogger(__name__)

# Placeholder sort order for a row being placed; any value past the real ones.
_INT32_LAST = 2**31 - 1


def _str_to_float(value: str | None) -> float:
    """Convert a string-stored numeric value to float, defaulting to 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


# ── Fallback production rates for generate-from-BOQ durations ─────────────
# Labor-hours per 1 unit of quantity, keyed by normalized BOQ unit. Used
# when a position carries no labor metadata at all (no labor_hours, no
# resources) so generated activities never end up with a zero duration.
# Coarse industry averages - enough for a usable first schedule that the
# planner refines; activities derived this way are flagged with
# ``duration_source = "estimated_fallback"`` in their metadata.
_FALLBACK_PRODUCTION_RATES: dict[str, float] = {
    "m3": 4.0,
    "m2": 0.8,
    "m": 0.5,
    "kg": 0.02,
    "pcs": 1.0,
    "stk": 1.0,
    "t": 8.0,
    # Quintal (100 kg), as Italian bills measure steel and lime.
    "q": 2.0,
}

# People working one task together, by kind of unit: a gang of four on a
# concrete pour, three on plaster or flooring, two on linear work and pieces.
# Not to be confused with the crews a section gets side by side
# (``boq_plan.MAX_CREWS``): a gang of four on one pour is still one crew.
_FALLBACK_GANG_SIZE: dict[str, int] = {
    "m3": 4,
    "m2": 3,
    "m": 2,
    "kg": 4,
    "t": 4,
    "q": 4,
    "pcs": 2,
    "stk": 2,
    "lsum": 1,
}
_FALLBACK_DEFAULT_GANG = 2

# A duration guessed from the unit table may claim at most this many times the
# position's share of the bill's money in the bill's guessed hours. The table
# reads 6,252 m2 of scaffold hire (1,250 m2 for five months) as 5,000 hours of
# work for a position worth 4 % of the bill; the price says otherwise.
_FALLBACK_PRICE_SHARE_CAP = 3.0

# The most workers per position the generator assumes on its own when a bill
# gives hours but no crew. A person may ask for any number in the same range.
MAX_ASSUMED_WORKERS = 20

# Lump-sum positions get a flat labor-hour allowance regardless of quantity.
_FALLBACK_LUMP_SUM_HOURS = 8.0

# Labor-hours per unit when the unit is unknown.
_FALLBACK_DEFAULT_RATE = 1.0

# Common unit spellings mapped onto the production-rate keys above.
_UNIT_ALIASES: dict[str, str] = {
    "m²": "m2",
    "qm": "m2",
    "sqm": "m2",
    "m³": "m3",
    "cbm": "m3",
    "lfm": "m",
    "lm": "m",
    "pc": "pcs",
    "piece": "pcs",
    "pieces": "pcs",
    "ea": "pcs",
    "each": "pcs",
    "st": "stk",
    "to": "t",
    "ton": "t",
    "tonne": "t",
    "ls": "lsum",
    "lump sum": "lsum",
    "psch": "lsum",
    "pauschal": "lsum",
    # Italian and other bills of quantities.
    "mq": "m2",
    "m.q.": "m2",
    "mc": "m3",
    "m.c.": "m3",
    "ml": "m",
    "m.l.": "m",
    "cad": "pcs",
    "cad.": "pcs",
    "nr": "pcs",
    "nr.": "pcs",
    "n": "pcs",
    "n.": "pcs",
    "no": "pcs",
    "pz": "pcs",
    "q.li": "q",
    "ql": "q",
}


def _normalize_unit(unit: str | None) -> str:
    """Normalize a BOQ unit string to a production-rate key.

    The table above first, on the unit as written; then the bill's own
    lump-sum test, which knows "a corpo", "kpl", "forfait" and the rest.
    """
    u = (unit or "").strip().lower()
    if u in _UNIT_ALIASES:
        return _UNIT_ALIASES[u]
    if u in _FALLBACK_PRODUCTION_RATES:
        return u
    try:
        from app.modules.boq.units import is_lump_sum_unit
    except ImportError:  # the bill module is a plugin like any other
        return u
    return "lsum" if is_lump_sum_unit(u) else u


def fallback_gang_size(unit: str | None) -> int:
    """People working one task together, by the kind of unit it is measured in."""
    return _FALLBACK_GANG_SIZE.get(_normalize_unit(unit), _FALLBACK_DEFAULT_GANG)


def fallback_production_rate(unit: str | None) -> float:
    """Labour-hours per unit the fallback table assumes."""
    return _FALLBACK_PRODUCTION_RATES.get(_normalize_unit(unit), _FALLBACK_DEFAULT_RATE)


def fallback_labor_hours(unit: str | None, quantity: float) -> float:
    """Estimate total labor-hours for a position from unit production rates.

    Args:
        unit: BOQ position unit (e.g. "m3", "m2", "pcs"); common aliases
            such as "m³", "Stk" or "psch" are normalized first.
        quantity: Position quantity (callers guard quantity > 0).

    Returns:
        Estimated total labor-hours. Lump-sum positions get a flat
        allowance independent of quantity; unknown units fall back to
        ``_FALLBACK_DEFAULT_RATE`` hours per unit.
    """
    u = _normalize_unit(unit)
    if u == "lsum":
        return _FALLBACK_LUMP_SUM_HOURS
    rate = _FALLBACK_PRODUCTION_RATES.get(u, _FALLBACK_DEFAULT_RATE)
    return quantity * rate


def estimate_fallback_duration_days(
    unit: str | None,
    quantity: float,
    hours_per_day: float = 8.0,
    gang_size: int | None = None,
) -> int:
    """Derive an activity duration from unit-based production rates.

    Used by :meth:`ScheduleService.generate_from_boq` when a BOQ position
    has no labor metadata, so the generated activity still gets a usable
    non-zero duration.

    Args:
        unit: BOQ position unit (normalized internally).
        quantity: Position quantity (callers guard quantity > 0).
        hours_per_day: Hours one person works per working day (regional calendar).
        gang_size: People on the task; by default :func:`fallback_gang_size`.

    Returns:
        Working days, ``ceil(total_hours / (gang_size * hours_per_day))``,
        at least 1. 850 m3 at 4 h/m3 is 3,400 hours; a gang of four at 8 hours
        a day does it in 107 days.
    """
    total_hours = fallback_labor_hours(unit, quantity)
    hpd = hours_per_day if hours_per_day > 0 else 8.0
    gang = gang_size if gang_size and gang_size > 0 else fallback_gang_size(unit)
    return max(1, math.ceil(total_hours / (gang * hpd)))


def _meta_number(meta: dict, key: str) -> float:
    """Read a numeric metadata value defensively (string values tolerated)."""
    try:
        return float(meta.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


# Hour spellings already used by BOQ/assembly resources, cost translations
# ("Std."), and the GESN labour-unit reader. No day/week conversion: a time
# allowance in another dimension is not an hourly productivity norm.
_RESOURCE_HOUR_UNITS = frozenset(
    {
        "h",
        "hr",
        "hrs",
        "hour",
        "hours",
        "std",
        "std.",
        "stunde",
        "stunden",
        "person-hour",
        "person-hours",
        "man-hour",
        "man-hours",
        "чел.-ч",
        "чел-ч",
        "чел.ч",
        "человеко-час",
        "chel.-ch",
        "chel-ch",
        "ч",
        "hod",
        "jam",
        "ora",
        "uur",
        "시간",
        "時間",
        "godz",
        "tim",
        "ชั่วโมง",
        "saat",
        "giờ",
    }
)
# Preserve the pre-existing untyped/plant path for explicit hrs/hours labels.
# Do not start adding equipment "hr" to labour: demo buildups carry both, and
# summing them would change every such norm. Substring matches like hours/m2
# and hours-allowance, however, are not quantities measured in hours.
_LEGACY_RESOURCE_HOUR_UNITS = frozenset({"hrs", "hours", "person-hours", "man-hours", "machine-hours", "machine-hrs"})


def _resource_is_hourly(resource: dict) -> bool:
    unit = str(resource.get("unit") or "").strip().lower()
    kind = str(resource.get("type") or "").strip().lower()
    return unit in _LEGACY_RESOURCE_HOUR_UNITS or (kind in ("labor", "operator") and unit in _RESOURCE_HOUR_UNITS)


def _calc_duration_from_resources(
    pos_meta: dict,
    quantity: float,
    unit: str | None,
    total_cost: float,
    grand_total: float,
    total_days: int,
    *,
    hours_per_day: float,
    work_days_per_week: int,
    assumed_workers: int = 1,
) -> tuple[int, str]:
    """Calculate the calendar-day duration for a BOQ-generated activity.

    Priority:
        1. Explicit ``labor_hours`` (+ ``workers_per_unit``) in position
           metadata - the primary, data-driven path.
        2. Sum of hourly labor resources stored in position metadata.
        3. Unit-based fallback production rates when the position has a
           nonzero quantity but no labor metadata at all. Lump-sum units
           are the exception: their quantity carries no production-rate
           signal, so when total cost data is available they defer to the
           cost-proportional path below (audit m10) and only take the flat
           8h allowance as the last resort.
        4. Cost-proportional share of the total project duration.

    Args:
        pos_meta: BOQ position metadata dict.
        quantity: Position quantity.
        unit: Position unit (for the fallback production-rate table).
        total_cost: Position total cost.
        grand_total: Grand total across all sections (cost-proportional path).
        total_days: The project window in calendar days. Only the
            cost-proportional path uses it, as the scale its share is taken
            of. The other paths are not cut to it: a position longer than the
            window keeps its length, so fitting the plan sees the overrun.
        hours_per_day: Crew hours per working day (regional calendar).
        work_days_per_week: Working days per week (regional calendar).
        assumed_workers: Workers on the position when its metadata names no
            ``workers_per_unit``; a count of labour rows above it wins.

    Returns:
        ``(duration_days, source)`` where ``source`` is one of
        ``labor_hours``, ``resource_sum``, ``estimated_fallback``,
        ``cost_proportional`` or ``default_minimum`` so the UI can
        distinguish measured from estimated durations.
    """
    # ── Try 1: explicit labor_hours + workers_per_unit in metadata ──────
    labor_hours = _meta_number(pos_meta, "labor_hours")
    workers = _meta_number(pos_meta, "workers_per_unit")

    if labor_hours > 0 and quantity > 0:
        total_hours = quantity * labor_hours
        crew = max(workers, 1) if workers > 0 else max(assumed_workers, 1)
        crew_hours_per_day = crew * hours_per_day
        working_days = total_hours / crew_hours_per_day
        # Add 10% for mobilization / demobilization
        cal_days = working_days * 1.1
        # Convert working days -> calendar days
        cal_days = cal_days * 7 / work_days_per_week
        return max(1, int(round(cal_days))), "labor_hours"

    # ── Try 2: sum labor-type resources stored in metadata ──────────────
    # The bill tolerates resource rows that are not mappings (and a resources
    # value that is not a list), so they are skipped here rather than crashing
    # the whole generation.
    raw_resources = pos_meta.get("resources", []) if isinstance(pos_meta, dict) else []
    resources = [r for r in raw_resources if isinstance(r, dict)] if isinstance(raw_resources, list) else []
    if resources and quantity > 0:
        labor_hrs_per_unit = 0.0
        labor_rows = 0
        for res in resources:
            if not _resource_is_hourly(res):
                continue
            res_type = str(res.get("type") or "").strip().lower()
            if res_type in ("labor", "operator"):
                labor_rows += 1
            labor_hrs_per_unit += _meta_number(res, "quantity")
        if labor_hrs_per_unit > 0:
            total_hours = quantity * labor_hrs_per_unit
            crew_size = max(labor_rows, assumed_workers, 1)
            crew_hours_per_day = crew_size * hours_per_day
            working_days = total_hours / crew_hours_per_day
            cal_days = working_days * 1.1 * 7 / work_days_per_week
            return max(1, int(round(cal_days))), "resource_sum"

    # ── Try 3: unit-based fallback production rates ──────────────────────
    # No labor metadata at all but a real quantity - estimate from the
    # module-level production-rate table so the activity never gets a
    # zero / near-zero duration. Lump-sum units only carry a flat 8h
    # allowance regardless of size, which would collapse a big lump-sum
    # subcontract to 1 day - prefer the cost-proportional share (Try 4)
    # whenever total cost data is available and keep the flat allowance
    # strictly as the last resort (audit m10).
    if quantity > 0:
        lump_sum_with_cost_data = _normalize_unit(unit) == "lsum" and total_cost > 0 and grand_total > 0
        if not lump_sum_with_cost_data:
            days = estimate_fallback_duration_days(unit, quantity, hours_per_day)
            return max(1, days), "estimated_fallback"

    # ── Try 4: cost-proportional fallback ────────────────────────────────
    if total_cost > 0 and grand_total > 0:
        proportion = total_cost / grand_total
        return max(1, round(proportion * total_days)), "cost_proportional"

    return 3, "default_minimum"  # minimum default


# ── Regional work calendar configuration ─────────────────────────────────
# Each entry defines hours_per_day, work_days (weekday indices) and label.
# An entry may carry a ``holidays`` callable (year -> set[date]).
# compute_duration skips those dates in addition to weekends.
# weekday(): Monday=0, Tuesday=1, ... Saturday=5, Sunday=6
#
# WHAT THIS TABLE IS. The week the planner schedules against, which is not the
# same question as the week a statute describes. core.calendar._WORKING_WEEK
# answers that other question. A planning week may deliberately be LONGER than
# the statutory one, which is why Brazil, China and India plan six days on top
# of a five-day statutory week. It may never be shorter, because removing a day
# the country works puts every computed date on the wrong side of the weekend.
# The gate is tests/unit/test_work_calendar_rest_days_do_not_conflict.py, and
# its module docstring is the long form of this paragraph.
#
# WHAT CONSULTS IT. get_work_calendar is the only reader that computes a date,
# and every path that reaches it asks the same question the same way: the
# project's stored region, resolved once per request by
# ScheduleService.resolve_project_region. BOQ schedule generation, the three
# compute_duration call sites in this file (create_activity, update_activity
# and the get_gantt_data fallback for a stored duration of zero) and the two
# schedule imports in the router (XER and MSP XML) all pass its answer, so one
# project is planned on one week wherever its dates are counted.
#
# It was not always so. compute_duration took a region argument from March 2026
# and no caller passed one until September, so every recompute counted Monday
# to Friday while BOQ generation counted the regional week: a Gulf project was
# drawn Sunday to Thursday and recounted Monday to Friday the first time anyone
# dragged a date. Durations persisted before that fix were not rewritten. A row
# keeps the count it was given until its dates are next saved, so a schedule
# can carry both counts side by side until then. The gate against the paths
# parting again is tests/unit/test_schedule.py, the tests named for Doha and
# Berlin.
#
# core.country_coverage reads this table as well, but as a coverage probe, and
# it deliberately answers through the resolver rather than off the table: the
# keys are a mixed vocabulary rather than country codes, so reading them
# directly gives the wrong answer. It computes no dates.
#
# WHERE EACH WEEK CAME FROM is recorded per entry. An entry with no note is
# one whose source was never recorded, and that is worth knowing as such.

WORK_CALENDARS: dict[str, dict] = {
    "DEFAULT": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri
        "label": "Standard (Mon-Fri, 8h)",
    },
    # 1. USA - USA_USD
    "US": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri
        "label": "USA (Mon-Fri, 8h)",
    },
    # 2. UK - UK_GBP
    "UK": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri
        "label": "UK (Mon-Fri, 8h)",
    },
    # 3. Germany/DACH - DE_BERLIN
    "DACH": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri
        "label": "Germany/DACH (Mon-Fri, 8h)",
    },
    # 4. Canada - ENG_TORONTO
    "CANADA": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri
        "label": "Canada (Mon-Fri, 8h)",
    },
    # 5. France - FR_PARIS
    "FRANCE": {
        "hours_per_day": 7,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri (35h/week legal)
        "label": "France (Mon-Fri, 7h)",
    },
    # 6. Spain - SP_BARCELONA
    "SPAIN": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri
        "label": "Spain (Mon-Fri, 8h)",
    },
    # 7. Brazil - PT_SAOPAULO
    "BRAZIL": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4, 5},  # Mon-Sat (44h/week legal)
        "label": "Brazil (Mon-Sat, 8h)",
    },
    # 8. Russia - RU_STPETERSBURG
    "RU": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri
        "label": "Russia (Mon-Fri, 8h)",
    },
    # Gulf states that work Sunday to Thursday: SA, QA, KW, BH and OM.
    #
    # Friday is the statutory weekly rest day, not merely the customary one:
    # Qatar Labour Law No. 14 of 2004 Art. 75 and Kuwait Labour Law No. 6 of 2010
    # Art. 64 both name it. A planning week that works Friday therefore
    # contradicts the statute, and one that rests Sunday drops a working day.
    #
    # Eight hours a day keeps the week inside every maximum in the group: 48
    # hours a week in Saudi Arabia (Labour Law Art. 98), Qatar (Art. 73), Kuwait
    # (Art. 64) and Bahrain (Law No. 36 of 2012 Art. 51), and 40 hours in Oman,
    # the lowest of the six (Royal Decree 53/2023 Art. 70). Five 8-hour days is
    # 40 and clears all of them.
    #
    # Limit of the sourcing: Oman's statute sets two consecutive rest days
    # without naming them (Royal Decree 53/2023 Art. 77), so Sunday-Thursday for
    # Oman is the regional convention rather than a statute naming those days.
    # Ramadan reductions to 6 hours a day are not modelled here.
    "GULF": {
        "hours_per_day": 8,
        "work_days": {6, 0, 1, 2, 3},  # Sun-Thu
        "label": "Gulf (Sun-Thu, 8h)",
    },
    # The UAE left the Sunday-Thursday week on 1 January 2022 and is the only GCC
    # state to have done so, which is why it cannot share the entry above.
    # Federal government works Monday to Thursday in full with a half day on
    # Friday and a Saturday-Sunday weekend. The private-sector maximum is 8 hours
    # a day and 48 hours a week (Federal Decree-Law No. 33 of 2021 Art. 17).
    #
    # Limit of the sourcing: Friday is modelled as a whole working day because it
    # is worked, and a half day cannot be expressed in a whole-day work_days set.
    # This overstates Friday for the public sector rather than dropping it.
    "UAE": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4},  # Mon-Fri
        "label": "UAE (Mon-Fri, 8h)",
    },
    # 10. China - ZH_SHANGHAI
    #
    # Source of the week: UNSOURCED. The six-day week is a construction site
    # convention and no statute is cited for it here. An attempt to source the
    # PRC statutory week failed to reach a primary text, so the weekly maximum
    # this six-day week would have to fit inside is not known, and no figure has
    # been invented for it. core.calendar._WORKING_WEEK carries Monday-Friday for
    # CN, also uncited, so the two are not evidence for one another.
    #
    # China's holidays come from core.calendar._holidays_cn, which cites the
    # State Council national holiday measures. That function also documents the
    # annual arrangement that turns particular weekends into working days, which
    # neither this table nor the seeded calendar can express.
    "CHINA": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4, 5},  # Mon-Sat (common in construction)
        "label": "China (Mon-Sat, 8h)",
        "holidays": _holidays_cn,  # year -> set[date]; Spring Festival et al.
    },
    # 11. India - HI_MUMBAI
    #
    # Source of the week: UNSOURCED, and unlike Brazil and China this entry gave
    # no reason of its own. Brazil records a statutory 44h week and China records
    # a site convention; India recorded neither. The source the original author
    # used could not be found, so nothing is claimed for it here rather than a
    # citation being fitted to a value that was already in the table.
    "INDIA": {
        "hours_per_day": 8,
        "work_days": {0, 1, 2, 3, 4, 5},  # Mon-Sat
        "label": "India (Mon-Sat, 8h)",
    },
}


# Region resolution keyspaces, held apart on purpose.
#
# A calendar is selected by ISO 3166-1 alpha-2 country code. That is the
# convention the shipped CWICR catalogue uses for its region ids today:
# BR_SAOPAULO, CA_TORONTO, AR_BUENOSAIRES, PT_LISBON, GB_LONDON, IN_MUMBAI.
# A country whose week is not Monday-Friday and is simply absent from this map
# is not detected by anything: it falls through to DEFAULT, which is Mon-Fri, and
# a missing country looks exactly like a country with no special calendar. That
# is how Kuwait, Bahrain and Oman were given the wrong weekend. The gate is
# tests/unit/test_work_calendar_rest_days_do_not_conflict.py.
_CALENDAR_BY_COUNTRY: dict[str, str] = {
    "AE": "UAE",
    "AT": "DACH",
    "BH": "GULF",
    "BR": "BRAZIL",
    "CA": "CANADA",
    "CH": "DACH",
    "CN": "CHINA",
    "DE": "DACH",
    "ES": "SPAIN",
    "FR": "FRANCE",
    "GB": "UK",
    "IN": "INDIA",
    "KW": "GULF",
    "OM": "GULF",
    "QA": "GULF",
    "RU": "RU",
    "SA": "GULF",
    "US": "US",
}

# Heads that are not, and can never be, ISO 3166-1 alpha-2 country codes: a
# superseded CWICR naming that keyed some regions by language (ZH_SHANGHAI,
# HI_MUMBAI, SP_BARCELONA) or by a longer alias (USA_USD, UK_GBP, ENG_TORONTO),
# plus the calendar keys and grouping names a project may carry directly.
# core.match_service.region_language renames the same strays to their ISO form.
#
# Nothing in here may be a two-letter ISO code. AR and PT used to sit in the
# same dict as the country codes, where they meant Arabic and Portuguese, so
# Buenos Aires was given the Gulf week of six 10-hour days and Lisbon the
# Brazilian week of six. Because the three head keyspaces cannot overlap, the
# order they are consulted in does not decide any answer.
_CALENDAR_BY_LEGACY_HEAD: dict[str, str] = {
    "BRAZIL": "BRAZIL",
    "CANADA": "CANADA",
    "CHINA": "CHINA",
    "DACH": "DACH",
    "ENG": "CANADA",  # ENG_TORONTO, since renamed CA_TORONTO
    "FRANCE": "FRANCE",
    "GULF": "GULF",
    "HI": "INDIA",  # HI_MUMBAI, since renamed IN_MUMBAI
    "INDIA": "INDIA",
    "NORDIC": "DACH",
    "SP": "SPAIN",  # SP_BARCELONA, since renamed ES_MADRID
    "SPAIN": "SPAIN",
    "UK": "UK",  # UK_GBP, since renamed GB_LONDON
    "USA": "US",  # USA_USD
    "ZH": "CHINA",  # ZH_SHANGHAI
}

# The vocabulary the project region picker emits, which is none of the three
# above: not ISO codes, not superseded catalogue heads, and not the spaced
# labels below. frontend/src/features/projects/CreateProjectPage.tsx ships
# REGION_GROUPS as compound CamelCase tokens, so a project created through the
# product carries "GulfStates" or "MiddleEast" rather than "QA" or "Middle East".
#
# That mismatch is why the Gulf week was unreachable from the product's own
# picker while every gate stayed green: the tests walked _CALENDAR_BY_COUNTRY,
# whose ISO codes the picker never emits, so the instrument and the product were
# speaking different vocabularies and neither could see the other.
#
# Only regions whose week actually differs from DEFAULT, or that own a named
# calendar, need an entry. A region with no calendar of its own is left to fall
# through to DEFAULT on purpose: that is the honest answer rather than a
# neighbouring country's week. The gate over this dict's coverage of the shipped
# picker is tests/unit/test_every_shipped_region_option_reaches_a_calendar.py,
# and it reads the picker file rather than a copy of these keys.
#
# Same rule as the dict above: nothing in here may be a two-letter ISO code.
_CALENDAR_BY_PICKER_REGION: dict[str, str] = {
    # "Gulf States" and "Middle East (General)" both carry no country, so both
    # get the week five of the six GCC states work, matching what the spaced
    # "MIDDLE EAST" label below has always answered. The UAE is the one GCC
    # state that does not work it, and it stays reachable by "AE", "AE_DUBAI"
    # and "United Arab Emirates"; a UAE project stored under a region naming the
    # group rather than the country gets Sunday-Thursday from this table, unless
    # its country column says AE, which calendar_region_for prefers to a group.
    "GULFSTATES": "GULF",
    "MIDDLEEAST": "GULF",
    # Not a week change: RU is Monday-Friday and eight hours, exactly DEFAULT.
    # It is here so the badge a Russian project renders reads "Russia" instead
    # of "Standard", because a shipped calendar the picker cannot reach is
    # indistinguishable from one that does not exist.
    "RUSSIA": "RU",
}

# Human-readable region labels that projects carry instead of a code, matched
# by prefix. There is deliberately no bare "UNITED" entry: it used to catch every
# label beginning with that word, so "United Arab Emirates" was given the
# American calendar rather than the Gulf one.
#
# The five Gulf states are named here as well as coded above because the region
# field accepts free text: the picker's "Custom..." option stores whatever the
# user types. "QA" resolved to Sunday-Thursday while "Qatar" fell through to
# Monday-Friday, so the same project got two different weeks depending on which
# form was typed, and the longer, more natural one was the wrong one.
_CALENDAR_BY_LABEL: dict[str, str] = {
    "BAHRAIN": "GULF",
    "KUWAIT": "GULF",
    # "Middle East" carries no country, so it gets the week five of the six GCC
    # states work. The UAE is named in full and is the one that does not.
    "MIDDLE EAST": "GULF",
    "OMAN": "GULF",
    "QATAR": "GULF",
    "SAUDI ARABIA": "GULF",
    "UNITED ARAB EMIRATES": "UAE",
    "UNITED KINGDOM": "UK",
    "UNITED STATES": "US",
}


def get_work_calendar(region: str | None = None) -> dict:
    """Get the work calendar for a region, falling back to DEFAULT.

    A region may be a calendar key ("GULF"), an ISO 3166-1 alpha-2 country code
    or a region id headed by one ("DE_BERLIN"), a superseded catalogue head
    ("ZH_SHANGHAI"), a value the project region picker emits ("GulfStates"), or
    a human-readable label ("United States", "Qatar").

    Args:
        region: The region string stored on a project or a catalogue row.

    Returns:
        The calendar dict, which carries hours_per_day, work_days and label.
        DEFAULT is returned when no calendar in the table is that region's,
        which is the honest answer rather than a neighbouring country's week.
    """
    if not region or not region.strip():
        return WORK_CALENDARS["DEFAULT"]

    normalized = region.strip().upper()

    # A calendar key carried directly.
    calendar = WORK_CALENDARS.get(normalized)
    if calendar:
        return calendar

    # A human-readable label. Longest first, so a label that is a prefix of
    # another can never answer for it.
    for label in sorted(_CALENDAR_BY_LABEL, key=len, reverse=True):
        if normalized.startswith(label):
            return WORK_CALENDARS.get(_CALENDAR_BY_LABEL[label], WORK_CALENDARS["DEFAULT"])

    # Otherwise the head of a region id: "DE_BERLIN" -> "DE".
    head_words = normalized.split("_")[0].split()
    head = head_words[0] if head_words else ""
    mapped = (
        _CALENDAR_BY_COUNTRY.get(head) or _CALENDAR_BY_LEGACY_HEAD.get(head) or _CALENDAR_BY_PICKER_REGION.get(head)
    )
    if mapped:
        return WORK_CALENDARS.get(mapped, WORK_CALENDARS["DEFAULT"])
    return WORK_CALENDARS["DEFAULT"]


def calendar_region_for(region: str | None, country_code: str | None) -> str | None:
    """The string a project's working week is resolved from: its region, or its country.

    A project carries two statements of where it is. ``region`` is free text
    (a city, a picker token, a group label) and ``country_code`` is ISO 3166-1
    alpha-2, filled by the creator, the address, or the country pack active at
    creation. The week used to be read off ``region`` alone, so a project
    created under the Saudi pack with "Riyadh" or nothing in its region was
    planned Monday to Friday while its country column said SA, and every date
    landed on the wrong side of a Sunday-Thursday week.

    The country is decided the way ``_build_rule_sets`` in the BOQ router
    decides it, so the week and the rule sets cannot name two countries for
    one project. A region that names one country wins, whether or not that
    country has a week of its own: "QA" and "DE_BERLIN" keep their weeks, and
    "PL_WARSAW" keeps the standard week even when the country column, filled
    from a Saudi or Indian pack, says otherwise. Only a region that names no
    country ("Riyadh", nothing at all) or a group of countries ("GulfStates",
    "DACH", "Middle East") gives way to the country column, which is then the
    more precise statement: a UAE project filed under the Gulf group works the
    UAE week.

    Args:
        region: ``project.region`` as stored.
        country_code: ``project.country_code`` as stored.

    Returns:
        The string to hand :func:`get_work_calendar`: the region as stored, or
        the ISO code of the country it names when only the code reaches that
        country's week, or the country column.
    """
    country = (country_code or "").strip().upper()
    if len(country) != 2 or not country.isalpha():
        return region
    from app.core.classification_registry import is_macro_region, normalise_region

    if is_macro_region(region):
        return country
    own = get_work_calendar(region)
    if own is not WORK_CALENDARS["DEFAULT"]:
        return region
    named = normalise_region(region)
    if named:
        # The region names a country. Its own spelling is kept where it
        # already reaches that country's week, which is also what the
        # /work-calendar badge echoes back; a spelling only the registry reads
        # ("United_States") is handed on as the code it names.
        return region if get_work_calendar(named) is own else named
    return country


def compute_duration(
    start_date: str,
    end_date: str,
    region: str | None = None,
    *,
    work_weekdays: frozenset[int] | None = None,
    extra_holidays: frozenset[date] | None = None,
) -> int:
    """Calculate working days between two ISO date strings, inclusive.

    ``region`` selects the working week from :data:`WORK_CALENDARS` through
    :func:`get_work_calendar`. Every call site in this module and in the router
    passes the project's region, resolved once per request by
    :meth:`ScheduleService.resolve_project_region`, so a Gulf activity is counted
    Sunday to Thursday and a German one Monday to Friday, on the same week BOQ
    schedule generation draws its dates on. ``None`` resolves to the DEFAULT
    Monday-to-Friday week and is the right answer only when there is no project
    to ask, which is why no caller in the product passes it any more.

    When ``work_weekdays`` or ``extra_holidays`` are supplied (typically from an
    activity-level custom calendar resolved by the progress service), they
    override the region-based working week and supplement the region holidays
    respectively.

    When the resolved calendar carries a ``holidays`` callable (year ->
    set[date]), those dates are skipped even if they fall on a working weekday.
    Currently only CHINA carries one (Spring Festival, Qingming, Dragon Boat,
    Mid-Autumn and the fixed Gregorian holidays).

    Args:
        start_date: ISO date string (e.g. "2026-04-01").
        end_date: ISO date string (e.g. "2026-04-15").
        region: The project's region as stored, in any vocabulary
            :func:`get_work_calendar` accepts: a calendar key ("GULF"), an ISO
            country code ("QA"), a catalogue region id ("DE_BERLIN"), a picker
            token ("GulfStates") or a label ("Saudi Arabia").
        work_weekdays: Override weekday set (0=Mon..6=Sun) from a custom calendar.
        extra_holidays: Additional holiday dates from a custom calendar.

    Returns:
        Number of working days between start and end, inclusive. 0 when either
        date does not parse or the end precedes the start.
    """
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (ValueError, TypeError):
        return 0

    if end < start:
        return 0

    cal = get_work_calendar(region)
    work_days_set = work_weekdays if work_weekdays is not None else cal["work_days"]

    # Collect holiday dates when the calendar provides a holidays callable.
    holiday_func = cal.get("holidays")
    holiday_dates: set[date] = set()
    if holiday_func is not None:
        for y in range(start.year, end.year + 1):
            holiday_dates.update(holiday_func(y))
    if extra_holidays:
        holiday_dates.update(extra_holidays)

    working_days = 0
    current = start
    while current <= end:
        if current.weekday() in work_days_set and current not in holiday_dates:
            working_days += 1
        current += timedelta(days=1)

    return working_days


def _compute_duration_from_cal(start_date: str, end_date: str, cal_data: dict) -> int:
    """Working days between two dates using a resolved calendar dict.

    ``cal_data`` is the ``{"work_days": [int, ...], "exceptions": [str, ...]}``
    shape returned by ``_resolve_activity_calendars``.
    """
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (ValueError, TypeError):
        return 0
    if end < start:
        return 0
    work_days_set = set(cal_data.get("work_days", [0, 1, 2, 3, 4]))
    exception_dates = set()
    for d in cal_data.get("exceptions", []):
        try:
            exception_dates.add(date.fromisoformat(d) if isinstance(d, str) else d)
        except (ValueError, TypeError):
            pass
    working_days = 0
    current = start
    while current <= end:
        if current.weekday() in work_days_set and current not in exception_dates:
            working_days += 1
        current += timedelta(days=1)
    return working_days


def resolve_calendar(schedule: Schedule) -> dict:
    """Resolve the CPM work calendar for a schedule (pure).

    MVP: honour an explicit work-calendar override carried in the schedule
    metadata (``metadata.calendar`` = ``{"work_days": [...], "exceptions":
    [...]}``) when present; otherwise fall back to a Monday-Friday work week
    with no holiday exceptions. Full per-project / per-activity calendar
    resolution (and the calendar-editing UI) is deferred.

    Args:
        schedule: The schedule whose calendar is being resolved. Only its
            ``metadata_`` is read, so the function stays pure and DB-free.

    Returns:
        The ``{"work_days": [...], "exceptions": [...]}`` shape the core CPM
        engine (:func:`app.core.cpm.calculate_cpm`) consumes.
    """
    default_work_days = [0, 1, 2, 3, 4]
    meta = getattr(schedule, "metadata_", None)
    cal = meta.get("calendar") if isinstance(meta, dict) else None
    if isinstance(cal, dict) and cal.get("work_days"):
        work_days = readable_work_days(cal.get("work_days"), source="schedule metadata calendar work days")
        exceptions = readable_exception_dates(cal.get("exceptions"), source="schedule metadata calendar exceptions")
        return {"work_days": work_days or list(default_work_days), "exceptions": exceptions}
    return {"work_days": list(default_work_days), "exceptions": []}


def inclusive_end_from_cpm(early_start: int, early_finish: int, calendar: dict, project_start: date) -> str:
    """Turn a CPM finish offset into the inclusive end date an activity shows.

    The engine's ``early_finish`` is the first day an FS successor may start,
    that is the day after the work. An activity of N working days ends on its
    Nth working day, so the end date is the last working day before that
    offset on the activity's own calendar. Writing ``early_finish`` itself made
    every linked activity end one working day late and put its successor's
    start on the predecessor's end day. A zero-duration activity ends where it
    starts.

    Args:
        early_start: CPM early start, a day offset from ``project_start``.
        early_finish: CPM early finish, a day offset from ``project_start``.
        calendar: ``{"work_days": [...], "exceptions": [...]}``, the calendar
            the engine measured this activity on.
        project_start: The CPM origin date.

    Returns:
        The inclusive end date as an ISO string.
    """
    start = project_start + timedelta(days=int(early_start))
    finish = project_start + timedelta(days=int(early_finish))
    if finish <= start:
        return start.isoformat()
    work_days = set(calendar.get("work_days") or [0, 1, 2, 3, 4])
    exceptions = {d for d in (normalise_exception_date(e) for e in calendar.get("exceptions") or []) if d}
    current = finish - timedelta(days=1)
    while current > start and (current.weekday() not in work_days or current in exceptions):
        current -= timedelta(days=1)
    return current.isoformat()


def _effective_activity_status(
    *,
    stored_status: str,
    progress_pct: float,
    end_date: str | None,
    today: date,
    region: str | None = None,
) -> str:
    """Derive the display status of an activity, flagging overdue ones as "delayed".

    The stored status only ever carries completed / in_progress / not_started
    (set from progress in ``update_progress``). "Delayed" is a temporal overlay
    computed at read time: an activity that is not yet complete and whose planned
    end date is strictly before today is considered delayed. A completed activity
    (or one already at 100 % progress) is never delayed, regardless of dates.

    Args:
        stored_status: The persisted activity status.
        progress_pct: Current progress percentage (0.0 - 100.0).
        end_date: ISO planned end date string (may be empty/None).
        today: Reference date for the overdue comparison.
        region: Optional project region (accepted for calendar consistency).

    Returns:
        The effective status, which may be "delayed" in place of an unfinished
        stored status.
    """
    if stored_status == "completed" or progress_pct >= 100.0:
        return "completed"

    if not end_date:
        return stored_status

    try:
        planned_end = date.fromisoformat(str(end_date)[:10])
    except (ValueError, TypeError):
        return stored_status

    # ``region`` is currently informational; the overdue test is calendar-based
    # (planned end already in the past). Regional holidays would only ever push
    # the delay flag later, never earlier, so a strict past-date check is a safe
    # lower bound that never over-reports.
    _ = region
    if planned_end < today:
        return "delayed"

    return stored_status


# What a generated task's note says about its duration, by where it came from.
_DURATION_NOTE: dict[str, str] = {
    "labor_hours": "from_labor_norm",
    "resource_sum": "from_labor_norm",
    "estimated_fallback": "estimated_from_unit",
    "cost_proportional": "cost_share",
    "default_minimum": "default_duration",
    "spans_works": "spans_works",
}


def _parse_day(value: object) -> date | None:
    """Read the day off an ISO date or timestamp string; ``None`` when there is none."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


# The English of the names and descriptions a generation writes, as in
# backend/locales/en.json under schedule.generated. Used when the catalogue has
# not been loaded (a script, a worker started without the app), so a missing
# catalogue writes English rather than the raw key onto the plan.
_GENERATED_ENGLISH: dict[str, str] = {
    "position_label": "Position {ordinal}",
    "section_label": "Section {ordinal}",
    "task_description": "Auto-generated from BOQ position {ordinal} ({quantity} {unit})",
    "section_description": "Summary: BOQ section {ordinal}",
    "start_milestone": "Project Start",
    "start_milestone_description": "Project kick-off milestone",
    "completion_milestone": "Project Completion",
    "completion_milestone_description": "Project completion milestone",
}


def _generated_text(name: str, **params: object) -> str:
    """A generated name or description in the reader's language (the request locale)."""
    from app.core.i18n import t

    key = f"schedule.generated.{name}"
    text = t(key, **params)
    return _GENERATED_ENGLISH[name].format(**params) if text == key else text


def _format_quantity(quantity: float) -> str:
    """850.0 as "850", 1250.4 as "1250.4": the quantity as the bill shows it."""
    return f"{quantity:.3f}".rstrip("0").rstrip(".")


# The generated milestones a regenerated plan has again, by WBS code.
_GENERATED_MILESTONE_CODES = frozenset({"MS-001", "MS-999"})


def _relink_key(activity: Any) -> tuple | None:
    """What makes an activity "the same one" in a regenerated plan, if anything."""
    meta = activity.metadata_ if isinstance(activity.metadata_, dict) else {}
    if (
        activity.activity_type == "milestone"
        and meta.get("source") == "boq_generation"
        and activity.wbs_code in _GENERATED_MILESTONE_CODES
    ):
        return ("milestone", activity.wbs_code)
    positions = activity.boq_position_ids or []
    if positions:
        return (activity.activity_type, tuple(sorted(str(p) for p in positions)))
    return None


@dataclass
class _BoqGenerationPlan:
    """Everything a generation from a bill writes, worked out before writing."""

    schedule_meta: dict[str, Any]
    boq_name: str
    boq_estimate_type: str | None
    schedule_start: date
    planned_end: str
    requested_end: str | None
    fit: PlanFit
    activities: list[Activity]
    relationships: list[ScheduleRelationship]
    created: list[dict]
    positions_scheduled: int
    workers_per_position: int
    workers_assumed: bool
    # The window the workers were fitted to: the end date asked for, or the
    # default one when none was (``{"days", "end", "default"}``).
    fitted_window: dict[str, Any]
    positions_without_workers: int
    lump_sum_positions: int
    rows_skipped: int
    notes: list[dict[str, Any]]
    note_counts: dict[str, int]
    warnings: list[dict]


class ScheduleService:
    """Business logic for Schedule, Activity, and WorkOrder operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.schedule_repo = ScheduleRepository(session)
        self.activity_repo = ActivityRepository(session)
        self.work_order_repo = WorkOrderRepository(session)
        self.relationship_repo = RelationshipRepository(session)

    # ── Regional working week ──────────────────────────────────────────────

    async def resolve_project_region(self, project_id: uuid.UUID | None) -> str | None:
        """Return the stored region a project's working week is selected by.

        This is the one place the module asks which week a project works.
        Every path that counts or draws dates feeds the answer to
        :func:`get_work_calendar`: ``compute_duration`` in ``create_activity``,
        ``update_activity`` and the ``get_gantt_data`` fallback, BOQ schedule
        generation, the XER and MSP XML imports, and the stats and work-calendar
        routes. Resolving the region in one place is what keeps those paths on
        one week. Before this helper existed the recompute paths passed no
        region and counted Monday to Friday for every project while generation
        counted the regional week.

        Args:
            project_id: The owning project. ``None`` when the caller has no
                project to ask, which nothing the product creates is.

        Returns:
            ``project.region`` as stored, or the project's country code when
            the region names no calendar of its own (see
            :func:`calendar_region_for`), or ``None`` when the project is gone
            or was never given, which :func:`get_work_calendar` reads as the
            DEFAULT Monday-to-Friday week.
        """
        if project_id is None:
            return None
        from app.modules.projects.repository import ProjectRepository

        project = await ProjectRepository(self.session).get_by_id(project_id)
        if project is None:
            return None
        return calendar_region_for(project.region, getattr(project, "country_code", None))

    # ── Schedule operations ────────────────────────────────────────────────

    async def create_schedule(self, data: ScheduleCreate) -> Schedule:
        """Create a new schedule.

        Args:
            data: Schedule creation payload with project_id, name, etc.

        Returns:
            The newly created schedule.
        """
        schedule = Schedule(
            project_id=data.project_id,
            name=data.name,
            schedule_type=data.schedule_type,
            description=data.description,
            start_date=data.start_date,
            end_date=data.end_date,
            status="draft",
            data_date=data.data_date,
            created_by=data.created_by,
            metadata_=data.metadata,
        )
        schedule = await self.schedule_repo.create(schedule)

        await _safe_publish(
            "schedule.schedule.created",
            {"schedule_id": str(schedule.id), "project_id": str(data.project_id)},
            source_module="oe_schedule",
        )

        logger.info("Schedule created: %s (project=%s)", schedule.name, data.project_id)
        return schedule

    async def get_schedule(self, schedule_id: uuid.UUID) -> Schedule:
        """Get schedule by ID. Raises 404 if not found."""
        schedule = await self.schedule_repo.get_by_id(schedule_id)
        if schedule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Schedule not found",
            )
        return schedule

    async def list_schedules_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        archive_state: Literal["current", "archived", "all"] = "current",
    ) -> tuple[list[Schedule], int]:
        """List schedules for a given project with pagination."""
        return await self.schedule_repo.list_for_project(
            project_id, offset=offset, limit=limit, archive_state=archive_state
        )

    async def update_schedule(
        self,
        schedule_id: uuid.UUID,
        data: ScheduleUpdate,
        *,
        actor_payload: dict[str, Any] | None = None,
        restore: bool = False,
    ) -> Schedule:
        """Update schedule metadata fields.

        Args:
            schedule_id: Target schedule identifier.
            data: Partial update payload.

        Returns:
            Updated schedule.

        Raises:
            HTTPException 404 if schedule not found.
        """
        schedule = await self.schedule_repo.get_for_update(schedule_id)
        if schedule is None:
            raise HTTPException(status_code=404, detail="Schedule not found")

        fields = data.model_dump(exclude_unset=True)
        metadata = dict(schedule.metadata_ or {})
        archive = metadata.get("_schedule_archive")
        archive = archive if isinstance(archive, dict) else {}
        prior = archive.get("previous_status")
        valid_prior = prior in ("draft", "active", "completed", "frozen")
        restore_status = prior if valid_prior else "draft"
        target_status = fields.get("status")
        if restore or target_status == "archived" or (schedule.status == "archived" and "status" in fields):
            from app.dependencies import RequirePermission

            await RequirePermission("schedule.delete")(actor_payload or {})
        if restore:
            # A repeated restore must not reset a subsequently edited status.
            if schedule.status != "archived":
                return schedule
            target_status = restore_status
            fields["status"] = target_status
        if schedule.status == "archived" and target_status not in (None, "archived", restore_status):
            raise coded_http_error(
                409,
                "schedule_restore_status_mismatch",
                "Restore the schedule to its previous status first.",
                restore_status=restore_status,
            )
        # Map 'metadata' key to the model's 'metadata_' column. Merge the
        # incoming dict over the stored value so a partial PATCH never drops
        # keys the caller did not resend (json_overwrite data-loss guard).
        if "metadata" in fields:
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(schedule, "metadata_", None), _incoming)
                if isinstance(_incoming, dict)
                else metadata
            )

        if target_status == "archived" and schedule.status != "archived":
            metadata = dict(fields.get("metadata_", metadata))
            metadata["_schedule_archive"] = {
                "previous_status": schedule.status,
                "archived_at": datetime.now(UTC).isoformat(),
                "archived_by": (actor_payload or {}).get("sub"),
            }
            fields["metadata_"] = metadata
        elif schedule.status == "archived" and target_status not in (None, "archived"):
            metadata = dict(fields.get("metadata_", metadata))
            metadata["_schedule_archive"] = {
                **archive,
                "previous_status": restore_status,
                "restored_at": datetime.now(UTC).isoformat(),
                "restore_used_fallback": not valid_prior,
            }
            fields["metadata_"] = metadata

        # When this update advances the data (status) date, freeze an EVM
        # snapshot at the new date so the cost / schedule performance trend
        # accrues automatically. Compare against the value before the write so a
        # PATCH that merely re-sends the same data date does not re-snapshot.
        data_date_advanced = "data_date" in fields and fields["data_date"] and fields["data_date"] != schedule.data_date

        if fields:
            await self.schedule_repo.update_fields(schedule_id, **fields)

            publish_after_commit(
                self.session,
                "schedule.schedule.updated",
                {
                    "schedule_id": str(schedule_id),
                    "project_id": str(schedule.project_id),
                    "fields": list(fields.keys()),
                },
                source_module="oe_schedule",
            )

        if data_date_advanced:
            # Lazy import: the snapshot service imports the progress service,
            # which imports this module - importing it at call time avoids the
            # import cycle. The recording is best-effort and never breaks the
            # schedule write (see ``record_snapshot_safe``).
            from app.modules.schedule.evm_snapshot_service import ScheduleEvmSnapshotService

            await ScheduleEvmSnapshotService(self.session).record_snapshot_safe(schedule_id, fields["data_date"])

        # Re-fetch to return fresh data
        return await self.get_schedule(schedule_id)

    async def delete_impact(self, schedule_id: uuid.UUID) -> dict[str, int]:
        """Count what deleting a schedule takes with it.

        Payment instalments linked to its activities are counted when the
        contracts module is installed; they are not deleted, they lose the
        link and fall back to their contract dates.
        """
        await self.get_schedule(schedule_id)
        activity_count = (await self.activity_repo.list_for_schedule(schedule_id, limit=1))[1]
        baseline_count = await self.schedule_repo.count_baselines(schedule_id)
        payment_milestone_count = 0
        try:
            from app.modules.contracts.models import ContractMilestone
        except ImportError:  # contracts is a module like any other and may be absent
            ContractMilestone = None  # noqa: N806
        if ContractMilestone is not None:
            stmt = select(func.count()).where(ContractMilestone.schedule_id == schedule_id)
            payment_milestone_count = int((await self.session.execute(stmt)).scalar_one())
        return {
            "activity_count": activity_count,
            "baseline_count": baseline_count,
            "payment_milestone_count": payment_milestone_count,
        }

    async def delete_schedule(self, schedule_id: uuid.UUID, *, actor_payload: dict[str, Any]) -> None:
        """Archive through the same guarded path as PATCH; preserve all links."""
        await self.update_schedule(schedule_id, ScheduleUpdate(status="archived"), actor_payload=actor_payload)

    async def restore_schedule(self, schedule_id: uuid.UUID, *, actor_payload: dict[str, Any]) -> Schedule:
        """Restore the recorded status, or explicitly draft for legacy archives."""
        return await self.update_schedule(schedule_id, ScheduleUpdate(), actor_payload=actor_payload, restore=True)

    async def purge_schedule(self, schedule_id: uuid.UUID, *, actor_payload: dict[str, Any]) -> None:
        """Permanently delete an archived schedule; administrator only.

        Raises HTTPException 404 if not found.
        """
        from app.dependencies import RequirePermission, RequireRole

        await RequireRole("admin")(actor_payload)
        await RequirePermission("schedule.purge")(actor_payload)
        schedule = await self.schedule_repo.get_for_update(schedule_id)
        if schedule is None:
            raise HTTPException(status_code=404, detail="Schedule not found")
        if schedule.status != "archived":
            raise coded_http_error(409, "schedule_not_archived", "Archive the schedule before permanently deleting it.")
        project_id = str(schedule.project_id)

        # Baselines hold the schedule id without a foreign key, so nothing
        # cascades to them; without this they outlive the schedule.
        await self.schedule_repo.delete_baselines(schedule_id)
        activity_count = (await self.activity_repo.list_for_schedule(schedule_id, limit=1))[1]
        await self.schedule_repo.delete(schedule_id)

        # The activities go with the schedule; followers of a cleared schedule
        # (payment plan forecasts tied to its milestones) refresh on this.
        publish_after_commit(
            self.session,
            "schedule.activities.cleared",
            {"schedule_id": str(schedule_id), "count": activity_count},
            source_module="oe_schedule",
        )

        # After commit, like the activity deletes: a subscriber that reads the
        # schedule back must not see it still there, nor see an event for a
        # delete that rolled back.
        publish_after_commit(
            self.session,
            "schedule.schedule.deleted",
            {"schedule_id": str(schedule_id), "project_id": project_id},
            source_module="oe_schedule",
        )

        logger.info("Schedule deleted: %s", schedule_id)

    # ── Activity operations ────────────────────────────────────────────────

    async def create_activity(self, data: ActivityCreate, actor_id: str | None = None) -> Activity:
        """Add a new activity to a schedule.

        Auto-calculates duration_days if start_date and end_date are provided.
        Assigns sort_order to place the activity at the end if not specified.

        Args:
            data: Activity creation payload.
            actor_id: The caller. When given, an assignee must be a contact
                the caller can see (admins see all).

        Returns:
            The newly created activity.

        Raises:
            HTTPException 404 if the target schedule doesn't exist.
        """
        # Verify schedule exists
        schedule = await self.get_schedule(data.schedule_id)

        # Auto-compute duration only when the client omitted it (sent explicit
        # null / not provided). An explicit ``duration_days=0`` is respected
        # so callers can create milestones / zero-duration events. The count
        # is on the project's working week, the same one BOQ generation draws
        # dates on, so a Gulf activity is not counted Monday to Friday.
        duration = data.duration_days
        if duration is None and data.start_date and data.end_date:
            region = await self.resolve_project_region(schedule.project_id)
            duration = compute_duration(data.start_date, data.end_date, region)
        if duration is None:
            duration = 0

        outline = await self.activity_repo.list_outline(data.schedule_id)
        if data.parent_id is not None:
            self._assert_parent_in_outline(data.parent_id, outline)
        if data.assignee_id is not None:
            await self._assert_assignee_exists(data.assignee_id, actor_id)

        # A blank code continues the numbering of the section the activity
        # goes into, or the top-level numbering; a typed code is kept as typed
        # but may not repeat one already in use.
        wbs_code = data.wbs_code or suggest_code(data.parent_id, outline)
        if wbs_code:
            self._assert_wbs_code_free(wbs_code, outline)

        # Determine sort_order. Without a section the activity goes last, as
        # before. Under a section it goes right after the section's last
        # descendant, so the flat order every list and export reads keeps the
        # child inside its section instead of at the bottom of the schedule.
        # The id is minted here so the new row can take its place in that
        # order before it exists.
        new_id = uuid.uuid4()
        sort_order = data.sort_order
        reorder: dict[uuid.UUID, int] = {}
        if sort_order == 0:
            if data.parent_id is not None:
                planned = [*outline, (new_id, data.parent_id, _INT32_LAST, wbs_code)]
                changes = sort_order_changes(order_with_block_under(new_id, data.parent_id, planned), planned)
                sort_order = changes.pop(new_id)
                reorder = changes
            else:
                max_order = await self.activity_repo.get_max_sort_order(data.schedule_id)
                sort_order = max_order + 1

        # Auto-generate activity_code if not provided
        activity_code = data.activity_code
        if not activity_code:
            max_seq = await self.activity_repo.get_max_activity_code_seq(data.schedule_id)
            activity_code = f"ACT-{max_seq + 1:03d}"

        # Serialize nested models to dicts for JSON storage
        dependencies_data = [dep.model_dump() for dep in data.dependencies]
        for dep in dependencies_data:
            dep["activity_id"] = str(dep["activity_id"])
        resources_data = [res.model_dump() for res in data.resources]
        boq_ids = [str(pid) for pid in data.boq_position_ids]
        await self._assert_positions_in_project(data.schedule_id, boq_ids)
        await self._assert_activities_in_schedule(data.schedule_id, [d["activity_id"] for d in dependencies_data])

        # Move the other rows only once every check has passed, so a rejected
        # create leaves the order of the schedule alone.
        if reorder:
            await self.activity_repo.bulk_update_fields([{"id": aid, "sort_order": o} for aid, o in reorder.items()])

        activity = Activity(
            id=new_id,
            schedule_id=data.schedule_id,
            parent_id=data.parent_id,
            name=data.name,
            description=data.description,
            wbs_code=wbs_code,
            start_date=data.start_date,
            end_date=data.end_date,
            duration_days=duration,
            progress_pct=str(data.progress_pct),
            status=data.status,
            activity_type=data.activity_type,
            dependencies=dependencies_data,
            resources=resources_data,
            boq_position_ids=boq_ids,
            color=data.color,
            sort_order=sort_order,
            constraint_type=data.constraint_type,
            constraint_date=data.constraint_date,
            activity_code=activity_code,
            bim_element_ids=data.bim_element_ids,
            metadata_=data.metadata,
            cost_planned=data.cost_planned,
            cost_actual=data.cost_actual,
            percent_complete_type=data.percent_complete_type,
            remaining_duration=data.remaining_duration,
            budgeted_units=data.budgeted_units,
            installed_units=data.installed_units,
            assignee_id=data.assignee_id,
        )
        activity = await self.activity_repo.create(activity)
        activity_id = activity.id  # snapshot before update_fields() expires the instance

        # Project the JSON dependency payload into the canonical
        # ScheduleRelationship table, then rebuild Activity.dependencies from
        # those rows so the JSON stays a faithful mirror of the authority. This
        # closes the historical split-brain where create wrote only the JSON.
        if dependencies_data:
            await self._project_dependencies_to_relationships(
                successor_id=activity_id,
                schedule_id=data.schedule_id,
                deps_json=dependencies_data,
            )
            derived = await self._derive_dependencies_json(activity_id)
            await self.activity_repo.update_fields(activity_id, dependencies=derived)

        await _safe_publish(
            "schedule.activity.created",
            {
                "activity_id": str(activity_id),
                "schedule_id": str(data.schedule_id),
                "wbs_code": wbs_code,
            },
            source_module="oe_schedule",
        )

        logger.info("Activity added: %s to schedule %s", data.name, data.schedule_id)
        return await self.get_activity(activity_id)

    @staticmethod
    def _assert_parent_in_outline(
        parent_id: uuid.UUID,
        outline: list[tuple[uuid.UUID, uuid.UUID | None, int, str]],
    ) -> None:
        """Reject a parent that is not an activity of the same schedule.

        ``parent_id`` has no foreign key, so without this a section of another
        schedule (or another project) could be named. Answers 404 for a foreign
        id exactly as for a missing one.
        """
        if not any(act_id == parent_id for act_id, _p, _o, _c in outline):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent activity not found in this schedule",
            )

    @staticmethod
    def _assert_wbs_code_free(
        wbs_code: str,
        outline: list[tuple[uuid.UUID, uuid.UUID | None, int, str]],
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        """Reject a WBS code that another activity of the schedule already uses.

        Enforced here and not as a database constraint on purpose: schedules
        imported or generated before this check can already hold duplicates,
        and a constraint would fail every one of them. Only a code being
        written is checked, so those schedules keep working.
        """
        code = wbs_code.strip()
        if not code:
            return
        for act_id, _p, _o, other in outline:
            if act_id != exclude_id and (other or "").strip() == code:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"WBS code '{code}' is already used by another activity in this schedule",
                )

    async def suggest_wbs_code(self, schedule_id: uuid.UUID, parent_id: uuid.UUID | None) -> str:
        """Suggest the WBS code for a new activity under ``parent_id``.

        Args:
            schedule_id: Target schedule.
            parent_id: The section the activity goes into, or None for the top
                level.

        Returns:
            The next code in that section's sequence, or ``""`` when the
            section has no code of its own to continue.

        Raises:
            HTTPException 404 if the schedule or the parent is not found.
        """
        await self.get_schedule(schedule_id)
        outline = await self.activity_repo.list_outline(schedule_id)
        if parent_id is not None:
            self._assert_parent_in_outline(parent_id, outline)
        return suggest_code(parent_id, outline)

    async def _assert_assignee_exists(self, assignee_id: uuid.UUID, actor_id: str | None = None) -> None:
        """Reject an assignee that is not a live contact the caller can see.

        The activity keeps the id without a foreign key (the contacts module is
        a plugin), so without this a typo or a deleted contact would be stored
        and render as an empty cell forever, and a contact of another tenant
        could be named. The rule is the contacts list's own, shared with the
        task assignee in :mod:`app.modules.contacts.lookup`.

        Raises:
            HTTPException 404 if the contact does not exist or is not the
            caller's; 422 if it has been deactivated.
        """
        from app.modules.contacts.lookup import assignable_contact

        await assignable_contact(self.session, assignee_id, actor_id)

    async def resolve_assignee_names(self, assignee_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Map contact ids to display names in one query.

        The table shows the name from here rather than looking the id up in
        the viewer's own contact list, which holds only that viewer's
        contacts (and only the first page of them), so a colleague's pick
        would otherwise read as unassigned.
        """
        if not assignee_ids:
            return {}
        from app.modules.contacts.models import Contact

        rows = await self.session.execute(
            select(
                Contact.id, Contact.first_name, Contact.last_name, Contact.company_name, Contact.primary_email
            ).where(Contact.id.in_(assignee_ids))
        )
        names: dict[uuid.UUID, str] = {}
        for cid, first, last, company, email in rows.all():
            person = " ".join(p for p in (first, last) if p)
            names[cid] = person or company or email or ""
        return names

    async def get_activity(self, activity_id: uuid.UUID) -> Activity:
        """Get activity by ID. Raises 404 if not found."""
        activity = await self.activity_repo.get_by_id(activity_id)
        if activity is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Activity not found",
            )
        return activity

    async def list_activities_for_schedule(
        self,
        schedule_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 1000,
    ) -> tuple[list[Activity], int]:
        """List activities for a schedule ordered by sort_order."""
        return await self.activity_repo.list_for_schedule(schedule_id, offset=offset, limit=limit)

    async def _reject_dependency_cycles(
        self,
        *,
        activity_id: uuid.UUID,
        schedule_id: uuid.UUID,
        proposed_predecessors: list[uuid.UUID],
    ) -> None:
        """Refuse a proposed dependency edit that would create a cycle.

        Activity-embedded ``dependencies`` are predecessors of *this*
        activity, i.e. each entry represents an edge ``predecessor -> activity_id``.
        Adding a cycle would make CPM compute_paths recurse forever.

        For each proposed predecessor P we check that ``activity_id`` is not
        already reachable from P in the current dependency graph.
        """
        if not proposed_predecessors:
            return

        # Self-reference is the trivial case.
        if any(p == activity_id for p in proposed_predecessors):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail="An activity cannot depend on itself.",
            )

        # Load all activities in the schedule and build adjacency
        # (predecessor -> {successors}) from each activity's stored deps.
        existing_activities, _total = await self.activity_repo.list_for_schedule(
            schedule_id,
            limit=10_000,
        )
        adjacency: dict[uuid.UUID, set[uuid.UUID]] = {}
        for act in existing_activities:
            for dep in act.dependencies or []:
                try:
                    pred_id = uuid.UUID(str(dep.get("activity_id")))
                except (TypeError, ValueError):
                    continue
                adjacency.setdefault(pred_id, set()).add(act.id)

        # Pre-compute the reachability set from ``activity_id`` ONCE for
        # this mutation request. Adding ``P -> activity_id`` closes a cycle
        # iff P is transitively reachable from ``activity_id`` in the
        # current graph. The naive previous version re-ran a BFS per
        # proposed predecessor (O(P × V)); a single traversal is O(V+E).
        reachable_from_activity: set[uuid.UUID] = set()
        stack: list[uuid.UUID] = list(adjacency.get(activity_id, set()))
        while stack:
            current = stack.pop()
            if current in reachable_from_activity:
                continue
            reachable_from_activity.add(current)
            for successor in adjacency.get(current, ()):
                if successor not in reachable_from_activity:
                    stack.append(successor)

        # Now every proposed predecessor is a hash-set membership test.
        for predecessor in proposed_predecessors:
            if predecessor in reachable_from_activity:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Adding this dependency would create a circular "
                        "reference. Check the dependency chain for cycles."
                    ),
                )

    # ── Canonical dependency store (ScheduleRelationship) ───────────────────
    # ScheduleRelationship is the SINGLE source of truth for dependency edges.
    # Activity.dependencies (JSON) is a DERIVED mirror, always rebuilt from the
    # canonical rows. The three helpers below keep the two in lock-step inside
    # the calling transaction:
    #   * _project_dependencies_to_relationships - write a JSON edge payload
    #     into the canonical table (create / update / delete rows to match).
    #   * _derive_dependencies_json - read the canonical rows for one activity
    #     and produce the JSON mirror shape stored on Activity.dependencies.
    #   * _assert_predecessors_complete - completion guard, reads canonical
    #     predecessors only.

    @staticmethod
    def _edge_payload_from_json(deps: list[dict] | None) -> dict[uuid.UUID, tuple[str, int]]:
        """Map a JSON dependency payload to ``predecessor_id -> (type, lag)``.

        ``deps`` is the activity-embedded predecessor list. Entries that are
        not valid UUIDs are skipped. The last occurrence of a duplicate
        predecessor wins, matching the unique (predecessor, successor) DB
        constraint on :class:`ScheduleRelationship`.
        """
        edges: dict[uuid.UUID, tuple[str, int]] = {}
        for dep in deps or []:
            if not isinstance(dep, dict):
                continue
            try:
                pred_id = uuid.UUID(str(dep.get("activity_id")))
            except (TypeError, ValueError):
                continue
            dep_type = str(dep.get("type") or "FS").upper()
            try:
                lag = int(dep.get("lag_days") or 0)
            except (TypeError, ValueError):
                lag = 0
            edges[pred_id] = (dep_type, lag)
        return edges

    async def _project_dependencies_to_relationships(
        self,
        *,
        successor_id: uuid.UUID,
        schedule_id: uuid.UUID,
        deps_json: list[dict] | None,
    ) -> None:
        """Project an activity's JSON dependency payload into the canonical table.

        Creates rows for new predecessors, updates type/lag on changed ones,
        and deletes rows for predecessors no longer present so a removed edge
        truly disappears from CPM. Idempotent: re-projecting the same payload
        leaves the table unchanged.

        Args:
            successor_id: The activity these edges point *into*.
            schedule_id: The owning schedule (stamped on each new row).
            deps_json: The activity-embedded predecessor list (each entry is an
                edge ``predecessor -> successor_id``). ``None`` is treated as an
                empty set, which clears all inbound canonical edges.
        """
        desired = self._edge_payload_from_json(deps_json)

        existing = await self.relationship_repo.list_predecessors(successor_id)
        existing_by_pred: dict[uuid.UUID, ScheduleRelationship] = {r.predecessor_id: r for r in existing}

        # Delete edges that are no longer desired.
        stale = [pred for pred in existing_by_pred if pred not in desired]
        await self.relationship_repo.delete_edges(successor_id, stale)

        # Create or update the remaining desired edges.
        for pred_id, (dep_type, lag) in desired.items():
            row = existing_by_pred.get(pred_id)
            if row is None:
                await self.relationship_repo.create(
                    ScheduleRelationship(
                        schedule_id=schedule_id,
                        predecessor_id=pred_id,
                        successor_id=successor_id,
                        relationship_type=dep_type,
                        lag_days=lag,
                    )
                )
            elif (row.relationship_type or "FS").upper() != dep_type or (row.lag_days or 0) != lag:
                await self.relationship_repo.update_edge(
                    row.id,
                    relationship_type=dep_type,
                    lag_days=lag,
                )

    async def _derive_dependencies_json(self, successor_id: uuid.UUID) -> list[dict]:
        """Rebuild the derived JSON mirror from the canonical relationship rows.

        Returns the ``Activity.dependencies`` shape (``[{activity_id, type,
        lag_days}, ...]``) sourced from :class:`ScheduleRelationship` so the
        convenience field always agrees with the authority.
        """
        rows = await self.relationship_repo.list_predecessors(successor_id)
        return [
            {
                "activity_id": str(r.predecessor_id),
                "type": (r.relationship_type or "FS").upper(),
                "lag_days": r.lag_days or 0,
            }
            for r in rows
        ]

    async def _assert_predecessors_complete(self, activity_id: uuid.UUID) -> None:
        """Reject completing an activity while a predecessor is still open.

        Mirrors the dependency guard ``tasks.complete_task`` enforces: reads the
        canonical predecessor edges of ``activity_id`` and raises HTTP 409 with
        a message naming every blocking (not-yet-completed) predecessor.

        Args:
            activity_id: The activity being marked completed.

        Raises:
            HTTPException 409 if any predecessor activity is not completed.
        """
        rows = await self.relationship_repo.list_predecessors(activity_id)
        if not rows:
            return

        pred_ids = {r.predecessor_id for r in rows}
        pred_stmt = select(Activity).where(Activity.id.in_(pred_ids))
        result = await self.session.execute(pred_stmt)
        predecessors = list(result.scalars().all())

        blocking: list[str] = []
        for pred in predecessors:
            progress = _str_to_float(pred.progress_pct)
            if pred.status != "completed" and progress < 100.0:
                blocking.append(pred.name or str(pred.id))

        if blocking:
            names = ", ".join(f"'{name}'" for name in sorted(blocking))
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot complete: blocked by {len(blocking)} predecessor "
                    f"activity(ies) that are not yet completed: {names}. Complete them first."
                ),
            )

    async def reconcile_dependency_sources(self, schedule_id: uuid.UUID) -> dict[str, int]:
        """Reconcile the split-brain dependency stores for a schedule.

        Backfill / repair helper. Historically dependency edges were written to
        either ``Activity.dependencies`` (JSON) OR :class:`ScheduleRelationship`
        (table) depending on which endpoint was used, so the two can drift. This
        unifies them around the canonical table:

          1. Every JSON edge that has no canonical row is inserted into the
             table (the JSON copy is preserved as the seed of truth on first
             run, since it was historically the only writer for PATCH activity).
          2. Each activity's ``dependencies`` JSON is then rebuilt from the
             (now unified) canonical rows so the mirror is byte-consistent.

        The central migration calls this once per existing schedule. It is
        idempotent: a second run makes no changes.

        Args:
            schedule_id: Schedule to reconcile.

        Returns:
            Counts ``{"edges_created": int, "activities_resynced": int}``.
        """
        activities, _ = await self.activity_repo.list_for_schedule(schedule_id, limit=10_000)
        active_ids = {a.id for a in activities}

        existing_rels = await self.relationship_repo.list_for_schedule(schedule_id)
        canonical_pairs: set[tuple[uuid.UUID, uuid.UUID]] = {(r.predecessor_id, r.successor_id) for r in existing_rels}

        edges_created = 0
        # 1. Promote orphan JSON edges into the canonical table.
        for act in activities:
            for pred_id, (dep_type, lag) in self._edge_payload_from_json(act.dependencies).items():
                if pred_id not in active_ids:
                    continue  # dangling reference to a deleted activity - drop
                pair = (pred_id, act.id)
                if pair in canonical_pairs:
                    continue
                await self.relationship_repo.create(
                    ScheduleRelationship(
                        schedule_id=schedule_id,
                        predecessor_id=pred_id,
                        successor_id=act.id,
                        relationship_type=dep_type,
                        lag_days=lag,
                    )
                )
                canonical_pairs.add(pair)
                edges_created += 1

        # 2. Rebuild every activity's JSON mirror from the unified canonical set.
        activities_resynced = 0
        for act in activities:
            derived = await self._derive_dependencies_json(act.id)
            current = self._edge_payload_from_json(act.dependencies)
            desired = self._edge_payload_from_json(derived)
            if current != desired:
                await self.activity_repo.update_fields(act.id, dependencies=derived)
                activities_resynced += 1

        logger.info(
            "Reconciled dependency sources for schedule %s: edges_created=%d, activities_resynced=%d",
            schedule_id,
            edges_created,
            activities_resynced,
        )
        return {"edges_created": edges_created, "activities_resynced": activities_resynced}

    async def update_activity(
        self, activity_id: uuid.UUID, data: ActivityUpdate, actor_id: str | None = None
    ) -> Activity:
        """Update an activity and recalculate duration if dates changed.

        Moving the activity to another section (``parent_id``, or an explicit
        null for the top level) also moves it, with its own children, to the
        end of that section in the flat order, unless ``sort_order`` is sent.

        Args:
            activity_id: Target activity identifier.
            data: Partial update payload.
            actor_id: The caller. When given, a new assignee must be a
                contact the caller can see (admins see all).

        Returns:
            Updated activity.

        Raises:
            HTTPException 404 if activity not found.
        """
        activity = await self.get_activity(activity_id)

        # Capture the pre-update values the transition checks and the event
        # below compare against, so neither reloads the activity afterwards
        # (MissingGreenlet on the async session).
        schedule_id = activity.schedule_id
        schedule_id_str = str(schedule_id)
        current_progress = _str_to_float(activity.progress_pct)
        current_status = activity.status

        fields = data.model_dump(exclude_unset=True)

        # The assignee is checked only when it changes to a new contact, and
        # the code only when it changes to a new value: clients resend
        # unchanged fields, and schedules from before the uniqueness check can
        # hold duplicate codes that must stay editable.
        if fields.get("assignee_id") is not None and fields["assignee_id"] != activity.assignee_id:
            await self._assert_assignee_exists(fields["assignee_id"], actor_id)
        new_code = (fields.get("wbs_code") or "").strip()
        new_parent = fields.get("parent_id")
        code_changes = bool(new_code) and new_code != (activity.wbs_code or "").strip()
        parent_changes = "parent_id" in fields and new_parent != activity.parent_id
        reorder: dict[uuid.UUID, int] = {}
        if code_changes or parent_changes:
            outline = await self.activity_repo.list_outline(schedule_id)
            if parent_changes and new_parent is not None:
                self._assert_parent_in_outline(new_parent, outline)
                if new_parent in subtree_ids(activity_id, outline):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail="An activity cannot be moved under itself or one of its own children",
                    )
            if code_changes:
                self._assert_wbs_code_free(new_code, outline, exclude_id=activity_id)
            if parent_changes and "sort_order" not in fields:
                planned = [
                    (aid, new_parent if aid == activity_id else pid, order, code) for aid, pid, order, code in outline
                ]
                reorder = sort_order_changes(order_with_block_under(activity_id, new_parent, planned), planned)

        # Convert float values to strings for storage
        if "progress_pct" in fields:
            fields["progress_pct"] = str(fields["progress_pct"])

        # Track whether this update transitions the activity to completed so we
        # can enforce the predecessor-completion guard before persisting.
        new_progress = float(fields["progress_pct"]) if "progress_pct" in fields else current_progress
        new_status = fields.get("status", current_status)
        becomes_completed = new_status == "completed" or new_progress >= 100.0
        was_completed = current_status == "completed" or current_progress >= 100.0

        # Serialize nested models. ``dependencies`` is projected into the
        # canonical ScheduleRelationship table after the field write; the JSON
        # value here is recomputed from the canonical rows afterwards so it
        # never becomes a competing authority.
        deps_payload: list[dict] | None = None
        if "dependencies" in fields and fields["dependencies"] is not None:
            deps = fields["dependencies"]
            serialized = []
            for dep in deps:
                d = dep.model_dump() if hasattr(dep, "model_dump") else dep
                d["activity_id"] = str(d["activity_id"])
                serialized.append(d)
            fields["dependencies"] = serialized
            deps_payload = serialized

            # Reject self-references and circular dependencies before write.
            # ``ScheduleRelationship.create_relationship`` enforces this for
            # the typed-relationship table; the activity-embedded JSON
            # ``dependencies`` field used to bypass it. Both writers must
            # apply the same guard or one path becomes a back door.
            await self._assert_activities_in_schedule(schedule_id, [d["activity_id"] for d in serialized])
            await self._reject_dependency_cycles(
                activity_id=activity_id,
                schedule_id=schedule_id,
                proposed_predecessors=[uuid.UUID(d["activity_id"]) for d in serialized],
            )

        if "resources" in fields and fields["resources"] is not None:
            res_list = fields["resources"]
            fields["resources"] = [r.model_dump() if hasattr(r, "model_dump") else r for r in res_list]

        if "boq_position_ids" in fields and fields["boq_position_ids"] is not None:
            fields["boq_position_ids"] = [str(pid) for pid in fields["boq_position_ids"]]
            # Only ids this write adds are checked, so resending a list that
            # already holds an older link does not fail on it.
            already = {str(pid) for pid in (activity.boq_position_ids or [])}
            await self._assert_positions_in_project(
                schedule_id, [pid for pid in fields["boq_position_ids"] if pid not in already]
            )

        # Map 'metadata' key to the model's 'metadata_' column. Merge the
        # incoming dict over the stored value so a partial PATCH never drops
        # keys the caller did not resend (json_overwrite data-loss guard).
        if "metadata" in fields:
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(activity, "metadata_", None), _incoming)
                if isinstance(_incoming, dict)
                else _incoming
            )

        # Recalculate duration if dates changed. Use the activity's own
        # calendar when assigned, falling back to the project's regional week.
        new_start = fields.get("start_date", activity.start_date)
        new_end = fields.get("end_date", activity.end_date)
        if "start_date" in fields or "end_date" in fields:
            schedule = await self.get_schedule(schedule_id)
            cal_id = getattr(activity, "calendar_id", None)
            if cal_id:
                cal_map = await self._resolve_activity_calendars([activity], schedule.project_id)
                cal_data = cal_map.get(str(activity_id))
            else:
                cal_data = None
            if cal_data:
                fields["duration_days"] = _compute_duration_from_cal(new_start, new_end, cal_data)
            else:
                region = await self.resolve_project_region(schedule.project_id)
                fields["duration_days"] = compute_duration(new_start, new_end, region)

        # Completion guard (mirrors tasks.complete_task): reject the transition
        # to completed while any canonical predecessor is still open. Skipped
        # when the activity was already completed (idempotent re-saves) so we
        # never block a no-op edit of a finished activity. Run before write.
        if becomes_completed and not was_completed:
            await self._assert_predecessors_complete(activity_id)

        if fields:
            await self.activity_repo.update_fields(activity_id, **fields)

            # After the commit: the payment plan recomputes forecasts from the
            # new dates in its own session, which cannot see them before then.
            publish_after_commit(
                self.session,
                "schedule.activity.updated",
                {
                    "activity_id": str(activity_id),
                    "schedule_id": schedule_id_str,
                    "fields": list(fields.keys()),
                },
                source_module="oe_schedule",
            )

        # Project the (validated) dependency payload into the canonical store,
        # then rebuild the JSON mirror from those rows. Done after the field
        # write so a deleted edge truly disappears from CPM.
        if deps_payload is not None:
            await self._project_dependencies_to_relationships(
                successor_id=activity_id,
                schedule_id=schedule_id,
                deps_json=deps_payload,
            )
            derived = await self._derive_dependencies_json(activity_id)
            await self.activity_repo.update_fields(activity_id, dependencies=derived)

        # Last, because the bulk write expires every loaded instance and the
        # code above still reads ``activity``.
        if reorder:
            await self.activity_repo.bulk_update_fields([{"id": aid, "sort_order": o} for aid, o in reorder.items()])

        # Re-fetch to return fresh data
        refreshed = await self.get_activity(activity_id)
        await announce_if_milestone_reached(self.session, refreshed, was_completed=was_completed, actor_id=actor_id)
        return refreshed

    async def delete_activity(self, activity_id: uuid.UUID, *, cascade: bool = False) -> int:
        """Delete an activity.

        A summary's children move up one level by default. With ``cascade``
        they go too, at every depth. One activity is announced on its own; a
        branch is announced once for the activity deleted and once for the
        schedule, so whatever follows any of it (a payment instalment linked to
        a milestone inside the summary) lets go of it without one event per
        activity.

        The activity's inbound/outbound canonical :class:`ScheduleRelationship`
        rows are removed by the ON DELETE CASCADE FKs, but the derived
        ``dependencies`` JSON mirror on *surviving successor* activities would
        otherwise keep listing the deleted predecessor - a dangling pointer that
        ``get_gantt_data`` returns verbatim (drawing a dependency arrow to a node
        that no longer exists). Strip the deleted activity from every successor's
        JSON mirror so the two stores stay consistent without waiting for a later
        ``reconcile_dependency_sources`` pass.

        Returns:
            How many activities were removed.

        Raises HTTPException 404 if not found.
        """
        activity = await self.get_activity(activity_id)
        schedule_uuid = activity.schedule_id
        schedule_id = str(schedule_uuid)
        parent_of_deleted = activity.parent_id

        if cascade:
            doomed = await self.activity_repo.delete_subtree(schedule_uuid, activity_id)
        else:
            # A deleted summary's children move up one level, under its own
            # parent, rather than falling to the top of the plan (the FK alone
            # would null their parent).
            await self.activity_repo.reparent_children(activity_id, parent_of_deleted)
            await self.activity_repo.delete(activity_id)
            doomed = [activity_id]
        doomed_str = {str(d) for d in doomed}

        # Rebuild the JSON mirror on each affected successor. The canonical edge
        # is already gone via the relationship CASCADE; here we keep the derived
        # copy in lockstep.
        for succ_id, deps in await self.activity_repo.dependency_mirrors(schedule_uuid):
            pruned = [d for d in deps if not (isinstance(d, dict) and str(d.get("activity_id")) in doomed_str)]
            if len(pruned) != len(deps):
                await self.activity_repo.update_fields(succ_id, dependencies=pruned)

        publish_after_commit(
            self.session,
            "schedule.activity.deleted",
            {"activity_id": str(activity_id), "schedule_id": schedule_id, "removed_count": len(doomed)},
            source_module="oe_schedule",
        )
        if len(doomed) > 1:
            # What was under it goes in the same breath: one schedule-level
            # event, on which contracts refreshes every instalment of the
            # schedule and unlinks those whose milestone went with the branch.
            publish_after_commit(
                self.session,
                "schedule.activities.cleared",
                {"schedule_id": schedule_id, "count": len(doomed), "root_activity_id": str(activity_id)},
                source_module="oe_schedule",
            )

        logger.info("Activity deleted: %s from schedule %s (%d removed)", activity_id, schedule_id, len(doomed))
        return len(doomed)

    async def clear_activities(self, schedule_id: uuid.UUID) -> int:
        """Delete every activity (and its work orders) of a schedule at once.

        Used by the schedule "Reset" action. Replaces an N+1 per-activity
        delete loop with a single bulk statement.

        Args:
            schedule_id: Target schedule whose activities are cleared.

        Returns:
            The number of activities removed.

        Raises:
            HTTPException 404 if the schedule does not exist.
        """
        await self.get_schedule(schedule_id)

        deleted = await self.activity_repo.delete_for_schedule(schedule_id)

        publish_after_commit(
            self.session,
            "schedule.activities.cleared",
            {"schedule_id": str(schedule_id), "count": deleted},
            source_module="oe_schedule",
        )

        logger.info("Cleared %d activity(ies) from schedule %s", deleted, schedule_id)
        return deleted

    async def _assert_activities_in_schedule(self, schedule_id: uuid.UUID, activity_ids: list[str]) -> None:
        """Reject dependency ids that are not activities of this schedule.

        A predecessor named in an activity's ``dependencies`` becomes a
        canonical edge, and the edge feeds CPM and the Gantt. An id from
        another schedule (another project, another tenant) would join two
        plans that share no access rule, so it answers 404 exactly like an
        unknown id, and nothing is written.
        """
        wanted: set[uuid.UUID] = set()
        for raw in activity_ids:
            try:
                wanted.add(uuid.UUID(str(raw)))
            except (TypeError, ValueError):
                wanted.add(uuid.uuid5(uuid.NAMESPACE_OID, str(raw)))  # matches no row
        if not wanted:
            return
        if await self.activity_repo.ids_in_schedule(schedule_id, wanted) != wanted:
            raise coded_http_error(
                status.HTTP_404_NOT_FOUND,
                "schedule_activity_not_in_schedule",
                "Both activities of a dependency must belong to this schedule.",
            )

    async def _assert_positions_in_project(self, schedule_id: uuid.UUID, position_ids: list[str]) -> None:
        """Reject BOQ positions that are not in the schedule's own project.

        The activity keeps position ids as a JSON list with no foreign key, so
        without this a link could name a position of another project, and the
        schedule would then read that project's quantities and money. Answers
        404 for a foreign id exactly as for a missing one, so a caller cannot
        probe which ids exist elsewhere.

        Args:
            schedule_id: The schedule the activity belongs to.
            position_ids: Position ids about to be linked.

        Raises:
            HTTPException 404 if any id is not a position of that project.
        """
        if not position_ids:
            return
        from app.modules.boq.models import BOQ, Position

        schedule = await self.get_schedule(schedule_id)
        wanted: set[uuid.UUID] = set()
        for pid in position_ids:
            try:
                wanted.add(uuid.UUID(str(pid)))
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ position not found") from exc
        rows = await self.session.execute(
            select(Position.id)
            .join(BOQ, BOQ.id == Position.boq_id)
            .where(Position.id.in_(wanted))
            .where(BOQ.project_id == schedule.project_id)
        )
        found = set(rows.scalars().all())
        if wanted - found:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOQ position not found in this project",
            )

    async def link_boq_position(self, activity_id: uuid.UUID, boq_position_id: uuid.UUID) -> Activity:
        """Link a BOQ position to an activity.

        Args:
            activity_id: Target activity identifier.
            boq_position_id: BOQ position UUID to link.

        Returns:
            Updated activity with the new position linked.

        Raises:
            HTTPException 404 if activity not found.
            HTTPException 409 if position is already linked.
        """
        activity = await self.get_activity(activity_id)

        position_str = str(boq_position_id)
        current_ids: list[str] = list(activity.boq_position_ids or [])

        if position_str in current_ids:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="BOQ position is already linked to this activity",
            )

        await self._assert_positions_in_project(activity.schedule_id, [position_str])
        current_ids.append(position_str)
        await self.activity_repo.update_fields(activity_id, boq_position_ids=current_ids)

        await _safe_publish(
            "schedule.activity.position_linked",
            {
                "activity_id": str(activity_id),
                "boq_position_id": position_str,
            },
            source_module="oe_schedule",
        )

        logger.info("BOQ position %s linked to activity %s", boq_position_id, activity_id)
        return await self.get_activity(activity_id)

    async def unlink_boq_position(self, activity_id: uuid.UUID, boq_position_id: uuid.UUID) -> Activity:
        """Unlink a BOQ position from an activity.

        Args:
            activity_id: Target activity identifier.
            boq_position_id: BOQ position UUID to unlink.

        Returns:
            Updated activity with the position removed.

        Raises:
            HTTPException 404 if activity not found or position not linked.
        """
        activity = await self.get_activity(activity_id)

        position_str = str(boq_position_id)
        current_ids: list[str] = list(activity.boq_position_ids or [])

        if position_str not in current_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOQ position is not linked to this activity",
            )

        current_ids.remove(position_str)
        await self.activity_repo.update_fields(activity_id, boq_position_ids=current_ids)

        await _safe_publish(
            "schedule.activity.position_unlinked",
            {
                "activity_id": str(activity_id),
                "boq_position_id": position_str,
            },
            source_module="oe_schedule",
        )

        logger.info("BOQ position %s unlinked from activity %s", boq_position_id, activity_id)
        return await self.get_activity(activity_id)

    async def update_progress(
        self, activity_id: uuid.UUID, progress_pct: float, actor_id: str | None = None
    ) -> Activity:
        """Update activity progress and auto-adjust status.

        Args:
            activity_id: Target activity identifier.
            progress_pct: New progress percentage (0.0 - 100.0).
            actor_id: The caller, named in a milestone-reached event.

        Returns:
            Updated activity.

        Raises:
            HTTPException 404 if activity not found.
            HTTPException 409 if completing while a predecessor is still open.
        """
        activity = await self.get_activity(activity_id)
        was_completed = activity.status == "completed" or _str_to_float(activity.progress_pct) >= 100.0

        # Determine status from progress
        if progress_pct >= 100.0:
            new_status = "completed"
        elif progress_pct > 0.0:
            new_status = "in_progress"
        else:
            new_status = "not_started"

        # Completion guard (mirrors tasks.complete_task): block reaching 100 %
        # while any canonical predecessor is still open. Skipped when already
        # completed so re-saving a finished activity is a no-op, not a 409.
        if new_status == "completed" and not was_completed:
            await self._assert_predecessors_complete(activity_id)

        await self.activity_repo.update_fields(
            activity_id,
            progress_pct=str(progress_pct),
            status=new_status,
        )

        # Deferred to the commit: the EVM snapshot subscriber reads this
        # activity's schedule and its siblings from its own session, and a
        # save that fails after this point must not leave a snapshot behind.
        publish_after_commit(
            self.session,
            "schedule.activity.progress_updated",
            {
                "activity_id": str(activity_id),
                "progress_pct": progress_pct,
                "status": new_status,
            },
            source_module="oe_schedule",
        )

        logger.info("Activity %s progress updated to %.1f%%", activity_id, progress_pct)

        # Roll up progress to parent summary if this activity has one.
        if activity.parent_id:
            await self._rollup_summary_progress(activity.parent_id)

        refreshed = await self.get_activity(activity_id)
        await announce_if_milestone_reached(self.session, refreshed, was_completed=was_completed, actor_id=actor_id)
        return refreshed

    async def _rollup_summary_progress(self, summary_id: uuid.UUID, _depth: int = 0) -> None:
        """Recompute a summary activity's progress as the duration-weighted mean of its children.

        Recurses up the ancestor chain so that updating a leaf under a
        nested summary propagates all the way to the root.  Depth is
        capped at 20 to prevent infinite loops if the data has a cycle.
        """
        if _depth > 20:
            return

        children = (
            await self.session.execute(
                select(Activity.progress_pct, Activity.duration_days).where(Activity.parent_id == summary_id)
            )
        ).all()
        if not children:
            return

        total_weight = 0.0
        weighted_sum = 0.0
        for pct_str, dur in children:
            weight = max(dur, 1)
            weighted_sum += _str_to_float(pct_str) * weight
            total_weight += weight
        rolled_up = weighted_sum / total_weight if total_weight > 0 else 0.0

        if rolled_up >= 100.0:
            new_status = "completed"
        elif rolled_up > 0:
            new_status = "in_progress"
        else:
            new_status = "not_started"

        await self.activity_repo.update_fields(
            summary_id,
            progress_pct=str(round(rolled_up, 1)),
            status=new_status,
        )

        # Recurse to grandparent if this summary itself has a parent.
        parent_row = (
            await self.session.execute(select(Activity.parent_id).where(Activity.id == summary_id))
        ).scalar_one_or_none()
        if parent_row:
            await self._rollup_summary_progress(parent_row, _depth + 1)

    # ── BIM ↔ Activity linking ─────────────────────────────────────────────

    async def update_bim_links(
        self,
        activity_id: uuid.UUID,
        bim_element_ids: list[str],
        *,
        add: bool = False,
    ) -> Activity:
        """Replace, or add to, the BIM element link set on an activity.

        Args:
            activity_id: Target activity identifier.
            bim_element_ids: BIM element UUIDs (as strings). Without ``add``
                they become the whole stored list.
            add: Merge the ids into the stored list instead, keeping its
                order and skipping ids already there.

        Returns:
            The updated activity (re-fetched from the database).

        Raises:
            HTTPException 404 if the activity does not exist.
        """
        activity = await self.get_activity(activity_id)
        schedule_id_str = str(activity.schedule_id)

        # Normalise to a list of plain strings so we never write a dict to
        # the JSON column (legacy values may have been dict-shaped).
        normalised = [str(eid) for eid in bim_element_ids]
        if add:
            stored = [str(eid) for eid in (activity.bim_element_ids or []) if not isinstance(eid, dict)]
            known = set(stored)
            normalised = stored + [eid for eid in dict.fromkeys(normalised) if eid not in known]

        await self.activity_repo.update_fields(
            activity_id,
            bim_element_ids=normalised,
        )

        await _safe_publish(
            "schedule.activity.bim_links_updated",
            {
                "activity_id": str(activity_id),
                "schedule_id": schedule_id_str,
                "bim_element_ids": normalised,
                "count": len(normalised),
            },
            source_module="oe_schedule",
        )

        logger.info(
            "Activity %s BIM links replaced (%d element(s))",
            activity_id,
            len(normalised),
        )
        return await self.get_activity(activity_id)

    async def get_activities_for_bim_element(
        self,
        bim_element_id: str,
        project_id: uuid.UUID,
    ) -> list[Activity]:
        """Return all activities in ``project_id`` that reference ``bim_element_id``.

        The ``bim_element_ids`` JSON column is stored as a plain list so we
        filter on the Python side (works across SQLite and PostgreSQL without
        a dialect-specific JSON contains operator). Scoping by project keeps
        the scan bounded.
        """
        target = str(bim_element_id)

        stmt = (
            select(Activity)
            .join(Schedule, Activity.schedule_id == Schedule.id)
            .where(Schedule.project_id == project_id)
            .where(Activity.bim_element_ids.isnot(None))
            .options(
                noload(Activity.children),
                noload(Activity.work_orders),
            )
            .order_by(*activity_order_terms())
        )
        result = await self.session.execute(stmt)
        candidates = list(result.scalars().all())

        matched: list[Activity] = []
        for act in candidates:
            raw = act.bim_element_ids
            # Legacy dict-shaped values are treated as empty.
            if isinstance(raw, list):
                if target in (str(eid) for eid in raw):
                    matched.append(act)
        return matched

    # ── Work Order operations ──────────────────────────────────────────────

    async def create_work_order(self, data: WorkOrderCreate) -> WorkOrder:
        """Create a new work order for an activity.

        Args:
            data: Work order creation payload.

        Returns:
            The newly created work order.

        Raises:
            HTTPException 404 if the target activity doesn't exist.
        """
        # Verify activity exists
        await self.get_activity(data.activity_id)

        work_order = WorkOrder(
            activity_id=data.activity_id,
            assembly_id=data.assembly_id,
            boq_position_id=data.boq_position_id,
            code=data.code,
            description=data.description,
            assigned_to=data.assigned_to,
            planned_start=data.planned_start,
            planned_end=data.planned_end,
            actual_start=data.actual_start,
            actual_end=data.actual_end,
            planned_cost=str(data.planned_cost),
            actual_cost=str(data.actual_cost),
            status=data.status,
            metadata_=data.metadata,
        )
        work_order = await self.work_order_repo.create(work_order)

        await _safe_publish(
            "schedule.work_order.created",
            {
                "work_order_id": str(work_order.id),
                "activity_id": str(data.activity_id),
                "code": data.code,
            },
            source_module="oe_schedule",
        )

        logger.info("Work order created: %s for activity %s", data.code, data.activity_id)
        return work_order

    async def get_work_order(self, work_order_id: uuid.UUID) -> WorkOrder:
        """Get work order by ID. Raises 404 if not found."""
        work_order = await self.work_order_repo.get_by_id(work_order_id)
        if work_order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Work order not found",
            )
        return work_order

    async def list_work_orders_for_activity(
        self,
        activity_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[WorkOrder], int]:
        """List work orders for an activity."""
        return await self.work_order_repo.list_for_activity(activity_id, offset=offset, limit=limit)

    async def list_work_orders_for_schedule(
        self,
        schedule_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 500,
    ) -> tuple[list[WorkOrder], int]:
        """List all work orders across all activities in a schedule."""
        return await self.work_order_repo.list_for_schedule(schedule_id, offset=offset, limit=limit)

    async def update_work_order(self, work_order_id: uuid.UUID, data: WorkOrderUpdate) -> WorkOrder:
        """Update a work order.

        Args:
            work_order_id: Target work order identifier.
            data: Partial update payload.

        Returns:
            Updated work order.

        Raises:
            HTTPException 404 if work order not found.
        """
        work_order = await self.get_work_order(work_order_id)

        fields = data.model_dump(exclude_unset=True)

        # Convert float values to strings for storage
        if "planned_cost" in fields:
            fields["planned_cost"] = str(fields["planned_cost"])
        if "actual_cost" in fields:
            fields["actual_cost"] = str(fields["actual_cost"])

        # Convert UUID fields to strings for GUID storage
        if "assembly_id" in fields and fields["assembly_id"] is not None:
            fields["assembly_id"] = fields["assembly_id"]
        if "boq_position_id" in fields and fields["boq_position_id"] is not None:
            fields["boq_position_id"] = fields["boq_position_id"]

        # Map 'metadata' key to the model's 'metadata_' column. Merge the
        # incoming dict over the stored value so a partial PATCH never drops
        # keys the caller did not resend (json_overwrite data-loss guard).
        if "metadata" in fields:
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(work_order, "metadata_", None), _incoming)
                if isinstance(_incoming, dict)
                else _incoming
            )

        if fields:
            # Snapshot the linked activity id before the update so the event
            # below carries it without re-reading the work order, where a
            # reload raises MissingGreenlet
            activity_id = work_order.activity_id

            await self.work_order_repo.update_fields(work_order_id, **fields)

            await _safe_publish(
                "schedule.work_order.updated",
                {
                    "work_order_id": str(work_order_id),
                    "activity_id": str(activity_id),
                    "fields": list(fields.keys()),
                },
                source_module="oe_schedule",
            )

        # Re-fetch to return fresh data
        return await self.get_work_order(work_order_id)

    async def update_work_order_status(self, work_order_id: uuid.UUID, new_status: str) -> WorkOrder:
        """Update work order status.

        Args:
            work_order_id: Target work order identifier.
            new_status: New status value.

        Returns:
            Updated work order.

        Raises:
            HTTPException 404 if work order not found.
        """
        work_order = await self.get_work_order(work_order_id)

        await self.work_order_repo.update_fields(work_order_id, status=new_status)

        await _safe_publish(
            "schedule.work_order.status_changed",
            {
                "work_order_id": str(work_order_id),
                "activity_id": str(work_order.activity_id),
                "old_status": work_order.status,
                "new_status": new_status,
            },
            source_module="oe_schedule",
        )

        logger.info(
            "Work order %s status changed: %s -> %s",
            work_order_id,
            work_order.status,
            new_status,
        )
        return await self.get_work_order(work_order_id)

    # ── Gantt chart data ───────────────────────────────────────────────────

    async def get_gantt_data(self, schedule_id: uuid.UUID) -> GanttData:
        """Build structured data for Gantt chart rendering.

        Returns all activities with their dependencies, progress, and summary
        statistics suitable for frontend Gantt visualization.

        Args:
            schedule_id: Target schedule identifier.

        Returns:
            GanttData with activities list and summary statistics.

        Raises:
            HTTPException 404 if schedule not found.
        """
        schedule = await self.get_schedule(schedule_id)

        # Resolve the project region once so the delay check and the duration
        # fallback below count on the same regional working week as every
        # other path in this module.
        project_region = await self.resolve_project_region(schedule.project_id)
        today = datetime.now(UTC).date()

        activities, _ = await self.activity_repo.list_for_schedule(schedule_id)
        assignee_names = await self.resolve_assignee_names({a.assignee_id for a in activities if a.assignee_id})

        gantt_activities: list[GanttActivity] = []
        completed = 0
        in_progress = 0
        delayed = 0
        not_started = 0

        for act in activities:
            progress = _str_to_float(act.progress_pct)

            # Report the stored working-day duration so the Gantt agrees with
            # the activity table and CPM. ``act.duration_days`` is recomputed
            # via compute_duration() on every create/update; falling back to a
            # raw calendar-day diff (as the old code did) produced a different
            # number than the rest of the UI for any multi-week activity.
            duration = act.duration_days or 0
            if not duration:
                duration = compute_duration(str(act.start_date), str(act.end_date), project_region)

            # Derive the effective status: an unfinished activity whose planned
            # end date has already passed is "delayed". This is computed at read
            # time (not persisted) because delay is a temporal condition that
            # changes daily; the stored status keeps the user-set value.
            effective_status = _effective_activity_status(
                stored_status=act.status,
                progress_pct=progress,
                end_date=act.end_date,
                today=today,
                region=project_region,
            )

            gantt_activities.append(
                GanttActivity(
                    id=act.id,
                    name=act.name,
                    start_date=str(act.start_date),
                    end_date=str(act.end_date),
                    duration_days=duration,
                    progress_pct=progress,
                    dependencies=_normalize_deps(act.dependencies),
                    parent_id=act.parent_id,
                    color=act.color,
                    boq_position_ids=act.boq_position_ids or [],
                    wbs_code=act.wbs_code,
                    activity_type=act.activity_type,
                    status=effective_status,
                    calendar_id=act.calendar_id,
                    assignee_id=act.assignee_id,
                    assignee_name=assignee_names.get(act.assignee_id) if act.assignee_id else None,
                    client_visible=bool(act.client_visible),
                    metadata=act.metadata_ or {},
                )
            )

            # Count by status
            if effective_status == "completed":
                completed += 1
            elif effective_status == "in_progress":
                in_progress += 1
            elif effective_status == "delayed":
                delayed += 1
            else:
                not_started += 1

        summary = GanttSummary(
            total_activities=len(activities),
            completed=completed,
            in_progress=in_progress,
            delayed=delayed,
            not_started=not_started,
        )

        return GanttData(activities=gantt_activities, summary=summary)

    # ── Reschedule (CPM-driven dates) ──────────────────────────────────────

    @staticmethod
    def _resolve_project_start(schedule: Schedule, activities: list[Activity]) -> date:
        """Pick the CPM origin date the day-offsets are measured from.

        Prefers the schedule's own ``start_date``; falls back to the earliest
        activity start, then to today. The forward pass floors early_start at
        zero, so projected dates never precede this origin.
        """
        raw = schedule.start_date
        if raw:
            try:
                return date.fromisoformat(str(raw)[:10])
            except (ValueError, TypeError):
                pass
        earliest: date | None = None
        for act in activities:
            try:
                d = date.fromisoformat(str(act.start_date)[:10])
            except (ValueError, TypeError):
                continue
            if earliest is None or d < earliest:
                earliest = d
        return earliest or datetime.now(UTC).date()

    @staticmethod
    def _activity_start_offset(activity: Activity, project_start: date) -> int:
        """Day-offset of an activity's manual start from the project origin.

        Used to anchor a root activity in the CPM forward pass so its
        successors are scheduled after it. Returns 0 when the activity has no
        parseable start date or starts on/before the origin (the forward pass
        floors early_start at zero anyway).
        """
        try:
            d = date.fromisoformat(str(activity.start_date)[:10])
        except (ValueError, TypeError):
            return 0
        return max((d - project_start).days, 0)

    async def _resolve_activity_calendars(self, activities: list[Activity], project_id: uuid.UUID) -> dict[str, dict]:
        """Load each activity's per-activity work calendar as ``{work_days, exceptions}``.

        An activity may point at a named work calendar (``Activity.calendar_id``
        -> a ``schedule_advanced`` ``Calendar``) so its own duration is measured
        on its own work week - a six-day trade, or a crew with its own holidays.
        Returns a map keyed by activity-id string, only for activities whose
        ``calendar_id`` resolves to an existing calendar in this project; the
        rest fall back to the schedule-wide calendar inside the CPM engine. The
        calendar model stores ``holidays``, which the engine consumes as
        ``exceptions``. Calendars are batch-loaded in a single query.

        The lookup is scoped to ``project_id`` so a foreign or dangling
        ``calendar_id`` (for example one copied in through a schedule import from
        another project) resolves to nothing and falls back to the schedule-wide
        calendar, rather than silently scheduling the activity on another
        tenant's work week. This mirrors the write path
        (``progress_service.set_calendar``), which rejects a cross-project
        calendar with a 404.

        Args:
            activities: The schedule's activities.
            project_id: The owning project; calendars outside it are ignored.

        Returns:
            ``{activity_id: {"work_days": [...], "exceptions": [...]}}`` for the
            activities that carry a resolvable calendar; empty when none do.
        """
        calendar_ids = {a.calendar_id for a in activities if getattr(a, "calendar_id", None)}
        if not calendar_ids:
            return {}

        from app.modules.schedule_advanced.models import Calendar

        rows = await self.session.execute(
            select(Calendar).where(Calendar.id.in_(calendar_ids)).where(Calendar.project_id == project_id)
        )
        cal_by_id = {c.id: c for c in rows.scalars().all()}

        resolved: dict[str, dict] = {}
        for a in activities:
            cid = getattr(a, "calendar_id", None)
            cal = cal_by_id.get(cid) if cid else None
            if cal is None:
                continue
            work_days = readable_work_days(cal.work_days, source=f"calendar {cal.id} work days")
            exceptions = readable_exception_dates(cal.holidays, source=f"calendar {cal.id} holidays")
            resolved[str(a.id)] = {
                "work_days": work_days or [0, 1, 2, 3, 4],
                "exceptions": exceptions,
            }
        return resolved

    async def _resolve_schedule_default_calendar(self, schedule: Schedule) -> dict:
        """Resolve the schedule-wide work calendar the CPM engine falls back to.

        Precedence: an explicit ``metadata.calendar`` override carried on the
        schedule wins; otherwise the project's default named calendar (the
        ``schedule_advanced`` ``Calendar`` flagged ``is_default``) so activities
        without their own calendar inherit the project default the calendar UI
        advertises; otherwise a Monday-Friday week. The calendar model stores
        ``holidays``, which the engine consumes as ``exceptions``.

        Args:
            schedule: The schedule being rescheduled.

        Returns:
            The ``{"work_days": [...], "exceptions": [...]}`` shape the core CPM
            engine (:func:`app.core.cpm.calculate_cpm`) consumes.
        """
        meta = getattr(schedule, "metadata_", None)
        cal = meta.get("calendar") if isinstance(meta, dict) else None
        if isinstance(cal, dict) and cal.get("work_days"):
            return resolve_calendar(schedule)

        project_id = getattr(schedule, "project_id", None)
        if project_id is not None:
            default_cal = await self._project_default_calendar(project_id)
            if default_cal is not None:
                return default_cal

        return resolve_calendar(schedule)

    async def _project_default_calendar(self, project_id: uuid.UUID) -> dict | None:
        """The project's default named calendar as ``{work_days, exceptions}``, if it has one."""
        from app.modules.schedule_advanced.models import Calendar

        rows = await self.session.execute(
            select(Calendar).where(Calendar.project_id == project_id).where(Calendar.is_default.is_(True)).limit(1)
        )
        default_cal = rows.scalars().first()
        if default_cal is None:
            return None
        work_days = readable_work_days(default_cal.work_days, source=f"default calendar {default_cal.id} work days")
        exceptions = readable_exception_dates(
            default_cal.holidays, source=f"default calendar {default_cal.id} holidays"
        )
        return {"work_days": work_days or [0, 1, 2, 3, 4], "exceptions": exceptions}

    async def _generation_calendar(self, schedule: Schedule, region_week: set[int]) -> tuple[dict, dict | None]:
        """The calendar a generated plan is drawn on, and the one to record on the schedule.

        The plan is drawn on the calendar :meth:`reschedule` will recount it
        on, holidays included, so the first reschedule moves no bar: the
        schedule's own calendar, else the project's default calendar. Without
        either, the project region's week is used, and recorded on the
        schedule when it is not Monday to Friday, which is what reschedule
        would otherwise fall back to.

        Returns:
            ``(calendar, calendar_to_record)``; the second is ``None`` when
            nothing needs recording.
        """
        meta = schedule.metadata_ if isinstance(schedule.metadata_, dict) else {}
        own = meta.get("calendar")
        if isinstance(own, dict) and own.get("work_days"):
            return resolve_calendar(schedule), None
        default_cal = await self._project_default_calendar(schedule.project_id)
        if default_cal is not None:
            return default_cal, None
        week = {"work_days": sorted(region_week), "exceptions": []}
        return week, (week if set(region_week) != {0, 1, 2, 3, 4} else None)

    async def reschedule(self, schedule_id: uuid.UUID) -> list[Activity]:
        """Recompute activity dates from the dependency network via CPM.

        Loads the schedule's activities and its canonical
        :class:`ScheduleRelationship` edges, runs the core CPM engine on a
        resolved work calendar, then projects each early-date day-offset back
        onto a calendar date. Activities that have at least one predecessor are
        CPM-driven: their ``start_date`` / ``end_date`` are rewritten from the
        forward-pass early dates, so changing a link moves the successor's bar.
        Root activities (no predecessor) keep their manually set dates - only
        their critical-path flag, float columns and colour are refreshed.

        Constraint pinning (must-start-on / as-late-as-possible) is out of
        scope for this pass; roots anchor the network at their manual start.

        Args:
            schedule_id: The schedule to reschedule.

        Returns:
            The activities after the write, re-fetched in sort order. Empty
            when the schedule has no activities.

        Raises:
            HTTPException 404 if the schedule does not exist.
        """
        from app.core.cpm import calculate_cpm, offset_to_iso

        schedule = await self.get_schedule(schedule_id)
        activities, _ = await self.list_activities_for_schedule(schedule_id, limit=10_000)
        if not activities:
            return []

        relationships = await self.relationship_repo.list_for_schedule(schedule_id)
        project_start = self._resolve_project_start(schedule, activities)

        # Activities that appear as a successor of some edge are CPM-driven;
        # the rest are roots whose manual start anchors the chain.
        has_predecessor = {str(r.successor_id) for r in relationships}

        # Each activity may carry its own named work calendar so its duration is
        # measured on its own work week (a six-day trade, a crew with its own
        # holidays); the rest fall back to the schedule-wide calendar.
        activity_calendars = await self._resolve_activity_calendars(activities, schedule.project_id)

        # Feed each root's own start into the engine as a "start no earlier
        # than" floor (a day-offset from the project origin) so its successors
        # are scheduled after it, not at the origin. Successors carry no floor:
        # they are driven purely by the network, so a stale manual date can
        # never pin them later than their predecessors allow.
        act_dicts: list[dict[str, object]] = []
        for a in activities:
            entry: dict[str, object] = {
                "id": str(a.id),
                "duration": a.duration_days or 0,
                "name": a.name,
                "start_offset": (0 if str(a.id) in has_predecessor else self._activity_start_offset(a, project_start)),
            }
            activity_calendar = activity_calendars.get(str(a.id))
            if activity_calendar is not None:
                entry["calendar"] = activity_calendar
            act_dicts.append(entry)
        rel_dicts = [
            {
                "predecessor_id": str(r.predecessor_id),
                "successor_id": str(r.successor_id),
                "type": r.relationship_type,
                "lag": r.lag_days,
            }
            for r in relationships
        ]

        calendar = await self._resolve_schedule_default_calendar(schedule)
        cpm_results = await calculate_cpm(
            act_dicts,
            rel_dicts,
            calendar=calendar,
            project_start_date=project_start.isoformat(),
        )
        cpm_map = {r["id"]: r for r in cpm_results}

        # One uniform payload shape per row so the bulk UPDATE compiles a
        # single statement (heterogeneous key sets would break executemany).
        updates: list[dict[str, object]] = []
        for act in activities:
            cpm = cpm_map.get(str(act.id))
            if cpm is None:
                continue
            if str(act.id) in has_predecessor:
                new_start = offset_to_iso(cpm["early_start"], project_start)
                new_end = inclusive_end_from_cpm(
                    cpm["early_start"],
                    cpm["early_finish"],
                    activity_calendars.get(str(act.id), calendar),
                    project_start,
                )
            else:
                new_start = act.start_date
                new_end = act.end_date
            is_critical = bool(cpm["is_critical"])
            updates.append(
                {
                    "id": act.id,
                    "start_date": new_start,
                    "end_date": new_end,
                    "early_start": str(cpm["early_start"]),
                    "early_finish": str(cpm["early_finish"]),
                    "late_start": str(cpm["late_start"]),
                    "late_finish": str(cpm["late_finish"]),
                    "total_float": cpm["total_float"],
                    "free_float": cpm["free_float"],
                    "is_critical": is_critical,
                    "color": "#ef4444" if is_critical else "#0071e3",
                }
            )

        await self.activity_repo.bulk_update_fields(updates)

        publish_after_commit(
            self.session,
            "schedule.rescheduled",
            {"schedule_id": str(schedule_id), "count": len(updates)},
            source_module="oe_schedule",
        )

        logger.info("Rescheduled schedule %s: %d activities updated", schedule_id, len(updates))

        refreshed, _ = await self.list_activities_for_schedule(schedule_id, limit=10_000)
        return refreshed

    # ── Generate from BOQ ─────────────────────────────────────────────────

    async def _plan_from_boq(
        self,
        schedule_id: uuid.UUID,
        boq_id: uuid.UUID,
        total_project_days: int | None,
        start_date: date | None,
        *,
        workers_per_position: int | None = None,
    ) -> _BoqGenerationPlan:
        """Work out everything a generation would write, and write nothing.

        Shared by :meth:`generate_from_boq` and :meth:`preview_generation`, so
        the preview a person confirms is the plan that gets written.

        Raises:
            HTTPException: 404 ``boq_not_found`` (also for a bill of another
                project), 422 ``boq_has_no_positions``.
        """
        from app.modules.boq.repository import BOQRepository, PositionRepository
        from app.modules.boq.service import _is_section, is_empty_position
        from app.modules.schedule.boq_plan import (
            MAX_CREWS,
            BoqRow,
            Task,
            build_plan_tree,
            fit_plan,
            iter_items,
            iter_tasks,
            layout_plan,
        )

        schedule = await self.get_schedule(schedule_id)
        schedule_project_id = schedule.project_id

        boq = await BOQRepository(self.session).get_by_id(boq_id)
        if boq is None or boq.project_id != schedule_project_id:
            # A bill of another project answers like a missing one, so the
            # endpoint cannot be used to probe which bills exist elsewhere.
            raise coded_http_error(status.HTTP_404_NOT_FOUND, "boq_not_found", "BOQ not found.")
        boq_meta = dict(boq.metadata_ or {})

        positions = await PositionRepository(self.session).list_all_for_boq(boq_id)
        rows: list[BoqRow] = []
        for p in positions:
            try:
                meta = dict(p.metadata_) if isinstance(p.metadata_, dict) else {}
            except Exception:
                meta = {}
            quantity = _str_to_float(p.quantity)
            total = _str_to_float(p.total)
            lump_sum = _normalize_unit(p.unit) == "lsum"
            rows.append(
                BoqRow(
                    id=str(p.id),
                    parent_id=str(p.parent_id) if p.parent_id is not None else None,
                    is_section=_is_section(p),
                    is_placeholder=is_empty_position(p),
                    data={
                        "ordinal": (p.ordinal or "").strip(),
                        "description": (p.description or "").strip(),
                        "unit": p.unit or "",
                        "quantity": quantity,
                        "total": total,
                        "metadata": meta,
                    },
                    # A lump sum is often priced by its total alone, with the
                    # quantity left empty: it is work all the same.
                    has_work=quantity > 0 or (lump_sum and total > 0),
                    lump_sum=lump_sum,
                )
            )
        tree = build_plan_tree(rows)
        tasks = list(iter_tasks(tree.roots))
        if not tasks:
            raise coded_http_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "boq_has_no_positions",
                "This BOQ has no positions with work to schedule. Add positions to its sections first.",
            )

        window_is_explicit = total_project_days is not None
        if total_project_days is None:
            building_type = boq_meta.get("building_type", "residential")
            total_project_days = 540 if building_type == "office" else 365

        # The same resolver compute_duration's callers use, so the week the
        # dates are drawn on here is the week they are recounted on later.
        project_region = await self.resolve_project_region(schedule_project_id)
        cal = get_work_calendar(project_region)
        hours_per_day = cal["hours_per_day"]
        plan_calendar, calendar_to_record = await self._generation_calendar(schedule, set(cal["work_days"]))
        work_days_set = set(plan_calendar["work_days"])
        holidays = {d for d in (normalise_exception_date(e) for e in plan_calendar.get("exceptions") or []) if d}
        work_days_per_week = len(work_days_set)

        def _works(day: date) -> bool:
            return day.weekday() in work_days_set and day not in holidays

        grand_total = sum(float(task.row.data["total"]) for task in tasks)
        if grand_total <= 0:
            grand_total = 1.0

        def _from_resources(data: dict[str, Any], workers: int) -> tuple[int, str]:
            return _calc_duration_from_resources(
                data["metadata"],
                data["quantity"],
                data["unit"],
                data["total"],
                grand_total,
                total_project_days,
                hours_per_day=hours_per_day,
                work_days_per_week=work_days_per_week,
                assumed_workers=workers,
            )

        sources: dict[str, str] = {}
        basis: dict[str, dict[str, Any]] = {}
        for task in tasks:
            data = task.row.data
            _, source = _from_resources(data, 1)
            sources[task.row.id] = source
            if source == "estimated_fallback":
                # Worked in working days straight from the hours, so the
                # numbers on the note add up: hours / (gang x hours a day).
                unit_key = _normalize_unit(data["unit"])
                rate = fallback_production_rate(data["unit"])
                basis[task.row.id] = {
                    "unit": unit_key,
                    "rate": rate,
                    "hours": fallback_labor_hours(data["unit"], data["quantity"]),
                    "gang": fallback_gang_size(data["unit"]),
                    "hours_per_day": hours_per_day,
                }

        # Hold every guess from the unit table to the price: a position may not
        # take more than _FALLBACK_PRICE_SHARE_CAP times its share of the
        # guessed positions' money in their guessed hours.
        guessed_cost = sum(float(task.row.data["total"]) for task in tasks if task.row.id in basis)
        guessed_hours = sum(b["hours"] for b in basis.values())
        for task in tasks:
            b = basis.get(task.row.id)
            if b is None:
                continue
            cost = float(task.row.data["total"])
            if guessed_cost > 0 and guessed_hours > 0 and cost > 0:
                cap = _FALLBACK_PRICE_SHARE_CAP * cost / guessed_cost * guessed_hours
                if b["hours"] > cap:
                    b["hours_from_unit"] = b["hours"]
                    b["hours"] = cap
                    b["capped_by_price"] = True
            b["hours"] = round(b["hours"], 1)

        # Positions whose bill gives hours but no crew: one labour row in hours
        # per unit, or no labour data at all. They are worked by at least the
        # assumed number of workers; a crew the bill states is kept as it is,
        # and a position priced by its cost share has no crew to assume.
        without_workers = {
            task.row.id
            for task in tasks
            if sources[task.row.id] in ("resource_sum", "estimated_fallback")
            or (
                sources[task.row.id] == "labor_hours"
                and _meta_number(task.row.data["metadata"], "workers_per_unit") <= 0
            )
        }

        def _durations_for(workers: int) -> dict[str, int]:
            out: dict[str, int] = {}
            for task in tasks:
                b = basis.get(task.row.id)
                if b is not None:
                    out[task.row.id] = max(1, math.ceil(b["hours"] / (max(b["gang"], workers) * hours_per_day)))
                else:
                    duration_cal, _ = _from_resources(task.row.data, workers)
                    # Calendar days to working days on the project's own week.
                    out[task.row.id] = max(1, math.ceil(duration_cal * work_days_per_week / 7))
            return out

        schedule_start = (
            start_date
            or _parse_day(schedule.start_date)
            or await self._project_planned_start(schedule_project_id)
            or date.today()
        )
        plan_start = schedule_start
        while not _works(plan_start):
            plan_start += timedelta(days=1)

        # Working days inside the window, one held back for the completion
        # milestone, which CPM puts on the day after the work.
        window_end = schedule_start + timedelta(days=total_project_days - 1)
        budget = 0
        cursor = plan_start
        while cursor <= window_end:
            if _works(cursor):
                budget += 1
            cursor += timedelta(days=1)
        budget = max(1, budget - 1)

        def _choose_workers() -> tuple[int, PlanFit]:
            if workers_per_position is not None:
                workers = workers_per_position
            elif not without_workers:
                # Every crew is in the bill: nothing to assume.
                workers = 1
            else:
                # The fewest workers per position that fit the window at the
                # estimates themselves, so no duration is squeezed. Without an
                # end date that is the default window, which the preview names
                # as such: one worker on thousands of hours is no plan either. Tried one
                # by one: the layout is greedy, and more workers do not always
                # make it shorter, so a bisection could skip the fewest. Each
                # try is one layout with every crew; when even the most
                # workers do not fit, none is tried.
                def _fits(workers: int) -> bool:
                    return layout_plan(tree.roots, _durations_for(workers), MAX_CREWS).span <= budget

                workers = MAX_ASSUMED_WORKERS
                if _fits(MAX_ASSUMED_WORKERS):
                    workers = next(n for n in range(1, MAX_ASSUMED_WORKERS + 1) if _fits(n))
            return workers, fit_plan(tree.roots, _durations_for(workers), budget, allow_compress=window_is_explicit)

        # Pure and CPU-bound: off the event loop, so a big bill does not stall
        # every other request while it is laid out.
        workers, fit = await asyncio.to_thread(_choose_workers)
        durations = _durations_for(workers)
        for b in basis.values():
            b["gang"] = max(b["gang"], workers)
        layout = fit.layout
        # A loose lump sum runs for the whole works; whatever its own estimate
        # said is not what the chart shows, so neither is the note.
        for position_id in layout.spanning:
            sources[position_id] = "spans_works"
            basis.pop(position_id, None)

        work_dates: list[date] = []
        cursor = plan_start
        while len(work_dates) < layout.span + 1:
            if _works(cursor):
                work_dates.append(cursor)
            cursor += timedelta(days=1)

        def _start(offset: int) -> str:
            return work_dates[offset].isoformat()

        def _end(finish: int) -> str:
            return work_dates[max(finish - 1, 0)].isoformat()

        ids: dict[str, uuid.UUID] = {}
        wbs_of: dict[str, str] = {}
        root_links = {succ: (pred, lag) for pred, succ, lag in layout.root_links}
        activities: list[Activity] = []
        relationships: list[ScheduleRelationship] = []
        created: list[dict] = []
        child_counter: dict[str | None, int] = {}

        def _link(pred_key: str, succ_id: uuid.UUID, dep_type: str, lag: int) -> dict:
            relationships.append(
                ScheduleRelationship(
                    schedule_id=schedule_id,
                    predecessor_id=ids[pred_key],
                    successor_id=succ_id,
                    relationship_type=dep_type,
                    lag_days=lag,
                )
            )
            return {"activity_id": str(ids[pred_key]), "type": dep_type, "lag_days": lag}

        sort_counter = 0
        for item, parent in iter_items(tree.roots):
            slot = layout.slots[item.key]
            data = item.row.data
            activity_id = uuid.uuid4()
            ids[item.key] = activity_id
            parent_key = parent.key if parent is not None else None
            child_counter[parent_key] = child_counter.get(parent_key, 0) + 1
            ordinal = data["ordinal"]
            if not ordinal:
                prefix = wbs_of.get(parent_key, "") if parent_key else ""
                ordinal = f"{prefix}.{child_counter[parent_key]:03d}" if prefix else f"{child_counter[parent_key]:03d}"
            wbs = ordinal[:50]
            wbs_of[item.key] = wbs

            deps: list[dict] = []
            if slot.predecessor is not None:
                deps.append(_link(slot.predecessor, activity_id, "FS", 0))
            elif parent is not None:
                # The first item of each crew starts with its section, so the
                # section moving on a reschedule takes its work along.
                deps.append(_link(parent.key, activity_id, "SS", 0))
            if item.key in root_links:
                pred_key, _working_days = root_links[item.key]
                # CPM counts a lag in calendar days from the predecessor's
                # start; written that way it lands on the day drawn here.
                lag = (work_dates[slot.start] - work_dates[layout.slots[pred_key].start]).days
                deps.append(_link(pred_key, activity_id, "SS", lag))

            sort_counter += 1
            if isinstance(item, Task):
                quantity = data["quantity"]
                unit = data["unit"]
                meta = data["metadata"]
                label = data["description"] or _generated_text("position_label", ordinal=ordinal)
                task_meta: dict[str, Any] = {
                    "source": "boq_generation",
                    "boq_id": str(boq_id),
                    "quantity": quantity,
                    "unit": unit,
                    "labor_hours": meta.get("labor_hours", 0),
                    "workers_per_unit": meta.get("workers_per_unit", 0),
                    # "estimated_fallback" marks durations derived from the unit
                    # production-rate table so the UI can flag them as estimates.
                    "duration_method": sources[item.row.id],
                    "duration_source": sources[item.row.id],
                }
                if item.row.id in basis:
                    task_meta["duration_basis"] = basis[item.row.id]
                activities.append(
                    Activity(
                        id=activity_id,
                        schedule_id=schedule_id,
                        parent_id=ids[parent_key] if parent_key else None,
                        name=label[:255],
                        description=_generated_text(
                            "task_description",
                            ordinal=ordinal,
                            # A lump sum priced by its total reads as one of it.
                            quantity=_format_quantity(quantity if quantity > 0 else 1),
                            unit=unit,
                        ),
                        wbs_code=wbs,
                        start_date=_start(slot.start),
                        end_date=_end(slot.finish),
                        duration_days=slot.finish - slot.start,
                        progress_pct="0",
                        status="not_started",
                        activity_type="task",
                        dependencies=deps,
                        resources=[],
                        boq_position_ids=[item.row.id],
                        color="#0071e3",
                        sort_order=sort_counter,
                        metadata_=task_meta,
                    )
                )
                created.append({"id": activity_id, "activity_type": "task", "end_date": _end(slot.finish)})
            else:
                label = data["description"] or _generated_text("section_label", ordinal=ordinal)
                activities.append(
                    Activity(
                        id=activity_id,
                        schedule_id=schedule_id,
                        parent_id=ids[parent_key] if parent_key else None,
                        name=label[:255],
                        description=_generated_text("section_description", ordinal=ordinal),
                        wbs_code=wbs,
                        start_date=_start(slot.start),
                        end_date=_end(slot.finish),
                        duration_days=max(1, slot.finish - slot.start),
                        progress_pct="0",
                        status="not_started",
                        activity_type="summary",
                        dependencies=deps,
                        resources=[],
                        boq_position_ids=[],
                        color="#1e40af",
                        sort_order=sort_counter,
                        metadata_={"source": "boq_generation", "boq_id": str(boq_id)},
                    )
                )
                created.append({"id": activity_id, "activity_type": "summary", "end_date": _end(slot.finish)})

        # The completion milestone sits where CPM puts it: the working day
        # after the work, which the window kept a day for.
        planned_end = _start(layout.span)
        start_ms = Activity(
            id=uuid.uuid4(),
            schedule_id=schedule_id,
            parent_id=None,
            name=_generated_text("start_milestone"),
            description=_generated_text("start_milestone_description"),
            wbs_code="MS-001",
            start_date=schedule_start.isoformat(),
            end_date=schedule_start.isoformat(),
            duration_days=0,
            progress_pct="0",
            status="not_started",
            activity_type="milestone",
            dependencies=[],
            resources=[],
            boq_position_ids=[],
            color="#f59e0b",
            sort_order=0,
            metadata_={"source": "boq_generation", "boq_id": str(boq_id)},
        )
        activities.append(start_ms)
        created.append({"id": start_ms.id, "activity_type": "milestone", "end_date": start_ms.end_date})

        # Completion waits for every task nothing else waits for: the last item
        # of each crew in each section, and a loose position on its own. One
        # link from the latest-finishing section alone let CPM draw the
        # milestone before work that finishes later elsewhere.
        followed = {slot.predecessor for slot in layout.slots.values() if slot.predecessor is not None}
        terminal = [task for task in tasks if task.key not in followed]
        end_ms_id = uuid.uuid4()
        end_deps = [_link(task.key, end_ms_id, "FS", 0) for task in terminal]
        activities.append(
            Activity(
                id=end_ms_id,
                schedule_id=schedule_id,
                parent_id=None,
                name=_generated_text("completion_milestone"),
                description=_generated_text("completion_milestone_description"),
                wbs_code="MS-999",
                start_date=planned_end,
                end_date=planned_end,
                duration_days=0,
                progress_pct="0",
                status="not_started",
                activity_type="milestone",
                dependencies=end_deps,
                resources=[],
                boq_position_ids=[],
                color="#f59e0b",
                sort_order=sort_counter + 1,
                metadata_={"source": "boq_generation", "boq_id": str(boq_id)},
            )
        )
        created.append({"id": end_ms_id, "activity_type": "milestone", "end_date": planned_end})

        notes: list[dict[str, Any]] = []
        note_counts: dict[str, int] = {}
        for task in tasks:
            code = _DURATION_NOTE[sources[task.row.id]]
            note_counts[code] = note_counts.get(code, 0) + 1
            if code == "from_labor_norm":
                continue
            note: dict[str, Any] = {
                "position_id": task.row.id,
                "ordinal": task.row.data["ordinal"],
                "description": task.row.data["description"][:160],
                "note": code,
                "days": (
                    layout.slots[task.key].finish - layout.slots[task.key].start
                    if task.row.id in layout.spanning
                    else fit.durations.get(task.row.id, durations[task.row.id])
                ),
            }
            if task.row.id in basis:
                note["basis"] = basis[task.row.id]
            notes.append(note)
        for row, reason in tree.skipped_rows:
            note_counts[reason] = note_counts.get(reason, 0) + 1
            notes.append(
                {
                    "position_id": row.id,
                    "ordinal": row.data["ordinal"],
                    "description": row.data["description"][:160],
                    "note": reason,
                }
            )

        requested_end = window_end.isoformat() if window_is_explicit else None
        fitted_window = {
            "days": total_project_days,
            "end": window_end.isoformat(),
            "default": not window_is_explicit,
            # Whether the plan fits that window at its estimates. False when
            # even the most workers assumed leave it too long, so the preview
            # never calls the number "the fewest that fit".
            "fits": fit.fits and fit.compressed_pct is None,
        }
        warnings: list[dict] = []
        if window_is_explicit and not fit.fits:
            exceeds: dict[str, Any] = {
                "code": "plan_exceeds_window",
                "planned_end": planned_end,
                "requested_end": requested_end,
            }
            if fit.compressed_pct is not None:
                exceeds["percent"] = fit.compressed_pct
            warnings.append(exceeds)
        elif window_is_explicit and fit.compressed_pct is not None:
            warnings.append({"code": "durations_shortened", "percent": fit.compressed_pct})

        return _BoqGenerationPlan(
            schedule_meta=(
                {**(schedule.metadata_ or {}), "calendar": calendar_to_record}
                if calendar_to_record is not None
                else dict(schedule.metadata_ or {})
            ),
            boq_name=getattr(boq, "name", None) or "",
            boq_estimate_type=getattr(boq, "estimate_type", None),
            schedule_start=schedule_start,
            planned_end=planned_end,
            requested_end=requested_end,
            fit=fit,
            activities=activities,
            relationships=relationships,
            created=created,
            positions_scheduled=len(tasks),
            workers_per_position=workers,
            workers_assumed=workers_per_position is None,
            fitted_window=fitted_window,
            positions_without_workers=len(without_workers),
            lump_sum_positions=sum(1 for task in tasks if _normalize_unit(task.row.data["unit"]) == "lsum"),
            rows_skipped=tree.skipped,
            notes=notes,
            note_counts=note_counts,
            warnings=warnings,
        )

    async def _instalment_relinks(
        self, schedule_id: uuid.UUID, new_activities: list[Activity]
    ) -> tuple[list[tuple[uuid.UUID, uuid.UUID]], int]:
        """Which contract payment instalments a regenerated plan can carry over.

        An instalment waits for a milestone of this schedule. Replacing the
        plan deletes that milestone; when the new plan has the same one (the
        generated start or completion, or an activity built from the same bill
        positions) a pending instalment moves to it. The rest lose their link
        and go back to their contract dates, as on any delete.

        Returns:
            ``(instalment_id, new_activity_id)`` pairs, and how many linked
            instalments cannot be carried over.
        """
        try:
            from app.modules.contracts.models import ContractMilestone
        except ImportError:  # contracts not installed
            return [], 0
        linked = (
            await self.session.execute(
                select(ContractMilestone.id, ContractMilestone.activity_id, ContractMilestone.status)
                .where(ContractMilestone.schedule_id == schedule_id)
                .where(ContractMilestone.activity_id.is_not(None))
            )
        ).all()
        if not linked:
            return [], 0
        old = (
            await self.session.execute(
                select(
                    Activity.id,
                    Activity.activity_type,
                    Activity.wbs_code,
                    Activity.boq_position_ids,
                    Activity.metadata_,
                ).where(Activity.id.in_({row.activity_id for row in linked}))
            )
        ).all()
        old_key = {row.id: _relink_key(row) for row in old}
        new_by_key: dict[tuple, uuid.UUID] = {}
        for activity in new_activities:
            key = _relink_key(activity)
            if key is not None:
                new_by_key.setdefault(key, activity.id)
        relinks: list[tuple[uuid.UUID, uuid.UUID]] = []
        lost = 0
        for row in linked:
            key = old_key.get(row.activity_id)
            # Only an instalment still waiting: one already reached, claimed
            # or paid stays with the milestone it was settled against.
            target = new_by_key.get(key) if key is not None and row.status == "pending" else None
            if target is None:
                lost += 1
            else:
                relinks.append((row.id, target))
        return relinks, lost

    async def _apply_instalment_relinks(self, relinks: list[tuple[uuid.UUID, uuid.UUID]]) -> None:
        """Point each instalment at its milestone in the new plan."""
        from sqlalchemy import update

        from app.modules.contracts.models import ContractMilestone

        for instalment_id, activity_id in relinks:
            await self.session.execute(
                update(ContractMilestone).where(ContractMilestone.id == instalment_id).values(activity_id=activity_id)
            )

    async def _project_planned_start(self, project_id: uuid.UUID) -> date | None:
        """The project's planned start, when it has one."""
        from app.modules.projects.repository import ProjectRepository

        project = await ProjectRepository(self.session).get_by_id(project_id)
        return _parse_day(getattr(project, "planned_start_date", None)) if project is not None else None

    async def preview_generation(
        self,
        schedule_id: uuid.UUID,
        boq_id: uuid.UUID,
        total_project_days: int | None = None,
        *,
        start_date: date | None = None,
        workers_per_position: int | None = None,
    ) -> dict[str, Any]:
        """What :meth:`generate_from_boq` would write, for a person to confirm.

        Writes nothing, deletes nothing and leaves the schedule's start alone.
        Returns the counts, the planned start and end against the window, the
        activities already on the schedule (a confirmed generation replaces
        them) and one note per position whose duration is an estimate or that
        is left out, with the numbers behind the estimate.
        """
        plan = await self._plan_from_boq(
            schedule_id, boq_id, total_project_days, start_date, workers_per_position=workers_per_position
        )
        existing = (await self.activity_repo.list_for_schedule(schedule_id, limit=1))[1]
        started = await self.activity_repo.count_started(schedule_id) if existing else 0
        relinks, lost = await self._instalment_relinks(schedule_id, plan.activities) if existing else ([], 0)
        estimated = sum(
            plan.note_counts.get(code, 0) for code in ("estimated_from_unit", "cost_share", "default_duration")
        )
        return {
            "boq_id": str(boq_id),
            "boq_name": plan.boq_name,
            "boq_estimate_type": plan.boq_estimate_type,
            "activity_count": len(plan.activities),
            "positions_scheduled": plan.positions_scheduled,
            "lump_sum_positions": plan.lump_sum_positions,
            "summary_count": sum(1 for a in plan.activities if a.activity_type == "summary"),
            "estimated_count": estimated,
            "skipped_count": plan.rows_skipped,
            "note_counts": plan.note_counts,
            "crews": plan.fit.crews,
            "workers_per_position": plan.workers_per_position,
            "workers_assumed": plan.workers_assumed,
            "positions_without_workers": plan.positions_without_workers,
            "fitted_window": plan.fitted_window,
            "compressed_pct": plan.fit.compressed_pct,
            "fits": plan.fit.fits or plan.requested_end is None,
            "planned_start": plan.schedule_start.isoformat(),
            "planned_end": plan.planned_end,
            "requested_end": plan.requested_end,
            "warnings": plan.warnings,
            "existing_activity_count": existing,
            "existing_started_count": started,
            "instalments_relinked": len(relinks),
            "instalments_unlinked": lost,
            "notes": plan.notes,
        }

    async def generate_from_boq(
        self,
        schedule_id: uuid.UUID,
        boq_id: uuid.UUID,
        total_project_days: int | None = None,
        *,
        replace: bool = False,
        start_date: date | None = None,
        workers_per_position: int | None = None,
    ) -> list[dict]:
        """Generate a schedule from a BOQ, at every depth of the bill.

        Every section becomes a summary and every priced position exactly one
        task under it; the layout rules (crews per section, overlap between
        top-level sections, fitting to the window) live in
        :mod:`app.modules.schedule.boq_plan`. Durations come from labour data
        on the position, else unit production rates and a gang per kind of
        unit (held to the position's price), else the cost share.

        The outcome is recorded on the schedule under
        ``metadata["boq_generation"]``: how many positions were scheduled, the
        crews used, whether durations were shortened, the requested and the
        planned end, and ``warnings`` such as ``plan_exceeds_window`` when the
        plan cannot fit the window the caller gave.

        Args:
            schedule_id: Target schedule to populate.
            boq_id: Source BOQ; it must belong to the schedule's project.
            total_project_days: The project window in calendar days, counted
                from the start. When omitted, 365 (540 for office buildings)
                is used as a target that crews may be added for, but no
                duration is shortened.
            replace: Delete the schedule's activities and links first, in the
                same transaction. Without it a populated schedule is refused.
            start_date: The day the plan starts. Written to the schedule with
                the plan, in the same transaction. When omitted: the
                schedule's start, else the project's planned start, else today.
            workers_per_position: Workers on a position whose bill gives hours
                but no crew, at least (a gang the unit table or the labour rows
                give is never cut). When omitted, the fewest from 1 to
                :data:`MAX_ASSUMED_WORKERS` that fit the window without
                shortening any duration; without an end date, the default
                window, which the preview names as such.

        Returns:
            One ``{"id", "activity_type", "end_date"}`` dict per created activity.

        Raises:
            HTTPException: 404 ``boq_not_found``, 422 ``boq_has_no_positions``,
                409 ``schedule_has_activities``. Each detail carries ``error``
                (the code) and ``message`` (English, for API clients).
        """
        # Two generations at once would both find the schedule empty and both
        # write a plan. Hold the schedule row until this one commits; the
        # other then finds the activities and answers 409, or replaces them.
        await self.session.execute(select(Schedule.id).where(Schedule.id == schedule_id).with_for_update())
        plan = await self._plan_from_boq(
            schedule_id, boq_id, total_project_days, start_date, workers_per_position=workers_per_position
        )

        relinks: list[tuple[uuid.UUID, uuid.UUID]] = []
        existing_count = (await self.activity_repo.list_for_schedule(schedule_id, limit=1))[1]
        if existing_count > 0:
            relinks, lost = await self._instalment_relinks(schedule_id, plan.activities)
            if not replace:
                started = await self.activity_repo.count_started(schedule_id)
                raise coded_http_error(
                    status.HTTP_409_CONFLICT,
                    "schedule_has_activities",
                    "Schedule already has activities. Generate again with replace=true to replace them.",
                    activity_count=existing_count,
                    started_count=started,
                    instalments_relinked=len(relinks),
                    instalments_unlinked=lost,
                )
            # Same transaction: if anything below fails, the old plan comes back.
            await self.relationship_repo.delete_for_schedule(schedule_id)
            await self.activity_repo.delete_for_schedule(schedule_id)
            publish_after_commit(
                self.session,
                "schedule.activities.cleared",
                {"schedule_id": str(schedule_id), "count": existing_count},
                source_module="oe_schedule",
            )

        await self.activity_repo.create_many(plan.activities)
        await self.relationship_repo.create_many(plan.relationships)
        if relinks:
            # Before the commit, so the cleared event finds them on the new
            # milestones and only refreshes their forecasts.
            await self._apply_instalment_relinks(relinks)

        schedule_meta = plan.schedule_meta
        schedule_meta["boq_generation"] = {
            "boq_id": str(boq_id),
            "generated_at": datetime.now(UTC).isoformat(),
            "positions_scheduled": plan.positions_scheduled,
            "rows_skipped": plan.rows_skipped,
            "note_counts": plan.note_counts,
            "crews": plan.fit.crews,
            "workers_per_position": plan.workers_per_position,
            "workers_assumed": plan.workers_assumed,
            "positions_without_workers": plan.positions_without_workers,
            "fitted_window": plan.fitted_window,
            "compressed_pct": plan.fit.compressed_pct,
            "requested_end": plan.requested_end,
            "planned_end": plan.planned_end,
            "replaced_activities": existing_count if replace else 0,
            "warnings": plan.warnings,
        }
        await self.schedule_repo.update_fields(
            schedule_id,
            start_date=plan.schedule_start.isoformat(),
            end_date=plan.planned_end,
            metadata_=schedule_meta,
        )

        publish_after_commit(
            self.session,
            "schedule.generated_from_boq",
            {
                "schedule_id": str(schedule_id),
                "boq_id": str(boq_id),
                "activities_created": len(plan.created),
            },
            source_module="oe_schedule",
        )

        logger.info(
            "Generated %d activities from BOQ %s for schedule %s (%d crews, fits=%s)",
            len(plan.created),
            boq_id,
            schedule_id,
            plan.fit.crews,
            plan.fit.fits,
        )
        return plan.created

    # ── Critical Path Method ──────────────────────────────────────────────

    async def calculate_critical_path(self, schedule_id: uuid.UUID) -> CriticalPathResponse:
        """Calculate the critical path using forward/backward pass CPM.

        Algorithm adapted from DDC_Toolkit _compute_cpm:
        - Forward pass: compute Early Start (ES) and Early Finish (EF) for each activity
        - Backward pass: compute Late Start (LS) and Late Finish (LF)
        - Total Float = LS - ES
        - Critical path = activities where Total Float = 0

        Supports FS (Finish-to-Start) and SS (Start-to-Start) dependency types.
        Results are stored in each activity's metadata for later retrieval.

        Args:
            schedule_id: Target schedule to analyze.

        Returns:
            CriticalPathResponse with all CPM data and the critical path.

        Raises:
            HTTPException 404 if schedule not found or has no activities.
        """
        await self.get_schedule(schedule_id)

        activities, count = await self.activity_repo.list_for_schedule(schedule_id)
        if count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Schedule has no activities",
            )

        # Snapshot all activity data before the bulk write: ``bulk_update_fields``
        # still ends in ``session.expire_all()``, so reading an activity back
        # afterwards raises MissingGreenlet on the async session
        act_data: list[dict] = []
        for a in activities:
            act_data.append(
                {
                    "id": str(a.id),
                    "name": a.name or "",
                    "duration_days": a.duration_days or 0,
                    "activity_type": a.activity_type or "task",
                    "dependencies": _normalize_deps(a.dependencies),
                    "color": a.color or "#0071e3",
                    # The CPM write below merges into this, so every other
                    # key (a milestone's reached marker, import provenance,
                    # links to sales contracts) survives a recalculation.
                    "metadata_": dict(a.metadata_) if isinstance(a.metadata_, dict) else {},
                }
            )

        # Build activity index and dependency map
        idx: dict[str, dict] = {d["id"]: d for d in act_data}
        active_ids = set(idx.keys())

        # Parse dependencies: map activity_id -> list of (predecessor_id, type, lag)
        deps: dict[str, list[tuple[str, str, int]]] = {d["id"]: [] for d in act_data}

        # ScheduleRelationship is the SINGLE source of truth for edges. CPM reads
        # ONLY the canonical table so a relationship the user deleted truly
        # disappears from the network (the historical bug: a deleted row left a
        # JSON copy that kept blocking CPM because the two were additively
        # merged). All writers project the JSON into this table, so it is
        # authoritative.
        canonical_rows = await self.relationship_repo.list_for_schedule(schedule_id)
        seen_pairs: set[tuple[str, str]] = set()
        for r in canonical_rows:
            pred_id = str(r.predecessor_id)
            succ_id = str(r.successor_id)
            if pred_id in active_ids and succ_id in active_ids:
                deps[succ_id].append((pred_id, (r.relationship_type or "FS").upper(), r.lag_days or 0))
                seen_pairs.add((pred_id, succ_id))

        # Legacy fallback: only when the canonical table is EMPTY for this
        # schedule do we read the activity-embedded JSON, so un-reconciled
        # historical schedules (edges written only to the JSON before the
        # unification) still compute. As soon as any canonical row exists the
        # table is the sole authority and the JSON is ignored. The central
        # migration's reconciliation removes the need for this path on
        # production data; it is a safety net, never a competing source.
        if not canonical_rows:
            for ad in act_data:
                act_id = ad["id"]
                for dep in ad["dependencies"]:
                    pred_id = str(dep.get("activity_id", ""))
                    dep_type = dep.get("type", "FS")
                    lag = dep.get("lag_days", 0)
                    if pred_id in active_ids and (pred_id, act_id) not in seen_pairs:
                        deps[act_id].append((pred_id, dep_type, lag))
                        seen_pairs.add((pred_id, act_id))

        # --- Topological sort (Kahn's algorithm) ---
        # The forward/backward passes must visit each activity AFTER all of its
        # predecessors. Iterating in raw DB order is unsafe: if a successor is
        # listed before its predecessor, the forward pass would read ef.get(pred)
        # as the fallback (0 + pred_dur) and produce wrong CPM dates. We also
        # detect cycles here so we never silently return nonsense.
        from collections import defaultdict, deque

        adj: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = {d["id"]: 0 for d in act_data}
        for succ_id, preds in deps.items():
            for pred_id, _dep_type, _lag in preds:
                adj[pred_id].append(succ_id)
                in_degree[succ_id] += 1

        queue: deque[str] = deque([d["id"] for d in act_data if in_degree[d["id"]] == 0])
        sorted_ids: list[str] = []
        while queue:
            nid = queue.popleft()
            sorted_ids.append(nid)
            for succ in adj[nid]:
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)

        if len(sorted_ids) < len(act_data):
            unsorted_ids = [d["id"] for d in act_data if d["id"] not in set(sorted_ids)]
            unsorted_names = [idx[aid]["name"] or aid for aid in unsorted_ids[:5]]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("Schedule has a dependency cycle. Affected activities: " + ", ".join(unsorted_names)),
            )

        sorted_act_data: list[dict] = [idx[aid] for aid in sorted_ids]

        # --- Forward pass: compute ES, EF ---
        # Supports all 4 dependency types per PMBOK:
        #   FS (Finish-to-Start): successor starts after predecessor finishes (+lag)
        #   SS (Start-to-Start):  successor starts after predecessor starts (+lag)
        #   FF (Finish-to-Finish): successor finishes after predecessor finishes (+lag)
        #   SF (Start-to-Finish): successor finishes after predecessor starts (+lag)
        es: dict[str, int] = {}
        ef: dict[str, int] = {}
        for ad in sorted_act_data:
            act_id = ad["id"]
            dur = ad["duration_days"]
            act_es = 0
            for pred_id, dep_type, lag in deps[act_id]:
                dep_type = (dep_type or "FS").upper()
                pred_dur = idx[pred_id]["duration_days"]
                pred_ef = ef.get(pred_id, pred_dur)
                pred_es = es.get(pred_id, 0)
                if dep_type == "FS":
                    candidate = pred_ef + lag
                elif dep_type == "SS":
                    candidate = pred_es + lag
                elif dep_type == "FF":
                    # Successor finish ≥ predecessor finish + lag → ES = EF_succ - dur
                    candidate = pred_ef + lag - dur
                elif dep_type == "SF":
                    # Successor finish ≥ predecessor start + lag → ES = SF - dur
                    candidate = pred_es + lag - dur
                else:
                    logger.warning(
                        "Unknown dependency type '%s' on activity %s; treating as FS",
                        dep_type,
                        act_id,
                    )
                    candidate = pred_ef + lag
                act_es = max(act_es, candidate)
            es[act_id] = act_es
            ef[act_id] = act_es + dur

        # Project duration
        project_duration = max(ef.values()) if ef else 0

        # --- Backward pass: compute LS, LF ---
        successors: dict[str, list[tuple[str, str, int]]] = {d["id"]: [] for d in act_data}
        for ad in act_data:
            act_id = ad["id"]
            for pred_id, dep_type, lag in deps[act_id]:
                successors[pred_id].append((act_id, dep_type, lag))

        lf: dict[str, int] = {d["id"]: project_duration for d in act_data}
        ls: dict[str, int] = {}

        for ad in reversed(sorted_act_data):
            act_id = ad["id"]
            dur = ad["duration_days"]
            for succ_id, dep_type, lag in successors.get(act_id, []):
                dep_type = (dep_type or "FS").upper()
                succ_ls = ls.get(succ_id, project_duration)
                succ_lf = lf.get(succ_id, project_duration)
                if dep_type == "FS":
                    # pred LF ≤ succ LS - lag
                    lf[act_id] = min(lf[act_id], succ_ls - lag)
                elif dep_type == "SS":
                    # pred LS ≤ succ LS - lag → LF = LS_succ - lag + dur
                    lf[act_id] = min(lf[act_id], succ_ls - lag + dur)
                elif dep_type == "FF":
                    # pred LF ≤ succ LF - lag
                    lf[act_id] = min(lf[act_id], succ_lf - lag)
                elif dep_type == "SF":
                    # pred LS ≤ succ LF - lag → LF = LF_succ - lag + dur
                    lf[act_id] = min(lf[act_id], succ_lf - lag + dur)
                else:
                    logger.warning(
                        "Unknown dependency type '%s' on backward pass %s → %s; treating as FS",
                        dep_type,
                        act_id,
                        succ_id,
                    )
                    lf[act_id] = min(lf[act_id], succ_ls - lag)
            ls[act_id] = lf[act_id] - dur

        # --- Compute float and identify critical path ---
        all_results: list[CPMActivityResult] = []
        critical_results: list[CPMActivityResult] = []
        # Accumulate per-activity persistence payloads and flush them in a
        # single bulk UPDATE after the loop. The previous implementation issued
        # one UPDATE *and* one session.expire_all() per activity (the latter via
        # ActivityRepository.update_fields), which on a few-hundred-activity
        # schedule meant hundreds of round trips plus repeated full-identity-map
        # invalidation - the dominant cost of the /calculate-cpm/ button. The
        # values persisted are byte-identical to before.
        calculated_at = datetime.now(UTC).isoformat()
        cpm_updates: list[dict[str, object]] = []

        for ad in act_data:
            act_id = ad["id"]
            total_float = ls[act_id] - es[act_id]
            is_critical = total_float <= 0

            result = CPMActivityResult(
                activity_id=uuid.UUID(act_id),
                name=ad["name"],
                duration_days=ad["duration_days"],
                early_start=es[act_id],
                early_finish=ef[act_id],
                late_start=ls[act_id],
                late_finish=lf[act_id],
                total_float=total_float,
                is_critical=is_critical,
            )
            all_results.append(result)
            if is_critical:
                critical_results.append(result)

            # Update activity color + CPM metadata - persist so the frontend
            # can display ES/EF/LS/LF/float on next load without re-running CPM.
            cpm_meta = {
                "es": es[act_id],
                "ef": ef[act_id],
                "ls": ls[act_id],
                "lf": lf[act_id],
                "total_float": total_float,
                "is_critical": is_critical,
                "calculated_at": calculated_at,
            }
            new_color = "#ef4444" if is_critical else "#0071e3"
            # Merge cpm into existing metadata_ so we don't clobber user-set keys
            activity = idx.get(act_id)
            existing_meta = {}
            if activity:
                raw_meta = activity.get("metadata_") or activity.get("metadata") or {}
                if isinstance(raw_meta, dict):
                    existing_meta = dict(raw_meta)
            existing_meta["cpm"] = cpm_meta
            cpm_updates.append(
                {
                    "id": uuid.UUID(act_id),
                    "color": new_color,
                    "metadata_": existing_meta,
                }
            )

        # Single bulk UPDATE by primary key (one statement, executemany under
        # the hood) instead of N per-row update_fields() calls. The repository
        # runs expire_all() exactly once afterwards so a subsequent get_by_id
        # re-reads fresh state - matching the per-call contract the old loop
        # relied on.
        if cpm_updates:
            await self.activity_repo.bulk_update_fields(cpm_updates)

        await _safe_publish(
            "schedule.cpm.calculated",
            {
                "schedule_id": str(schedule_id),
                "project_duration": project_duration,
                "critical_count": len(critical_results),
            },
            source_module="oe_schedule",
        )

        logger.info(
            "CPM calculated for schedule %s: duration=%d, critical=%d/%d",
            schedule_id,
            project_duration,
            len(critical_results),
            len(all_results),
        )

        return CriticalPathResponse(
            schedule_id=schedule_id,
            project_duration_days=project_duration,
            critical_path=critical_results,
            all_activities=all_results,
        )

    # ── Risk Analysis (PERT) ──────────────────────────────────────────────

    async def get_risk_analysis(self, schedule_id: uuid.UUID) -> RiskAnalysisResponse:
        """Compute PERT-based risk analysis for the schedule.

        Uses the three-point estimation:
        - Optimistic (O) = duration * 0.75
        - Most Likely (M) = duration (as planned)
        - Pessimistic (P) = duration * 1.60

        Expected = (O + 4*M + P) / 6
        Variance per task = ((P - O) / 6)^2

        For the critical path: sums variances, computes standard deviation,
        and derives P50, P80, P95 percentiles using normal distribution
        approximation (Central Limit Theorem).

        Args:
            schedule_id: Target schedule to analyze.

        Returns:
            RiskAnalysisResponse with PERT estimates.

        Raises:
            HTTPException 404 if schedule not found or has no activities.
        """
        # First ensure CPM has been calculated (need critical path)
        cpm_result = await self.calculate_critical_path(schedule_id)

        det_days = cpm_result.project_duration_days

        # Compute per-activity PERT estimates
        activity_risks: list[dict] = []
        critical_variance_sum = 0.0

        for act_cpm in cpm_result.all_activities:
            duration = act_cpm.duration_days
            if duration <= 0:
                # Zero-duration milestone: no spread, so O = M = P = duration
                # keeps the three-point ordering valid and the variance at 0.
                optimistic = duration
                pessimistic = duration
            else:
                # Floors can push optimistic above the most-likely duration for
                # short tasks, so clamp the bounds to preserve O <= M <= P and
                # keep std_dev non-negative.
                optimistic = min(max(3, int(duration * _PERT_OPTIMISTIC)), duration)
                pessimistic = max(duration + 2, int(duration * _PERT_PESSIMISTIC), optimistic)
            expected = (optimistic + 4 * duration + pessimistic) / 6.0
            std_dev = (pessimistic - optimistic) / 6.0
            variance = std_dev**2

            activity_risks.append(
                {
                    "activity_id": str(act_cpm.activity_id),
                    "name": act_cpm.name,
                    "duration_days": duration,
                    "optimistic": optimistic,
                    "most_likely": duration,
                    "pessimistic": pessimistic,
                    "expected": round(expected, 1),
                    "std_dev": round(std_dev, 2),
                    "is_critical": act_cpm.is_critical,
                }
            )

            if act_cpm.is_critical:
                critical_variance_sum += variance

        # Project-level PERT estimates (sum of critical path variances)
        project_std = math.sqrt(critical_variance_sum)

        # Normal distribution percentiles: z_50=0, z_80=0.84, z_95=1.645
        p50_days = det_days  # median = deterministic for symmetric approx
        p80_days = int(det_days + 0.84 * project_std)
        p95_days = int(det_days + 1.645 * project_std)
        mean_days = round(
            sum(r["expected"] for r in activity_risks if r["is_critical"]),
            1,
        )
        risk_buffer = p80_days - det_days

        logger.info(
            "PERT risk analysis for schedule %s: P50=%d, P80=%d, P95=%d (buffer=%d)",
            schedule_id,
            p50_days,
            p80_days,
            p95_days,
            risk_buffer,
        )

        return RiskAnalysisResponse(
            schedule_id=schedule_id,
            deterministic_days=det_days,
            p50_days=p50_days,
            p80_days=p80_days,
            p95_days=p95_days,
            mean_days=mean_days,
            std_dev_days=round(project_std, 1),
            risk_buffer_days=risk_buffer,
            activity_risks=activity_risks,
        )

    # ── Project Intelligence (RFC 25) ──────────────────────────────────────

    async def get_labor_cost_by_phase(self, project_id: uuid.UUID):
        """Roll up labour cost per schedule phase (RFC 25)."""
        from sqlalchemy import select as _select

        from app.modules.boq.models import Position
        from app.modules.projects.models import Project
        from app.modules.schedule.models import Activity, Schedule
        from app.modules.schedule.schemas import (
            LaborCostByPhaseResponse,
            LaborCostByPhaseRow,
        )

        # Currency bug fix: the rolled-up labour/total costs are all scoped to
        # this one project, so they share a single ISO currency. Read the
        # project's real currency instead of hardcoding "EUR". Fall back to
        # blank ("unknown") - NEVER to "EUR" - when the project has no currency.
        cur_result = await self.session.execute(_select(Project.currency).where(Project.id == project_id))
        currency = cur_result.scalar_one_or_none() or ""

        stmt = (
            _select(Activity)
            .join(Schedule, Activity.schedule_id == Schedule.id)
            .where(Schedule.project_id == project_id)
        )
        result = await self.session.execute(stmt)
        activities: list[Activity] = list(result.scalars().all())

        if not activities:
            # Still report the project's real currency on the empty result.
            return LaborCostByPhaseResponse(currency=currency)

        # Gather linked BOQ position ids for aggregate lookup
        all_boq_ids: list[uuid.UUID] = []
        for act in activities:
            for pid in act.boq_position_ids or []:
                try:
                    all_boq_ids.append(uuid.UUID(str(pid)))
                except (TypeError, ValueError):
                    continue

        position_totals: dict[uuid.UUID, float] = {}
        if all_boq_ids:
            pos_stmt = _select(Position.id, Position.total).where(Position.id.in_(all_boq_ids))
            pos_result = await self.session.execute(pos_stmt)
            for pid, total in pos_result.all():
                position_totals[pid] = _str_to_float(total)

        phases: dict[str, dict[str, object]] = {}
        for act in activities:
            wbs = (act.wbs_code or "").strip()
            if wbs:
                phase = wbs.split(".")[0]
            else:
                phase = (act.activity_type or "task").strip() or "task"

            labour = 0.0
            for resource in act.resources or []:
                if not isinstance(resource, dict):
                    continue
                if resource.get("type") != "labor":
                    continue
                tc = resource.get("total_cost")
                if tc not in (None, "", 0):
                    labour += _str_to_float(tc)
                else:
                    units = _str_to_float(resource.get("units"))
                    rate = _str_to_float(resource.get("rate"))
                    labour += units * rate

            linked_total = 0.0
            for pid in act.boq_position_ids or []:
                try:
                    linked_total += position_totals.get(uuid.UUID(str(pid)), 0.0)
                except (TypeError, ValueError):
                    continue

            entry = phases.setdefault(
                phase,
                {
                    "phase": phase,
                    "activity_count": 0,
                    "labor_cost": 0.0,
                    "total_cost": 0.0,
                    "start_date": act.start_date,
                    "end_date": act.end_date,
                },
            )
            entry["activity_count"] = int(entry["activity_count"]) + 1
            entry["labor_cost"] = float(entry["labor_cost"]) + labour
            entry["total_cost"] = float(entry["total_cost"]) + labour + linked_total
            start = str(entry["start_date"] or "")
            end = str(entry["end_date"] or "")
            if act.start_date and (not start or act.start_date < start):
                entry["start_date"] = act.start_date
            if act.end_date and (not end or act.end_date > end):
                entry["end_date"] = act.end_date

        rows = [
            LaborCostByPhaseRow(
                phase=str(p["phase"]),
                activity_count=int(p["activity_count"]),
                labor_cost=round(float(p["labor_cost"]), 2),
                total_cost=round(float(p["total_cost"]), 2),
                start_date=(str(p["start_date"]) if p["start_date"] else None),
                end_date=(str(p["end_date"]) if p["end_date"] else None),
            )
            for p in sorted(
                phases.values(),
                key=lambda e: (str(e["start_date"] or ""), str(e["phase"])),
            )
        ]

        # Currency bug fix: label the response with the project's real
        # currency (loaded above) instead of the previous hardcoded "EUR".
        return LaborCostByPhaseResponse(phases=rows, currency=currency)
