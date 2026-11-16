# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Pure field-time engine - all validatable timesheet logic, zero I/O.

This module deliberately imports nothing from :mod:`app.database`, SQLAlchemy,
FastAPI or any ORM model. It is the single source of truth for the rules that
decide whether a foreman's field timesheet is well formed, how a worker's hours
sum across a day, which lines become daywork sheet lines, how hours roll up into
cost, and how a reversing timesheet nets against the original it corrects.

Keeping the logic here (instead of inside :class:`FieldTimesheetService`) means
every rule is unit-testable on any interpreter - including the local Python 3.11
runner - without booting a database, exactly like ``schedule.progress_math`` and
``boq.cost_risk_engine``.

Vocabulary:

* A *line* is one worker-hours or plant-hours booking. A line is *labour* when it
  carries a ``resource_id`` and *plant* when it carries an ``equipment_id``.
  Exactly one of the two identifies a well formed line (labour XOR plant).
* A *worker* is the labour ``resource_id``. Per-worker hours are summed across a
  single day's lines and capped so a day can never book more than 24 hours.
* A *daywork* line books time-and-material work performed under an open variation
  and, on approval, is mirrored into a signed daywork sheet.

Money is ``Decimal`` throughout - never ``float`` - and serialised to a string by
the caller, matching the platform-wide money convention.

International by design. Nothing here hard-codes one country's working day, week
start, overtime threshold, break rule, rounding step or currency:

* Hours are computed from timezone-aware (or consistently naive) ``datetime``
  values, never from a locale-formatted date string, so day / month order never
  matters. Night shifts that cross midnight are handled explicitly.
* Overtime is OFF by default. Overtime rules differ by country and contract, so
  hours are only split into regular / overtime when a project supplies a daily
  threshold. With no threshold every hour is ordinary time.
* Rounding is OFF by default. When a project supplies a rounding step (for
  example a quarter hour) each entry is rounded to it; otherwise hours are kept
  to two decimals as booked.
* The week can start on any weekday. The default is Monday (ISO 8601), but a
  project may set Sunday or Saturday.

These knobs are read from a timesheet's ``metadata`` by :func:`read_hours_config`
so no database column or schema change is needed to configure them per project.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any

# The hard ceiling on how many hours a single worker can book in one calendar
# day. A day has 24 hours; anything above is a data-entry error (a decimal typo,
# a double entry, or two crews booked under one person).
MAX_HOURS_PER_DAY: Decimal = Decimal("24")

# Minutes in an hour and the default first day of the week (0 = Monday, the
# ISO 8601 international standard). A project may override the week start.
_MINUTES_PER_HOUR: Decimal = Decimal("60")
DEFAULT_WEEK_STARTS_ON: int = 0

# Quantisation quanta - hours to 2 dp, money to 2 dp.
_HOURS_Q: Decimal = Decimal("0.01")
_MONEY_Q: Decimal = Decimal("0.01")

# Line kinds resolved from which identifier a line carries.
KIND_LABOUR = "labour"
KIND_PLANT = "plant"
KIND_AMBIGUOUS = "ambiguous"  # both a resource and an equipment id - not allowed
KIND_UNSPECIFIED = "unspecified"  # neither id and no explicit hint - not allowed


# ── Coercion helpers ────────────────────────────────────────────────────────


def to_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    """Coerce an arbitrary value to a finite ``Decimal``.

    Args:
        value: An int / float / str / Decimal (or None).
        default: What to return when ``value`` is None or cannot be parsed.

    Returns:
        The parsed ``Decimal``, preserving sign (a reversal uses negative
        hours), or ``default`` for None / non-numeric / non-finite input.
    """
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value if value.is_finite() else default
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default
    return parsed if parsed.is_finite() else default


def quantize_hours(value: object) -> Decimal:
    """Return ``value`` as a 2 dp ``Decimal`` number of hours."""
    return to_decimal(value).quantize(_HOURS_Q)


def quantize_money(value: object) -> Decimal:
    """Return ``value`` as a 2 dp ``Decimal`` money amount."""
    return to_decimal(value).quantize(_MONEY_Q)


def _clean_str(value: object) -> str:
    """Return a stripped string for ``value`` (``""`` for None)."""
    if value is None:
        return ""
    return str(value).strip()


def _get(line: Mapping[str, Any], key: str) -> object:
    """Read ``key`` from a line mapping, tolerating a missing key."""
    return line.get(key) if isinstance(line, Mapping) else None


# ── Line kind + completeness ────────────────────────────────────────────────


def resolve_line_kind(line: Mapping[str, Any]) -> str:
    """Resolve whether a line books labour or plant.

    The persisted invariant is labour XOR plant, but a draft payload may carry
    neither identifier yet (the foreman has picked a worker/machine but not
    saved) - in that case an explicit ``kind`` hint (``"labour"`` / ``"plant"``)
    still lets the completeness rules classify the intent.

    Returns:
        One of ``KIND_LABOUR``, ``KIND_PLANT``, ``KIND_AMBIGUOUS`` (both ids
        set) or ``KIND_UNSPECIFIED`` (neither id and no usable hint).
    """
    has_resource = bool(_clean_str(_get(line, "resource_id")))
    has_equipment = bool(_clean_str(_get(line, "equipment_id")))
    if has_resource and has_equipment:
        return KIND_AMBIGUOUS
    if has_resource:
        return KIND_LABOUR
    if has_equipment:
        return KIND_PLANT
    hint = _clean_str(_get(line, "kind")).lower()
    if hint in ("labour", "labor"):
        return KIND_LABOUR
    if hint in ("plant", "equipment"):
        return KIND_PLANT
    return KIND_UNSPECIFIED


@dataclass(frozen=True)
class LineCompleteness:
    """Outcome of checking one line for completeness.

    Attributes:
        passed: True when the line is well formed.
        kind: The resolved line kind (see :func:`resolve_line_kind`).
        reasons: Machine-readable reason codes for each failed check
            (``"labour_xor_plant"``, ``"hours_positive"``, ``"cost_code_required"``).
    """

    passed: bool
    kind: str
    reasons: tuple[str, ...] = ()


def line_completeness(line: Mapping[str, Any]) -> LineCompleteness:
    """Check a single line: labour XOR plant, hours > 0, cost_code present.

    Args:
        line: A line mapping with ``resource_id`` / ``equipment_id`` /
            ``hours`` / ``cost_code`` (and optional ``kind``).

    Returns:
        A :class:`LineCompleteness` capturing pass/fail plus reason codes.
    """
    reasons: list[str] = []
    kind = resolve_line_kind(line)
    if kind in (KIND_AMBIGUOUS, KIND_UNSPECIFIED):
        reasons.append("labour_xor_plant")
    if to_decimal(_get(line, "hours")) <= 0:
        reasons.append("hours_positive")
    if not _clean_str(_get(line, "cost_code")):
        reasons.append("cost_code_required")
    return LineCompleteness(passed=not reasons, kind=kind, reasons=tuple(reasons))


# ── Per-worker daily hours ──────────────────────────────────────────────────


def worker_key(line: Mapping[str, Any]) -> str | None:
    """Return the labour worker key (``resource_id``) for a line, else None.

    Plant lines (no ``resource_id``) return None - a machine is not a worker and
    is exempt from the per-worker daily cap.
    """
    resource_id = _clean_str(_get(line, "resource_id"))
    return resource_id or None


def sum_hours_by_worker(lines: Sequence[Mapping[str, Any]]) -> dict[str, Decimal]:
    """Sum labour hours per worker across a day's lines.

    Args:
        lines: The day's timesheet lines.

    Returns:
        ``{resource_id: total_hours}`` over labour lines only. Plant lines are
        ignored. Negative or non-numeric hours coerce to 0 so a stray value
        never understates a worker's day below what was actually booked.
    """
    totals: dict[str, Decimal] = {}
    for line in lines:
        key = worker_key(line)
        if key is None:
            continue
        hours = to_decimal(_get(line, "hours"))
        if hours < 0:
            hours = Decimal("0")
        totals[key] = totals.get(key, Decimal("0")) + hours
    return {key: value.quantize(_HOURS_Q) for key, value in totals.items()}


@dataclass(frozen=True)
class WorkerDayHours:
    """A worker's summed hours for a day, with the cap it is checked against."""

    worker_key: str
    hours: Decimal
    max_hours: Decimal

    @property
    def exceeds(self) -> bool:
        """True when the worker's hours exceed the daily cap."""
        return self.hours > self.max_hours


def hours_cap_exceedances(
    lines: Sequence[Mapping[str, Any]],
    *,
    max_hours: Decimal = MAX_HOURS_PER_DAY,
) -> list[WorkerDayHours]:
    """Return the workers whose summed daily hours exceed ``max_hours``.

    Args:
        lines: The day's timesheet lines.
        max_hours: The per-worker daily ceiling (default 24).

    Returns:
        One :class:`WorkerDayHours` per offending worker, sorted by worker key
        for deterministic output. Empty when every worker is within the cap.
    """
    exceed: list[WorkerDayHours] = []
    for key, hours in sorted(sum_hours_by_worker(lines).items()):
        if hours > max_hours:
            exceed.append(WorkerDayHours(worker_key=key, hours=hours, max_hours=max_hours))
    return exceed


# ── Daywork + plant completeness ────────────────────────────────────────────


def is_daywork_line(line: Mapping[str, Any]) -> bool:
    """Return True when a line is flagged as daywork (time-and-material)."""
    return bool(_get(line, "is_daywork"))


def daywork_incomplete_indices(
    lines: Sequence[Mapping[str, Any]],
    *,
    open_variation_ids: set[str] | None = None,
) -> list[int]:
    """Return indices of daywork lines that do not reference an open variation.

    A daywork line must name the variation it was performed under. When
    ``open_variation_ids`` is supplied, the referenced variation must also be
    open (still accepting cost). When it is None, only presence is checked - the
    caller could not resolve variation status, so we do not fail on it.

    Args:
        lines: The timesheet lines.
        open_variation_ids: Variation ids currently open, or None to skip the
            open-status check.

    Returns:
        Sorted list of offending line indices.
    """
    bad: list[int] = []
    for index, line in enumerate(lines):
        if not is_daywork_line(line):
            continue
        variation_id = _clean_str(_get(line, "variation_id"))
        if not variation_id:
            bad.append(index)
            continue
        if open_variation_ids is not None and variation_id not in open_variation_ids:
            bad.append(index)
    return bad


def plant_missing_equipment_indices(lines: Sequence[Mapping[str, Any]]) -> list[int]:
    """Return indices of plant-intent lines that name no equipment item.

    A line that declares plant work (via a ``"plant"`` kind hint) but carries no
    ``equipment_id`` cannot be costed against a machine. This is distinct from
    the labour-XOR-plant completeness error: here the intent is known (plant),
    only the specific machine is missing, so it is a warning the foreman can
    resolve by attaching the equipment.
    """
    bad: list[int] = []
    for index, line in enumerate(lines):
        if _clean_str(_get(line, "equipment_id")):
            continue
        hint = _clean_str(_get(line, "kind")).lower()
        if hint in ("plant", "equipment"):
            bad.append(index)
    return bad


def cost_code_unresolved_indices(
    lines: Sequence[Mapping[str, Any]],
    *,
    valid_cost_codes: set[str] | None,
    valid_wbs: set[str] | None,
) -> list[int]:
    """Return indices of lines whose cost_code / wbs resolves to no position.

    A line resolves when its ``cost_code`` is a known project cost code OR its
    ``wbs`` is a known project WBS code. Lines that carry neither code are left
    to :func:`line_completeness` (which requires a cost_code) and are not flagged
    here. When both resolver sets are None the caller could not load the
    project's codes, so nothing is flagged (resolution is deferred).

    Args:
        lines: The timesheet lines.
        valid_cost_codes: Known project cost codes, or None to skip.
        valid_wbs: Known project WBS codes, or None to skip.

    Returns:
        Sorted list of line indices whose codes resolve to nothing.
    """
    if valid_cost_codes is None and valid_wbs is None:
        return []
    codes = valid_cost_codes or set()
    wbs_codes = valid_wbs or set()
    bad: list[int] = []
    for index, line in enumerate(lines):
        cost_code = _clean_str(_get(line, "cost_code"))
        wbs = _clean_str(_get(line, "wbs"))
        if not cost_code and not wbs:
            continue  # completeness owns the "cost_code required" check
        if cost_code and cost_code in codes:
            continue
        if wbs and wbs in wbs_codes:
            continue
        bad.append(index)
    return bad


# ── Daywork sheet line mapping ──────────────────────────────────────────────


@dataclass(frozen=True)
class DayworkLineDraft:
    """A daywork sheet line derived from an approved daywork timesheet line.

    Mirrors the variations ``DayworkSheetLineCreate`` fields so the field-time
    service can hand it straight to the variations service without re-deriving.
    """

    line_type: str  # "labor" | "equipment" (variations vocabulary)
    description: str
    quantity: Decimal  # hours booked
    unit: str  # "h"
    unit_rate: Decimal  # cost rate per hour
    worker_name: str | None
    equipment_code: str | None
    source_line_id: str | None
    variation_id: str | None


def daywork_line_drafts(
    lines: Sequence[Mapping[str, Any]],
    *,
    labour_rates: Mapping[str, Decimal] | None = None,
    plant_rates: Mapping[str, Decimal] | None = None,
) -> list[DayworkLineDraft]:
    """Map the daywork lines of a timesheet to draft daywork sheet lines.

    Only lines flagged ``is_daywork`` are mapped - ordinary lines flow into cost
    actuals but never onto a signed daywork sheet. Labour lines become
    ``"labor"`` daywork lines, plant lines become ``"equipment"`` lines, and the
    hourly cost rate is looked up from the supplied rate maps (0 when unknown).

    Args:
        lines: The timesheet lines.
        labour_rates: ``{resource_id: hourly_rate}``.
        plant_rates: ``{equipment_id: hourly_rate}``.

    Returns:
        One :class:`DayworkLineDraft` per daywork line, in input order.
    """
    labour = labour_rates or {}
    plant = plant_rates or {}
    drafts: list[DayworkLineDraft] = []
    for line in lines:
        if not is_daywork_line(line):
            continue
        kind = resolve_line_kind(line)
        hours = quantize_hours(_get(line, "hours"))
        resource_id = _clean_str(_get(line, "resource_id"))
        equipment_id = _clean_str(_get(line, "equipment_id"))
        note = _clean_str(_get(line, "note"))
        if kind == KIND_PLANT:
            rate = to_decimal(plant.get(equipment_id)) if equipment_id else Decimal("0")
            line_type = "equipment"
        else:
            rate = to_decimal(labour.get(resource_id)) if resource_id else Decimal("0")
            line_type = "labor"
        drafts.append(
            DayworkLineDraft(
                line_type=line_type,
                description=note or _clean_str(_get(line, "cost_code")) or "Daywork",
                quantity=hours,
                unit="h",
                unit_rate=rate.quantize(Decimal("0.0001")),
                worker_name=resource_id or None,
                equipment_code=equipment_id or None,
                source_line_id=_clean_str(_get(line, "id")) or None,
                variation_id=_clean_str(_get(line, "variation_id")) or None,
            ),
        )
    return drafts


# ── Cost rollup ─────────────────────────────────────────────────────────────


def line_cost(hours: object, rate: object) -> Decimal:
    """Return ``hours * rate`` as a 2 dp money ``Decimal``."""
    return (to_decimal(hours) * to_decimal(rate)).quantize(_MONEY_Q)


@dataclass(frozen=True)
class CostRollup:
    """Hours and cost rolled up over a set of lines, split labour vs plant."""

    labour_hours: Decimal
    plant_hours: Decimal
    labour_cost: Decimal
    plant_cost: Decimal

    @property
    def total_hours(self) -> Decimal:
        """Combined labour + plant hours."""
        return (self.labour_hours + self.plant_hours).quantize(_HOURS_Q)

    @property
    def total_cost(self) -> Decimal:
        """Combined labour + plant cost."""
        return (self.labour_cost + self.plant_cost).quantize(_MONEY_Q)


def rollup(
    lines: Sequence[Mapping[str, Any]],
    *,
    labour_rates: Mapping[str, Decimal] | None = None,
    plant_rates: Mapping[str, Decimal] | None = None,
    rounding_increment: Decimal | None = None,
) -> CostRollup:
    """Roll a timesheet's lines up into labour/plant hours and cost.

    How the totals are derived, so a user is never surprised by them:

    * Every line's hours are counted, split by whether the line books a worker
      (labour) or a machine (plant).
    * Cost is ``hours * hourly_rate``. When a rate is not known the line still
      contributes its hours but zero cost, so an unpriced worker or machine is
      visible rather than silently dropped or given an invented rate.
    * When ``rounding_increment`` is given (for example a quarter hour) each
      line's hours are first rounded to that step, matching the project's
      timekeeping rule. With no step, hours are summed as booked.

    Args:
        lines: The timesheet lines.
        labour_rates: ``{resource_id: hourly_rate}``.
        plant_rates: ``{equipment_id: hourly_rate}``.
        rounding_increment: Optional per-entry rounding step in hours.

    Returns:
        A :class:`CostRollup`.
    """
    labour = labour_rates or {}
    plant = plant_rates or {}
    labour_hours = Decimal("0")
    plant_hours = Decimal("0")
    labour_cost = Decimal("0")
    plant_cost = Decimal("0")
    for line in lines:
        hours = to_decimal(_get(line, "hours"))
        if rounding_increment is not None:
            hours = round_to_increment(hours, rounding_increment)
        kind = resolve_line_kind(line)
        if kind == KIND_PLANT:
            equipment_id = _clean_str(_get(line, "equipment_id"))
            plant_hours += hours
            plant_cost += hours * to_decimal(plant.get(equipment_id))
        elif kind == KIND_LABOUR:
            resource_id = _clean_str(_get(line, "resource_id"))
            labour_hours += hours
            labour_cost += hours * to_decimal(labour.get(resource_id))
    return CostRollup(
        labour_hours=labour_hours.quantize(_HOURS_Q),
        plant_hours=plant_hours.quantize(_HOURS_Q),
        labour_cost=labour_cost.quantize(_MONEY_Q),
        plant_cost=plant_cost.quantize(_MONEY_Q),
    )


# ── Reversal netting ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TimesheetContribution:
    """One timesheet's signed contribution to a project's actual hours.

    Attributes:
        hours: The timesheet's total (positive) booked hours.
        is_reversal: True when this timesheet reverses another (contributes
            negative hours so an approved + reversal pair nets to zero).
    """

    hours: Decimal
    is_reversal: bool = False


def net_hours(contributions: Sequence[TimesheetContribution]) -> Decimal:
    """Net signed hours across timesheets, so a reversal cancels its original.

    A normal timesheet contributes ``+hours``; a reversal contributes
    ``-hours``. An approved timesheet plus a reversal that mirrors it therefore
    nets to exactly zero - the accounting-clean way to undo already-counted
    labour without deleting the audit trail.

    Args:
        contributions: The timesheets contributing to the total.

    Returns:
        The net hours as a 2 dp ``Decimal`` (may be zero or, transiently,
        negative if reversals exceed originals).
    """
    total = Decimal("0")
    for item in contributions:
        hours = to_decimal(item.hours)
        total += -hours if item.is_reversal else hours
    return total.quantize(_HOURS_Q)


def reverse_lines(lines: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Build the line payload for a reversing timesheet from an original.

    The reversal mirrors every original line verbatim (same worker/plant, hours,
    cost_code, bill position, daywork/variation link) so the reversal is a
    faithful negative of what it corrects. Hours stay positive on the row; the *timesheet* carries the
    reversal sign (see :func:`net_hours`), matching how the payroll and cost
    consumers net an approved original against its reversal.

    Args:
        lines: The original timesheet's lines (mappings).

    Returns:
        A list of plain dicts ready to persist as the reversal's lines.
    """
    mirrored: list[dict[str, Any]] = []
    for line in lines:
        mirrored.append(
            {
                "resource_id": _clean_str(_get(line, "resource_id")) or None,
                "equipment_id": _clean_str(_get(line, "equipment_id")) or None,
                "hours": quantize_hours(_get(line, "hours")),
                "cost_code": _clean_str(_get(line, "cost_code")),
                "wbs": _clean_str(_get(line, "wbs")) or None,
                "boq_position_id": _clean_str(_get(line, "boq_position_id")) or None,
                "is_daywork": bool(_get(line, "is_daywork")),
                "variation_id": _clean_str(_get(line, "variation_id")) or None,
                "hour_type": _clean_str(_get(line, "hour_type")) or "regular",
                "note": _clean_str(_get(line, "note")),
            },
        )
    return mirrored


# ── Rounding, worked-interval hours and overtime (international) ──────────────


def round_to_increment(
    value: object,
    increment: object,
    *,
    rounding: str = ROUND_HALF_UP,
) -> Decimal:
    """Round a number of hours to the nearest ``increment`` step.

    Timekeeping rules round to different steps around the world (a quarter hour,
    a tenth of an hour, six minutes). This applies whichever step the project
    uses. A zero, negative or unparseable ``increment`` means "do not round" and
    the value is returned to two decimals as booked.

    Args:
        value: The hours to round.
        increment: The step to round to, e.g. ``Decimal("0.25")``.
        rounding: A ``decimal`` rounding mode (default round half up).

    Returns:
        The rounded hours as a 2 dp ``Decimal``.
    """
    hours = to_decimal(value)
    step = to_decimal(increment)
    if step <= 0:
        return hours.quantize(_HOURS_Q)
    steps = (hours / step).quantize(Decimal("1"), rounding=rounding)
    return (steps * step).quantize(_HOURS_Q)


# Reason codes a worked interval can fail with (empty when it is valid).
INTERVAL_OK = ""
INTERVAL_TIMES_REQUIRED = "times_required"
INTERVAL_TIMEZONE_MISMATCH = "timezone_mismatch"
INTERVAL_END_BEFORE_START = "end_before_start"
INTERVAL_ZERO_LENGTH = "zero_length"
INTERVAL_OVER_24H = "over_24h"
INTERVAL_BREAK_NEGATIVE = "break_negative"
INTERVAL_BREAK_EXCEEDS_SHIFT = "break_exceeds_shift"


@dataclass(frozen=True)
class WorkedInterval:
    """Net worked hours derived from a start time, an end time and a break.

    Attributes:
        net_hours: Paid hours = gross shift minus the unpaid break.
        gross_hours: End minus start (after any overnight adjustment).
        break_hours: The unpaid break, converted from minutes.
        valid: True when the interval is well formed.
        reason: A machine-readable reason code when ``valid`` is False, one of
            the ``INTERVAL_*`` constants (empty when valid).
    """

    net_hours: Decimal
    gross_hours: Decimal
    break_hours: Decimal
    valid: bool
    reason: str = INTERVAL_OK


def worked_hours(
    start: object,
    end: object,
    break_minutes: object = 0,
    *,
    allow_overnight: bool = True,
) -> WorkedInterval:
    """Compute net worked hours from a start / end time and an unpaid break.

    Timezone-safe and locale-independent: it works on ``datetime`` objects, not
    formatted strings, so no day / month order is ever assumed. Both times must
    be either timezone-aware or both naive; mixing the two is rejected rather
    than guessed. A shift that ends at or before it starts is read as crossing
    midnight (a night shift) when ``allow_overnight`` is set, otherwise it is an
    error.

    Guards, each with a clear reason code:

    * ``times_required``   - start or end is not a datetime.
    * ``timezone_mismatch``- one time is timezone-aware and the other is not.
    * ``end_before_start`` - end is before start and overnight is not allowed.
    * ``zero_length``      - start and end are the same instant.
    * ``over_24h``         - a single continuous shift longer than 24 hours.
    * ``break_negative``   - the break is a negative number of minutes.
    * ``break_exceeds_shift`` - the break is as long as, or longer than, the shift.

    Args:
        start: Shift start ``datetime``.
        end: Shift end ``datetime``.
        break_minutes: Unpaid break length in minutes (default 0).
        allow_overnight: Treat ``end <= start`` as a night shift (default True).

    Returns:
        A :class:`WorkedInterval`. On any failure ``net_hours`` is the best
        available estimate (0 when it cannot be computed) and ``valid`` is False.
    """
    zero = Decimal("0")
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return WorkedInterval(zero, zero, zero, valid=False, reason=INTERVAL_TIMES_REQUIRED)
    if (start.tzinfo is None) != (end.tzinfo is None):
        return WorkedInterval(zero, zero, zero, valid=False, reason=INTERVAL_TIMEZONE_MISMATCH)

    minutes = to_decimal(break_minutes)
    break_hours = (minutes / _MINUTES_PER_HOUR).quantize(_HOURS_Q)
    if minutes < 0:
        return WorkedInterval(zero, zero, break_hours, valid=False, reason=INTERVAL_BREAK_NEGATIVE)

    end_effective = end
    if allow_overnight and end < start:
        end_effective = end + timedelta(days=1)
    gross_seconds = Decimal(str((end_effective - start).total_seconds()))
    gross_hours = (gross_seconds / Decimal("3600")).quantize(_HOURS_Q)

    if gross_hours == 0:
        return WorkedInterval(zero, gross_hours, break_hours, valid=False, reason=INTERVAL_ZERO_LENGTH)
    if gross_hours < 0:
        return WorkedInterval(zero, gross_hours, break_hours, valid=False, reason=INTERVAL_END_BEFORE_START)
    if gross_hours > MAX_HOURS_PER_DAY:
        net = (gross_hours - break_hours).quantize(_HOURS_Q)
        return WorkedInterval(net, gross_hours, break_hours, valid=False, reason=INTERVAL_OVER_24H)
    if break_hours >= gross_hours:
        return WorkedInterval(zero, gross_hours, break_hours, valid=False, reason=INTERVAL_BREAK_EXCEEDS_SHIFT)

    net = (gross_hours - break_hours).quantize(_HOURS_Q)
    return WorkedInterval(net, gross_hours, break_hours, valid=True, reason=INTERVAL_OK)


@dataclass(frozen=True)
class DerivedDuration:
    """The hours a line should carry, and where they came from.

    Attributes:
        hours: The hours to store. Derived from the clock times when they are
            there, otherwise the hours as booked by hand.
        derived: True when the figure came from the times rather than the hand.
        reason: An ``INTERVAL_*`` code when clock times were given but cannot
            produce a duration (empty otherwise). The caller refuses the write:
            a line whose times cannot be read must not fall back to a typed
            number, because the two would then say different things.
    """

    hours: Decimal
    derived: bool
    reason: str = INTERVAL_OK


def derive_line_hours(
    start: object,
    end: object,
    break_minutes: object = 0,
    *,
    booked_hours: object = 0,
) -> DerivedDuration:
    """Decide a line's hours from its clock times, or leave the booked figure alone.

    A line that carries a start and an end has exactly one duration and it is
    the one those times produce, less the unpaid break. A line without them
    keeps the hours somebody typed. There is deliberately no third state where a
    line has both times and an independent number, because that number could
    disagree with them and an audit would have no way to tell which was true.

    Not rounded, whatever rounding step the project uses for its payroll
    figures: the recorded duration has to be the duration the times produce, and
    a quarter-hour step would make it something else.

    Args:
        start: Shift start ``datetime``, or None.
        end: Shift end ``datetime``, or None.
        break_minutes: Unpaid break in minutes (None reads as 0).
        booked_hours: The hours as typed, used when there are no clock times.

    Returns:
        A :class:`DerivedDuration`.
    """
    booked = to_decimal(booked_hours)
    has_start = isinstance(start, datetime)
    has_end = isinstance(end, datetime)
    if not has_start and not has_end:
        return DerivedDuration(hours=booked, derived=False)
    if not (has_start and has_end):
        return DerivedDuration(hours=booked, derived=False, reason=INTERVAL_TIMES_REQUIRED)
    interval = worked_hours(start, end, break_minutes if break_minutes is not None else 0)
    if not interval.valid:
        return DerivedDuration(hours=booked, derived=False, reason=interval.reason)
    return DerivedDuration(hours=interval.net_hours, derived=True)


def _interval_bounds(entry: Mapping[str, Any]) -> tuple[datetime, datetime] | None:
    """Return ``(start, end)`` datetimes for an entry, or None when not usable."""
    start = _get(entry, "start")
    end = _get(entry, "end")
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return None
    return start, end


def overlapping_worker_intervals(
    entries: Sequence[Mapping[str, Any]],
) -> list[tuple[int, int]]:
    """Find pairs of entries for the same worker whose clock times overlap.

    A worker cannot be in two places at once, so two started-and-ended intervals
    for the same ``resource_id`` (or explicit ``worker_key``) that overlap in
    time are almost always a double booking. Entries without both a start and an
    end, or without a worker, are skipped (there is nothing to compare). Times
    that cannot be compared (one aware, one naive) are skipped rather than
    guessed.

    Args:
        entries: Mappings carrying ``resource_id`` / ``worker_key`` plus
            ``start`` and ``end`` datetimes.

    Returns:
        Sorted, de-duplicated ``(index_a, index_b)`` pairs that overlap.
    """
    by_worker: dict[str, list[int]] = {}
    for index, entry in enumerate(entries):
        worker = worker_key(entry) or (_clean_str(_get(entry, "worker_key")) or None)
        if worker is None or _interval_bounds(entry) is None:
            continue
        by_worker.setdefault(worker, []).append(index)

    pairs: set[tuple[int, int]] = set()
    for indices in by_worker.values():
        # Order by an ISO string key so mixing tz-aware and naive starts (which
        # cannot be compared directly) only affects ordering, never raises. The
        # actual overlap test below still skips any pair that is not comparable.
        ordered = sorted(indices, key=lambda i: entries[i]["start"].isoformat())
        for pos_a in range(len(ordered)):
            bounds_a = _interval_bounds(entries[ordered[pos_a]])
            if bounds_a is None:
                continue
            start_a, end_a = bounds_a
            for pos_b in range(pos_a + 1, len(ordered)):
                bounds_b = _interval_bounds(entries[ordered[pos_b]])
                if bounds_b is None:
                    continue
                start_b, end_b = bounds_b
                try:
                    overlaps = start_a < end_b and start_b < end_a
                except TypeError:
                    continue  # not comparable (mixed tz-awareness) - skip
                if overlaps:
                    pairs.add(tuple(sorted((ordered[pos_a], ordered[pos_b]))))
    return sorted(pairs)


@dataclass(frozen=True)
class OvertimeSplit:
    """Regular vs overtime hours for a single value, against a daily threshold."""

    regular_hours: Decimal
    overtime_hours: Decimal


def split_overtime(hours: object, *, daily_threshold: object = None) -> OvertimeSplit:
    """Split a number of hours into regular and overtime against a threshold.

    Overtime is only computed when a project supplies ``daily_threshold``. With
    no threshold (the worldwide default), every hour is regular time and no
    country-specific rule is assumed. Hours below zero are clamped to zero so a
    stray negative never invents overtime.

    Args:
        hours: The hours worked.
        daily_threshold: Hours above which the rest is overtime, or None.

    Returns:
        An :class:`OvertimeSplit`.
    """
    worked = to_decimal(hours)
    if worked < 0:
        worked = Decimal("0")
    threshold = to_decimal(daily_threshold) if daily_threshold is not None else None
    if threshold is None or threshold <= 0 or worked <= threshold:
        return OvertimeSplit(worked.quantize(_HOURS_Q), Decimal("0.00"))
    return OvertimeSplit(
        threshold.quantize(_HOURS_Q),
        (worked - threshold).quantize(_HOURS_Q),
    )


def daily_overtime(
    lines: Sequence[Mapping[str, Any]],
    *,
    daily_threshold: object,
) -> Decimal:
    """Total overtime hours across all workers on a day, above ``daily_threshold``.

    Sums each worker's day (see :func:`sum_hours_by_worker`) and counts only the
    hours above the threshold. Returns zero when no threshold is set, so a
    project that does not define overtime simply reports none.

    Args:
        lines: The day's timesheet lines.
        daily_threshold: Per-worker daily overtime threshold, or a falsy value.

    Returns:
        The total overtime hours as a 2 dp ``Decimal``.
    """
    threshold = to_decimal(daily_threshold)
    if threshold <= 0:
        return Decimal("0.00")
    total = Decimal("0")
    for hours in sum_hours_by_worker(lines).values():
        if hours > threshold:
            total += hours - threshold
    return total.quantize(_HOURS_Q)


def week_start(day: date, *, week_starts_on: int = DEFAULT_WEEK_STARTS_ON) -> date:
    """Return the first day of the week containing ``day``.

    The week can start on any weekday so weekly hour totals line up with local
    practice: 0 is Monday (ISO 8601, the default), 6 is Sunday. An out-of-range
    value falls back to Monday.

    Args:
        day: Any date within the week.
        week_starts_on: Weekday the week starts on, 0 (Monday) to 6 (Sunday).

    Returns:
        The date of the first day of that week.
    """
    if week_starts_on not in range(7):
        week_starts_on = DEFAULT_WEEK_STARTS_ON
    offset = (day.weekday() - week_starts_on) % 7
    return day - timedelta(days=offset)


# ── Per-project hours configuration (read from timesheet metadata) ───────────


@dataclass(frozen=True)
class HoursConfig:
    """A project's timekeeping rules, with worldwide-safe defaults.

    All fields default to "no local assumption": a full 24 hour day ceiling, no
    overtime, no rounding, and a Monday week start (ISO 8601). A project tunes
    these by writing them into a timesheet's ``metadata`` - no schema change.
    """

    max_hours_per_day: Decimal = MAX_HOURS_PER_DAY
    overtime_daily_threshold: Decimal | None = None
    rounding_increment: Decimal | None = None
    week_starts_on: int = DEFAULT_WEEK_STARTS_ON


def read_hours_config(metadata: Mapping[str, Any] | None) -> HoursConfig:
    """Parse a :class:`HoursConfig` from a timesheet's metadata mapping.

    Recognised keys (all optional):

    * ``max_hours_per_day``       - per-worker daily ceiling, 0 < x <= 24.
    * ``overtime_daily_threshold``- hours above which time is overtime.
    * ``hours_rounding_increment``- rounding step in hours (e.g. 0.25).
    * ``week_starts_on``          - 0 (Monday) to 6 (Sunday).

    Any missing, malformed or out-of-range value falls back to the safe default
    so bad metadata can never break a timesheet - it just uses the default rule.

    Args:
        metadata: The timesheet ``metadata`` mapping, or None.

    Returns:
        A :class:`HoursConfig`.
    """
    meta = metadata if isinstance(metadata, Mapping) else {}

    max_hours = to_decimal(meta.get("max_hours_per_day"), default=MAX_HOURS_PER_DAY)
    if not (Decimal("0") < max_hours <= MAX_HOURS_PER_DAY):
        max_hours = MAX_HOURS_PER_DAY

    overtime: Decimal | None = None
    raw_overtime = meta.get("overtime_daily_threshold")
    if raw_overtime is not None:
        parsed = to_decimal(raw_overtime)
        if parsed > 0:
            overtime = parsed

    rounding: Decimal | None = None
    raw_rounding = meta.get("hours_rounding_increment")
    if raw_rounding is not None:
        parsed_round = to_decimal(raw_rounding)
        if parsed_round > 0:
            rounding = parsed_round

    week_starts_on = DEFAULT_WEEK_STARTS_ON
    raw_week = meta.get("week_starts_on")
    if isinstance(raw_week, int) and raw_week in range(7):
        week_starts_on = raw_week

    return HoursConfig(
        max_hours_per_day=max_hours,
        overtime_daily_threshold=overtime,
        rounding_increment=rounding,
        week_starts_on=week_starts_on,
    )


# ── Offline capture (a day recorded on a phone with no signal) ───────────────
#
# A foreman in a basement, a lift shaft or a rural site records the day on the
# phone and the entry sits in a local queue until there is signal again. The
# timesheet that eventually lands carries a record of that journey under the
# ``offline`` key of its metadata, and the two functions below read it.
#
# Nothing here decides whether a timesheet is acceptable - both findings are
# advisory. Refusing a day because the phone that recorded it had a wrong clock,
# or because the site had no signal for a fortnight, would destroy exactly the
# hours this whole path exists to save.

# The metadata key under which the offline journey is recorded.
OFFLINE_METADATA_KEY = "offline"

# How far ahead of the server a device clock may read before the capture stamp
# is called wrong. Phones drift by seconds and timezone handling can cost an
# hour, so the tolerance is generous; it still catches a device set to the wrong
# day or year, which is the case that makes a capture time meaningless.
OFFLINE_CLOCK_TOLERANCE_MINUTES: int = 60

# A day that reaches the server later than this after it was worked is flagged
# for whoever approves it. A fortnight is a phone that missed a whole pay cycle.
OFFLINE_SYNC_DELAY_WARN_DAYS: int = 14


@dataclass(frozen=True)
class OfflineCapture:
    """What a timesheet records about having been captured away from the network.

    Attributes:
        recorded: True when the timesheet carries an offline capture record at
            all. False for an ordinary desk-entered timesheet, and then every
            offline finding is skipped rather than guessed.
        entry_key: The client-generated key that identifies this logical entry
            across every replay of it. Empty when the record omits it.
        captured_at: When the device says the foreman wrote the day down.
        synced_at: When the entry actually reached the server.
        device: A free-text device label, for tracing one phone's entries.
    """

    recorded: bool = False
    entry_key: str = ""
    captured_at: datetime | None = None
    synced_at: datetime | None = None
    device: str = ""


def _parse_instant(value: object) -> datetime | None:
    """Coerce a ``datetime`` or an ISO-8601 string to an aware ``datetime``.

    Metadata arrives as JSON, so a capture time is a string by the time it gets
    here. A naive value is read as UTC: the alternative is to drop it, and a
    capture time that is merely missing a zone still orders correctly against
    another value read the same way.

    Args:
        value: A ``datetime``, an ISO-8601 string (``Z`` suffix allowed), or
            anything else.

    Returns:
        A timezone-aware ``datetime``, or None when the value is not a time.
    """
    parsed: datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        # ``fromisoformat`` learned "Z" in 3.11; normalise anyway so the parse
        # does not depend on the interpreter this runs on.
        if text.endswith(("Z", "z")):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed is None:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def read_offline_capture(metadata: Mapping[str, Any] | None) -> OfflineCapture:
    """Parse the offline capture record from a timesheet's metadata.

    Any missing or malformed field degrades to "not recorded" for that field
    rather than raising, so a phone that writes a half-formed record still gets
    its hours in - it just yields no finding.

    Args:
        metadata: The timesheet ``metadata`` mapping, or None.

    Returns:
        An :class:`OfflineCapture`. ``recorded`` is False when the metadata
        carries no ``offline`` mapping at all.
    """
    meta = metadata if isinstance(metadata, Mapping) else {}
    raw = meta.get(OFFLINE_METADATA_KEY)
    if not isinstance(raw, Mapping):
        return OfflineCapture()
    return OfflineCapture(
        recorded=True,
        entry_key=_clean_str(raw.get("entry_key")),
        captured_at=_parse_instant(raw.get("captured_at")),
        synced_at=_parse_instant(raw.get("synced_at")),
        device=_clean_str(raw.get("device")),
    )


def offline_clock_ahead_minutes(
    capture: OfflineCapture,
    *,
    now: datetime | None = None,
) -> int | None:
    """Whole minutes by which the device clock ran ahead of the server.

    A capture stamp later than the moment the entry arrived is impossible: the
    foreman cannot have written the day down after the server received it. It
    means the phone's clock is wrong, which matters because a human reading two
    entries side by side will believe those timestamps.

    Args:
        capture: The parsed offline record.
        now: The instant to compare against. Defaults to the record's own
            ``synced_at``, which is when the entry actually landed.

    Returns:
        Minutes ahead (always positive), or None when there is nothing to
        compare - no capture time, or no arrival time to compare it with.
    """
    if not capture.recorded or capture.captured_at is None:
        return None
    reference = now if now is not None else capture.synced_at
    if reference is None:
        return None
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    ahead = (capture.captured_at - reference).total_seconds()
    if ahead <= 0:
        return None
    return int(ahead // 60)


def offline_sync_delay_days(capture: OfflineCapture, work_date: object) -> int | None:
    """Whole days between the day worked and the day the entry reached the server.

    This is the number an approver needs: hours booked against a fortnight-old
    day have already missed a valuation and possibly a payroll run, and the
    approver is the last person who can catch that.

    Args:
        capture: The parsed offline record.
        work_date: The timesheet's work date (a ``date``, or an ISO string).

    Returns:
        Whole days of delay (0 when it arrived the same day or earlier), or None
        when either end of the span is unknown.
    """
    if not capture.recorded or capture.synced_at is None:
        return None
    worked: date | None = None
    if isinstance(work_date, datetime):
        worked = work_date.date()
    elif isinstance(work_date, date):
        worked = work_date
    elif isinstance(work_date, str) and work_date.strip():
        try:
            worked = date.fromisoformat(work_date.strip()[:10])
        except ValueError:
            return None
    if worked is None:
        return None
    delay = (capture.synced_at.date() - worked).days
    return max(delay, 0)


# ── Cost-code suggestions (AI-augmented, human-confirmed) ────────────────────


@dataclass(frozen=True)
class CostCodeSuggestion:
    """A ranked cost-code suggestion for a line, with a confidence score.

    A suggestion is never auto-applied: the API returns it, the foreman confirms
    it, and only then does the line's ``cost_code`` change. ``confidence`` is a
    0.0-1.0 text-similarity score, never a certainty.
    """

    code: str
    label: str
    confidence: float


def _normalise_text(value: str) -> str:
    """Lower-case and collapse a string for fuzzy matching."""
    return " ".join(value.lower().split())


def suggest_cost_codes(
    text: str,
    candidates: Sequence[Mapping[str, Any]],
    *,
    limit: int = 5,
    min_confidence: float = 0.0,
) -> list[CostCodeSuggestion]:
    """Rank candidate cost codes by textual similarity to ``text``.

    A deterministic, dependency-free heuristic (difflib ratio over the candidate
    code + label versus the line's description) that PROPOSES cost codes for a
    line. It never applies them - the caller returns the ranked list to the user
    for confirmation, honouring the AI-augmented / human-confirmed principle.

    Args:
        text: The line description / note to match against.
        candidates: ``[{"code": ..., "label": ...}, ...]`` project cost codes.
        limit: Maximum suggestions to return.
        min_confidence: Drop suggestions below this score.

    Returns:
        Up to ``limit`` :class:`CostCodeSuggestion` sorted by confidence
        descending (ties broken by code for stable output).
    """
    needle = _normalise_text(_clean_str(text))
    if not needle:
        return []
    scored: list[CostCodeSuggestion] = []
    for candidate in candidates:
        code = _clean_str(_get(candidate, "code"))
        if not code:
            continue
        label = _clean_str(_get(candidate, "label"))
        haystack = _normalise_text(f"{code} {label}".strip())
        ratio = SequenceMatcher(None, needle, haystack).ratio()
        confidence = round(ratio, 4)
        if confidence >= min_confidence:
            scored.append(CostCodeSuggestion(code=code, label=label, confidence=confidence))
    scored.sort(key=lambda item: (-item.confidence, item.code))
    return scored[: max(0, limit)]


# ── Aggregate validation summary (used by the service before persistence) ────


@dataclass
class TimesheetChecks:
    """A flat summary of every field-time check over one timesheet payload.

    The service builds this to decide whether a submit is allowed (any
    ``blocking`` reason is an ERROR) and to surface warnings. The colocated
    validation rules recompute the same primitives for the traffic-light
    dashboard, so this stays a convenience aggregate, not a second source of
    truth.
    """

    incomplete_line_indices: list[int] = field(default_factory=list)
    hours_cap_exceedances: list[WorkerDayHours] = field(default_factory=list)
    unresolved_cost_code_indices: list[int] = field(default_factory=list)
    daywork_incomplete_indices: list[int] = field(default_factory=list)
    plant_missing_equipment_indices: list[int] = field(default_factory=list)
    # Pairs of line indices that book the same worker over overlapping clock
    # times (a double booking). Only populated when lines carry start / end.
    overlapping_worker_line_pairs: list[tuple[int, int]] = field(default_factory=list)

    @property
    def has_blocking_errors(self) -> bool:
        """True when any ERROR-severity condition is present."""
        return any(
            (
                self.incomplete_line_indices,
                self.hours_cap_exceedances,
                self.unresolved_cost_code_indices,
                self.overlapping_worker_line_pairs,
            ),
        )


def check_timesheet(
    lines: Sequence[Mapping[str, Any]],
    *,
    valid_cost_codes: set[str] | None = None,
    valid_wbs: set[str] | None = None,
    open_variation_ids: set[str] | None = None,
    max_hours: Decimal = MAX_HOURS_PER_DAY,
) -> TimesheetChecks:
    """Run every timesheet check and return a flat summary.

    Args:
        lines: The timesheet lines.
        valid_cost_codes: Known project cost codes (None to skip resolution).
        valid_wbs: Known project WBS codes (None to skip resolution).
        open_variation_ids: Open variation ids (None to skip the open check).
        max_hours: Per-worker daily cap.

    Returns:
        A :class:`TimesheetChecks` aggregate.
    """
    incomplete = [i for i, line in enumerate(lines) if not line_completeness(line).passed]
    return TimesheetChecks(
        incomplete_line_indices=incomplete,
        hours_cap_exceedances=hours_cap_exceedances(lines, max_hours=max_hours),
        unresolved_cost_code_indices=cost_code_unresolved_indices(
            lines,
            valid_cost_codes=valid_cost_codes,
            valid_wbs=valid_wbs,
        ),
        daywork_incomplete_indices=daywork_incomplete_indices(
            lines,
            open_variation_ids=open_variation_ids,
        ),
        plant_missing_equipment_indices=plant_missing_equipment_indices(lines),
        overlapping_worker_line_pairs=overlapping_worker_intervals(lines),
    )
