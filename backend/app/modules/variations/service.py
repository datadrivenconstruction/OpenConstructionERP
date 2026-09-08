# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Variations service - business logic for the variations lifecycle.

Pure helpers (top-level functions) are unit-tested directly. The
:class:`VariationsService` class wires repositories together and emits
domain events on state transitions.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from datetime import date as dt_date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.day_basis import CALENDAR, add_days
from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.money import money_quantum
from app.core.validation.messages import translate
from app.modules.variations.models import (
    DayworkSheet,
    DayworkSheetLine,
    DisruptionClaim,
    ExtensionOfTimeClaim,
    FinalAccount,
    Notice,
    SiteMeasurement,
    VariationBOQTrace,
    VariationCostImpact,
    VariationOrder,
    VariationRequest,
    VariationScheduleImpact,
)
from app.modules.variations.repository import (
    DayworkSheetLineRepository,
    DayworkSheetRepository,
    DisruptionClaimRepository,
    ExtensionOfTimeClaimRepository,
    FinalAccountRepository,
    NoticeRepository,
    SiteMeasurementRepository,
    VariationBOQTraceRepository,
    VariationCostImpactRepository,
    VariationOrderRepository,
    VariationRequestRepository,
    VariationScheduleImpactRepository,
)
from app.modules.variations.schemas import (
    DayworkSheetCreate,
    DayworkSheetLineCreate,
    DayworkSheetLineUpdate,
    DayworkSheetUpdate,
    DisruptionClaimCreate,
    DisruptionClaimUpdate,
    ExtensionOfTimeClaimCreate,
    ExtensionOfTimeClaimUpdate,
    FinalAccountCreate,
    FinalAccountUpdate,
    NoticeCreate,
    NoticeUpdate,
    SiteMeasurementCreate,
    SiteMeasurementUpdate,
    VariationBOQCreate,
    VariationBOQLineTraceUpdate,
    VariationCostImpactCreate,
    VariationCostImpactUpdate,
    VariationOrderCreate,
    VariationOrderUpdate,
    VariationRequestCreate,
    VariationRequestUpdate,
    VariationScheduleImpactCreate,
    VariationScheduleImpactUpdate,
)

logger = logging.getLogger(__name__)


# ── R5 audit: variations-specific tunables ─────────────────────────────────

# High-value approval threshold - VRs / VOs whose cost impact exceeds this
# amount require ``variations.approve_high_value`` (admin-only) on top of
# the standard ``variations.approve_request`` / ``variations.create``
# (manager+) gate. Currency-agnostic by design - the row-level currency is
# the contractual unit, so FX-normalising here would let a "small approval"
# silently authorise a large amount once FX drifted.
HIGH_VALUE_APPROVAL_THRESHOLD: Decimal = Decimal("100000")

# Bulk-endpoint cap - single POST cannot push more rows than this. Prevents
# allowlist-gap DoS on ``bulk_cost_impacts`` / ``bulk_daywork_lines`` where
# nothing else bounds the payload size.
BULK_LINES_MAX: int = 500


# ── State machines ─────────────────────────────────────────────────────────

NOTICE_TRANSITIONS: dict[str, list[str]] = {
    "issued": ["acknowledged", "closed"],
    "acknowledged": ["responded", "closed"],
    "responded": ["closed"],
    "closed": [],
}

VR_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["submitted"],
    "submitted": ["under_review", "approved", "rejected"],
    "under_review": ["approved", "rejected"],
    "approved": ["converted_to_vo"],
    "rejected": ["draft"],
    "converted_to_vo": [],
}

VO_TRANSITIONS: dict[str, list[str]] = {
    "issued": ["in_progress", "voided"],
    "in_progress": ["completed", "voided"],
    "completed": [],
    "voided": [],
}

DAYWORK_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["signed", "disputed"],
    "signed": ["billed", "disputed"],
    "disputed": ["draft", "signed"],
    "billed": [],
}

DISRUPTION_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["submitted"],
    "submitted": ["under_review", "agreed", "rejected"],
    "under_review": ["agreed", "rejected"],
    "agreed": [],
    "rejected": ["draft"],
}

EOT_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["submitted"],
    "submitted": ["under_review", "granted", "rejected"],
    "under_review": ["granted", "rejected"],
    "granted": [],
    "rejected": ["draft"],
}

FA_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["agreed", "disputed"],
    "agreed": ["closed", "disputed"],
    "disputed": ["draft", "agreed"],
    "closed": [],
}


def allowed_notice_transitions(current: str) -> list[str]:
    """Pure: return list of statuses Notice may move to from ``current``."""
    return list(NOTICE_TRANSITIONS.get(current, []))


def allowed_vr_transitions(current: str) -> list[str]:
    """Pure: return list of statuses VariationRequest may move to."""
    return list(VR_TRANSITIONS.get(current, []))


def allowed_vo_transitions(current: str) -> list[str]:
    """Pure: return list of statuses VariationOrder may move to."""
    return list(VO_TRANSITIONS.get(current, []))


def allowed_daywork_transitions(current: str) -> list[str]:
    """Pure: return list of statuses DayworkSheet may move to."""
    return list(DAYWORK_TRANSITIONS.get(current, []))


def allowed_disruption_transitions(current: str) -> list[str]:
    """Pure: return list of statuses DisruptionClaim may move to."""
    return list(DISRUPTION_TRANSITIONS.get(current, []))


def allowed_eot_transitions(current: str) -> list[str]:
    """Pure: return list of statuses ExtensionOfTimeClaim may move to."""
    return list(EOT_TRANSITIONS.get(current, []))


def allowed_final_account_transitions(current: str) -> list[str]:
    """Pure: return list of statuses FinalAccount may move to."""
    return list(FA_TRANSITIONS.get(current, []))


# ── Pure compute helpers ───────────────────────────────────────────────────


def _to_decimal(value: Any) -> Decimal:
    """Coerce an int/float/str/Decimal to Decimal, returning 0 on bad input."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _project_fx_map(project: Any) -> dict[str, Decimal]:
    """Project ``Project.fx_rates`` into ``{CODE: rate}`` as exact Decimals.

    Mirrors ``changeorders/repository.py::_project_fx_map`` and
    ``boq/service.py::_project_fx_map`` (shape
    ``[{"code": "USD", "rate": "1.08", "label": "US Dollar"}]`` where
    ``rate`` is BASE units per 1 unit of the foreign currency). Defensive
    against missing attribute / malformed entries -- a bad row is skipped.
    """
    if project is None:
        return {}
    raw = getattr(project, "fx_rates", None)
    if not isinstance(raw, list):
        return {}
    out: dict[str, Decimal] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip().upper()
        rate = _to_decimal(entry.get("rate"))
        if code and rate > 0:
            out[code] = rate
    return out


def _convert_money_buckets(
    by_currency: dict[str, Decimal],
    base_code: str,
    fx_map: dict[str, Decimal],
) -> tuple[Decimal, dict[str, Decimal]]:
    """Fold per-currency money buckets into a single base-currency total.

    Currency bug fix: blending raw amounts of different ISO currencies is
    meaningless, so each bucket is converted to the project BASE currency
    via ``fx_map`` before summing. A bucket that is already in the base
    currency (or carries a blank currency -- treated as "already base")
    passes through unchanged. A FOREIGN bucket with NO FX rate is NEVER
    folded into the base total; it is returned separately under
    ``unconverted`` so the figure stays honest rather than silently wrong.

    Returns ``(base_total, unconverted_by_currency)``.
    """
    base = (base_code or "").strip().upper()
    total = Decimal("0")
    unconverted: dict[str, Decimal] = {}
    for raw_code, amount in by_currency.items():
        code = (raw_code or "").strip().upper()
        if not code or code == base:
            # Already in the project base currency (or no currency stamp).
            total += amount
            continue
        fx = fx_map.get(code)
        if fx is not None:
            total += amount * fx
        else:
            # Foreign currency with no FX rate -- keep it visible per
            # currency instead of mis-stamping it as base currency.
            unconverted[code] = unconverted.get(code, Decimal("0")) + amount
    return total, unconverted


#: Two money figures closer than this are the same number. Both sides are
#: rounded to cents before they meet, so a sub-cent gap is rounding.
_MONEY_EPSILON = Decimal("0.01")

#: Why an approved variation's agreed amount is the number it is - Issue #435.
#:
#: Three facts, not three ways of reaching one number. Kept as constants
#: because the value is written by the service, read by the API and shown on a
#: screen, and a string spelled three times is a string that will be spelled
#: two ways.
AGREED_BASIS_NEGOTIATED = "negotiated"
AGREED_BASIS_PRICED_BOQ = "priced_boq"
AGREED_BASIS_HEADLINE = "headline_estimate"
AGREED_BASES: tuple[str, ...] = (
    AGREED_BASIS_NEGOTIATED,
    AGREED_BASIS_PRICED_BOQ,
    AGREED_BASIS_HEADLINE,
)


def _money(value: Any) -> Decimal:
    """Coerce a computed money figure to an exact Decimal rounded to cents.

    ``BOQService.compute_boq_totals`` reports floats, which is the historical
    shape of that API and not something to change from here. Routing through
    ``str`` keeps 0.1 from arriving as 0.10000000000000000555, and quantizing
    at the boundary means a comparison against a stored ``MoneyType`` figure
    is a comparison of two cent-rounded numbers rather than of a float and a
    decimal.
    """
    return _to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _money_str_map(by_currency: dict[str, Decimal]) -> dict[str, str]:
    """Render a ``{code: Decimal}`` money map as ``{code: decimal-string}``.

    Each amount is written in the units its own key names, which is the whole
    reason this map is keyed by currency in the first place.
    :func:`app.core.money.money_quantum` answers how fine that is, so a forint
    total comes back whole and a Kuwaiti dinar total keeps the fils it was
    agreed in. A blank or unregistered key takes the registry's own two-decimal
    default rather than a guess made here.

    The plain-decimal string wire format is the same one the scalar money
    fields use, so the per-currency breakdown stays exact and JS-safe.
    Blank-currency keys are normalised to ``""``.
    """
    out: dict[str, str] = {}
    for raw_code, amount in sorted(by_currency.items()):
        code = (raw_code or "").strip().upper()
        out[code] = format(_to_decimal(amount).quantize(money_quantum(code), rounding=ROUND_HALF_UP), "f")
    return out


async def _load_project_currency_meta(session: AsyncSession, project_id: uuid.UUID) -> Any:
    """Load the owning ``Project`` (currency + fx_rates) for FX conversion.

    Currency bug fix support: the dashboard money roll-ups must be
    labelled and FX-converted to the PROJECT currency, never a row
    currency. Imported lazily to avoid a hard import cycle and so the
    variations module stays decoupled from projects at import time.
    Returns ``None`` defensively if the project can't be loaded.
    """
    try:
        from sqlalchemy import select

        from app.modules.projects.models import Project

        result = await session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()
    except Exception:  # noqa: BLE001 -- dashboard must never 500 on FX metadata
        return None


async def _safe_by_currency(repo: Any, method_name: str, project_id: uuid.UUID) -> dict[str, Decimal]:
    """Call a repo's ``*_by_currency`` helper if present, else return ``{}``.

    Mirrors the ``hasattr(... "pending_count")`` guard already used in
    ``get_dashboard`` so in-memory test stubs (which don't implement the
    new per-currency aggregations) keep working without a hard failure.
    """
    method = getattr(repo, method_name, None)
    if method is None:
        return {}
    result = await method(project_id)
    return result if isinstance(result, dict) else {}


def compute_cost_impact_total(impacts: Iterable[Any]) -> Decimal:
    """Sum the ``total`` of every cost-impact line.

    Accepts ORM rows or any object exposing ``total``. Empty iterable
    returns ``Decimal('0')``.
    """
    total = Decimal("0")
    for line in impacts:
        if line is None:
            continue
        raw = getattr(line, "total", None)
        if raw is None and isinstance(line, dict):
            raw = line.get("total")
        if raw is None:
            qty = _to_decimal(getattr(line, "quantity", None))
            rate = _to_decimal(getattr(line, "unit_rate", None))
            raw = qty * rate
        total += _to_decimal(raw)
    return total


def compute_daywork_sheet_total(lines: Iterable[Any]) -> Decimal:
    """Sum the ``total`` of every daywork line.

    If ``total`` is missing, falls back to ``quantity * unit_rate``.
    """
    total = Decimal("0")
    for line in lines:
        if line is None:
            continue
        raw = getattr(line, "total", None)
        if raw is None and isinstance(line, dict):
            raw = line.get("total")
        if raw is None:
            qty = _to_decimal(getattr(line, "quantity", None))
            rate = _to_decimal(getattr(line, "unit_rate", None))
            raw = qty * rate
        total += _to_decimal(raw)
    return total


def is_within_response_window(notice: Any, today: dt_date | None = None) -> bool:
    """Pure: True if ``notice.target_response_date`` has not yet passed.

    If the target date is missing/unparseable, the window is treated as
    open. ``today=None`` uses ``date.today()``.
    """
    if today is None:
        today = dt_date.today()
    target = (
        getattr(notice, "target_response_date", None)
        if not isinstance(notice, dict)
        else notice.get("target_response_date")
    )
    if not target:
        return True
    try:
        target_date = dt_date.fromisoformat(str(target)[:10])
    except (ValueError, TypeError):
        return True
    return today <= target_date


def compute_critical_path_extension(schedule_impacts: Iterable[Any]) -> int:
    """Pure: max ``days_added`` across impacts where ``is_critical_path`` is True.

    Returns 0 if no critical-path impacts. Non-positive deltas count
    toward the max only if they are critical-path; negative deltas can
    represent schedule recovery and should not silently elevate.
    """
    best = 0
    seen = False
    for impact in schedule_impacts:
        if impact is None:
            continue
        is_cp = getattr(impact, "is_critical_path", None)
        if is_cp is None and isinstance(impact, dict):
            is_cp = impact.get("is_critical_path")
        if not is_cp:
            continue
        days = getattr(impact, "days_added", None)
        if days is None and isinstance(impact, dict):
            days = impact.get("days_added")
        try:
            days_int = int(days or 0)
        except (ValueError, TypeError):
            days_int = 0
        if not seen or days_int > best:
            best = days_int
            seen = True
    return best


def validate_variation_request(payload: Any) -> tuple[bool, list[str]]:
    """Pure: validate a VariationRequestCreate-like payload.

    Returns ``(ok, errors)``. Required fields vary by ``classification``:

    * ``regulatory`` -- must include a non-empty ``description``
      AND ``estimated_schedule_days`` must be non-negative.
    * ``unforeseen`` -- must include ``description``.
    * ``scope_change``, ``owner_change``, ``design_dev``, ``other`` --
      title or description must be present.

    All classifications require a project_id.
    """
    errors: list[str] = []

    def _get(name: str) -> Any:
        if isinstance(payload, dict):
            return payload.get(name)
        return getattr(payload, name, None)

    if _get("project_id") in (None, ""):
        errors.append("project_id is required")

    classification = _get("classification") or "scope_change"
    title = (_get("title") or "").strip() if isinstance(_get("title"), str) else (_get("title") or "")
    description = (
        (_get("description") or "").strip() if isinstance(_get("description"), str) else (_get("description") or "")
    )

    if classification == "regulatory":
        if not description:
            errors.append("description is required for regulatory variations")
        days = _get("estimated_schedule_days")
        try:
            if days is not None and int(days) < 0:
                errors.append("estimated_schedule_days cannot be negative for regulatory")
        except (ValueError, TypeError):
            errors.append("estimated_schedule_days must be an integer")
    elif classification == "unforeseen":
        if not description:
            errors.append("description is required for unforeseen variations")
    elif classification in {"scope_change", "owner_change", "design_dev", "other"}:
        if not title and not description:
            errors.append("title or description is required")
    else:
        errors.append(f"unknown classification: {classification}")

    cost = _get("estimated_cost_impact")
    if cost is not None:
        try:
            Decimal(str(cost))
        except (InvalidOperation, ValueError, TypeError):
            errors.append("estimated_cost_impact must be numeric")

    return (not errors, errors)


# ── Contract-clause defaults / NEC4 timers ────────────────────────────────


# Supported contract standards + their canonical sub-clause for "variation".
_VARIATION_CLAUSES: dict[str, str] = {
    "FIDIC_RED_2017": "Sub-Clause 13",
    "FIDIC_YELLOW_2017": "Sub-Clause 13",
    "FIDIC_SILVER_2017": "Sub-Clause 13",
    "JCT_SBC_2016": "Clause 5",
    "NEC4_ECC": "Clause 60-65",  # Compensation Events
    "PPC2000": "Part 5 - Pricing & Payment",
    # German public and private works. § 1 Abs. 3 is the client's right to
    # order a change; § 2 Abs. 5 is the price consequence and so the clause a
    # variation is argued under. Works never agreed at all fall under § 2
    # Abs. 6, which a row states in its own clause reference.
    "VOB_B": "§ 2 Abs. 5 VOB/B",
    "GENERIC": "-",
}


def supported_contract_standards() -> list[str]:
    """Return contract standards we know how to stamp."""
    return sorted(_VARIATION_CLAUSES.keys())


def default_clause_for_standard(standard: str) -> str:
    """Return the canonical variation sub-clause for a given standard."""
    return _VARIATION_CLAUSES.get(standard.upper(), "")


def compute_nec4_timers(
    notified_at: dt_date | str,
    *,
    quotation_weeks: int = 3,
    assessment_weeks: int = 4,
) -> dict[str, str]:
    """Return NEC4 quotation + assessment deadlines as ISO date strings.

    NEC4 ECC Clause 62.3 - Contractor's quotation due 3 weeks after
    instruction. Clause 62.5 - Project Manager's assessment due 4 weeks
    after quotation submission (combined SLA = 7 weeks).

    NEC states these windows in weeks and NEC weeks are calendar weeks, so the
    count runs through the shared day helper on its calendar basis and a week is
    exactly seven days. The basis is deliberately not a parameter: no caller can
    make NEC count in working days, and a knob for it would only invite someone
    to set it. A standard that *does* count in working days must not be added by
    copying this function - it belongs in the notice-period table in
    ``change_intelligence.time_bar``, which carries a basis per period and
    counts through the same helper.

    Args:
        notified_at: date or YYYY-MM-DD when the CE was notified.
        quotation_weeks: quotation due window (default 3 per Cl. 62.3).
        assessment_weeks: assessment due window (default 4 per Cl. 62.5).

    Returns:
        ``{"quotation_due_at": "YYYY-MM-DD", "assessment_due_at":
        "YYYY-MM-DD"}``.
    """
    if isinstance(notified_at, str):
        try:
            base = dt_date.fromisoformat(notified_at[:10])
        except (ValueError, TypeError):
            base = dt_date.today()
    elif isinstance(notified_at, dt_date):
        base = notified_at
    else:
        base = dt_date.today()
    # The assessment window runs from the quotation deadline, not from the
    # notification, so the two counts chain rather than both starting at ``base``.
    q_due = add_days(base, quotation_weeks * 7, CALENDAR)
    a_due = add_days(q_due, assessment_weeks * 7, CALENDAR)
    return {
        "quotation_due_at": q_due.isoformat(),
        "assessment_due_at": a_due.isoformat(),
    }


def is_nec4_overdue(
    request: Any,
    today: dt_date | None = None,
) -> dict[str, bool]:
    """Return overdue flags for the NEC4 quotation + assessment timers.

    ``request`` must expose ``quotation_due_at``, ``assessment_due_at``,
    ``submitted_at``, ``decision_at`` (any with None / unparseable date is
    treated as "not breached yet").
    """
    if today is None:
        today = dt_date.today()

    def _parse_date(v: Any) -> dt_date | None:
        if v is None:
            return None
        s = str(v)[:10]
        try:
            return dt_date.fromisoformat(s)
        except (ValueError, TypeError):
            return None

    q_due = _parse_date(getattr(request, "quotation_due_at", None))
    a_due = _parse_date(getattr(request, "assessment_due_at", None))
    submitted = _parse_date(getattr(request, "submitted_at", None))
    decided = _parse_date(getattr(request, "decision_at", None))

    quotation_overdue = bool(q_due and today > q_due and submitted is None)
    assessment_overdue = bool(a_due and today > a_due and decided is None)
    return {
        "quotation_overdue": quotation_overdue,
        "assessment_overdue": assessment_overdue,
    }


# ── BS 6079 daywork markup ────────────────────────────────────────────────


def apply_daywork_markup(
    subtotal: Decimal | float | int | str,
    markup_percent: Decimal | float | int | str | None,
) -> Decimal:
    """Return ``subtotal × (1 + markup/100)`` quantized to 2 dp.

    BS 6079-1:2019 §6.4.2 - markup covers overheads + profit on daywork
    rates. Pure: no I/O.
    """
    sub = _to_decimal(subtotal)
    mk = _to_decimal(markup_percent)
    if mk == 0:
        return sub.quantize(Decimal("0.01"))
    return (sub * (Decimal("1") + mk / Decimal("100"))).quantize(Decimal("0.01"))


# ── AICPA measured-mile disruption ────────────────────────────────────────


def compute_disruption_lost_hours(
    baseline_productivity: Decimal | float | int | str | None,
    impacted_productivity: Decimal | float | int | str | None,
    measured_quantity: Decimal | float | int | str | None,
) -> Decimal:
    """Return labour hours lost via the measured-mile method.

    Formula::

        lost_hours = measured_quantity *
                     (1 / impacted_productivity - 1 / baseline_productivity)

    The intuition: the team produces 1 unit in (1/productivity) hours; the
    difference between impacted and baseline productivity, multiplied by
    quantity produced under the impacted regime, is the lost labour.

    Returns ``Decimal("0")`` for inputs that don't form a valid
    measured-mile comparison (zero productivities or impacted ≥
    baseline).
    """
    baseline = _to_decimal(baseline_productivity)
    impacted = _to_decimal(impacted_productivity)
    qty = _to_decimal(measured_quantity)
    if baseline <= 0 or impacted <= 0 or qty <= 0:
        return Decimal("0")
    if impacted >= baseline:
        return Decimal("0")
    hours_per_unit_impacted = Decimal("1") / impacted
    hours_per_unit_baseline = Decimal("1") / baseline
    return (qty * (hours_per_unit_impacted - hours_per_unit_baseline)).quantize(Decimal("0.01"))


# ── FIDIC 20.1 time-bar (Red/Yellow/Silver 2017) ──────────────────────────


def check_fidic_time_bar(
    event_occurred_at: dt_date | str,
    notice_issued_at: dt_date | str | None,
    *,
    notice_window_days: int = 28,
) -> dict[str, Any]:
    """Check whether a contractor's notice was issued within the time-bar.

    FIDIC 2017 Sub-Clause 20.2.1 - the Contractor shall give Notice within
    28 days after they became aware (or should have become aware) of the
    event giving rise to a claim. Failure to issue notice in time bars
    the claim ("time-bar effect"), subject to Sub-Clause 20.2.4 exceptions.

    Args:
        event_occurred_at: date / ISO string when the event arose.
        notice_issued_at: date / ISO string when notice was sent (None =
            not yet sent → still computes days remaining).
        notice_window_days: bar window in days (default 28 per Cl. 20.2.1).

    Returns:
        ``{"days_elapsed": int, "deadline_at": str, "within_time_bar": bool,
        "days_remaining": int | None}``. ``days_remaining`` is None when
        the notice has been issued (no longer relevant).

    Pure: no I/O.
    """
    from datetime import timedelta as _td

    def _coerce(v: Any) -> dt_date | None:
        if v is None:
            return None
        if isinstance(v, dt_date):
            return v
        try:
            return dt_date.fromisoformat(str(v)[:10])
        except (ValueError, TypeError):
            return None

    event_d = _coerce(event_occurred_at)
    notice_d = _coerce(notice_issued_at)
    if event_d is None:
        return {
            "days_elapsed": 0,
            "deadline_at": "",
            "within_time_bar": True,
            "days_remaining": notice_window_days,
        }
    deadline = event_d + _td(days=notice_window_days)
    if notice_d is not None:
        elapsed = (notice_d - event_d).days
        within = notice_d <= deadline
        return {
            "days_elapsed": elapsed,
            "deadline_at": deadline.isoformat(),
            "within_time_bar": within,
            "days_remaining": None,
        }
    today = dt_date.today()
    elapsed = (today - event_d).days
    remaining = (deadline - today).days
    return {
        "days_elapsed": elapsed,
        "deadline_at": deadline.isoformat(),
        "within_time_bar": today <= deadline,
        "days_remaining": remaining,
    }


# ── Schedule-of-rates re-rating (±15% quantity variance trigger) ──────────


def recommend_rerate(
    boq_quantity: Decimal | float | int | str,
    actual_quantity: Decimal | float | int | str,
    *,
    threshold_pct: Decimal | float | int | str = Decimal("15"),
) -> dict[str, Any]:
    """Decide whether the re-rating of a BoQ item is justified.

    The 15% rule of thumb comes from JCT SBC Cl 5.6.1.3 and NEC4 Cl 60.4 /
    60.6 - when the actual quantity differs from the BoQ quantity by more
    than ±threshold_pct, the rate may be re-negotiated to reflect a
    different unit-cost.

    Args:
        boq_quantity: tendered / contracted quantity.
        actual_quantity: measured / executed quantity.
        threshold_pct: percentage trigger (default 15 per JCT 5.6.1.3).

    Returns:
        ``{"variance_pct": Decimal, "rerate_required": bool,
        "direction": "increase" | "decrease" | "none", "reason": str}``.

    Pure: no I/O.
    """
    bq = _to_decimal(boq_quantity)
    aq = _to_decimal(actual_quantity)
    thr = _to_decimal(threshold_pct)
    if bq == 0:
        # Division by zero - treat as 100% variance if actual > 0.
        if aq > 0:
            return {
                "variance_pct": Decimal("100.00"),
                "rerate_required": True,
                "direction": "increase",
                "reason": "BoQ quantity was zero - rate must be agreed",
            }
        return {
            "variance_pct": Decimal("0.00"),
            "rerate_required": False,
            "direction": "none",
            "reason": "Both quantities are zero",
        }
    variance = ((aq - bq) / bq) * Decimal("100")
    abs_var = abs(variance)
    rerate = abs_var > thr
    if not rerate:
        direction = "none"
    elif variance > 0:
        direction = "increase"
    else:
        direction = "decrease"
    reason = (
        f"Quantity variance {variance.quantize(Decimal('0.01'))}% exceeds ±{thr}% threshold - re-rating recommended"
        if rerate
        else f"Quantity variance {variance.quantize(Decimal('0.01'))}% within ±{thr}% threshold - contract rate stands"
    )
    return {
        "variance_pct": variance.quantize(Decimal("0.01")),
        "rerate_required": rerate,
        "direction": direction,
        "reason": reason,
    }


# --- International variation value roll-ups (pure, additive) -----------------
#
# These helpers turn a set of variations (any mix of requests, orders,
# claims) into plain, currency-safe figures for the revised contract sum.
# They are deliberately currency-agnostic: no ISO code, tax rate, unit or
# locale is hardcoded. Money stays Decimal-exact and is never summed across
# different currency codes. Every division is guarded, and empty inputs
# yield well-defined zeros rather than a 500 or a NaN.


# Value buckets group lifecycle status codes by their commercial meaning.
# "agreed" money has been accepted and moves the contract sum. "pending"
# money is proposed but not yet accepted, so it is still at risk. "rejected"
# money has been declined or voided and must never move the contract sum.
AGREED_VALUE_STATUSES: frozenset[str] = frozenset(
    {
        "approved",
        "converted_to_vo",
        "issued",
        "in_progress",
        "completed",
        "agreed",
        "granted",
        "signed",
        "billed",
    }
)
PENDING_VALUE_STATUSES: frozenset[str] = frozenset(
    {
        "draft",
        "submitted",
        "under_review",
        "acknowledged",
        "responded",
        "disputed",
        "pending",
    }
)
REJECTED_VALUE_STATUSES: frozenset[str] = frozenset({"rejected", "voided"})


def variation_value_bucket(status: str | None) -> str:
    """Classify a lifecycle status into a value bucket.

    Returns one of ``"agreed"``, ``"pending"``, ``"rejected"`` or
    ``"other"``. Case-insensitive. An unknown or blank status falls back to
    ``"other"`` so an unexpected code is never silently counted as agreed
    money that moves the contract sum.
    """
    code = (status or "").strip().lower()
    if code in AGREED_VALUE_STATUSES:
        return "agreed"
    if code in PENDING_VALUE_STATUSES:
        return "pending"
    if code in REJECTED_VALUE_STATUSES:
        return "rejected"
    return "other"


_STATUS_PLAIN_LABELS: dict[str, str] = {
    "draft": "Draft, not yet submitted",
    "submitted": "Submitted, awaiting review",
    "under_review": "Under review",
    "acknowledged": "Acknowledged by the other party",
    "responded": "Responded to",
    "approved": "Approved",
    "agreed": "Agreed",
    "granted": "Granted",
    "signed": "Signed",
    "billed": "Billed",
    "issued": "Issued",
    "in_progress": "In progress",
    "completed": "Completed",
    "converted_to_vo": "Converted to a variation order",
    "rejected": "Rejected",
    "voided": "Voided, carries no value",
    "disputed": "Disputed",
    "closed": "Closed",
}


def plain_status_label(status: str | None) -> str:
    """Return a short plain-language label for a status code.

    Falls back to the raw code with underscores replaced by spaces so an
    unmapped status still reads cleanly. A blank status returns
    ``"Unknown"``.
    """
    code = (status or "").strip().lower()
    if not code:
        return "Unknown"
    return _STATUS_PLAIN_LABELS.get(code, code.replace("_", " ").capitalize())


_CONCEPT_EXPLANATIONS: dict[str, str] = {
    "agreed_value": ("Agreed value is the total of variations both parties have accepted; it moves the contract sum."),
    "pending_value": (
        "Pending value is proposed but not yet accepted, so it is still at risk and does not move the contract sum yet."
    ),
    "rejected_value": ("Rejected value has been declined or voided and never moves the contract sum."),
    "time_impact": (
        "Time impact is the number of days a variation adds to the completion date, measured along the critical path."
    ),
    "contract_sum_movement": (
        "Contract sum movement is the net change to the original contract sum from all agreed variations."
    ),
    "revised_contract_sum": (
        "Revised contract sum is the original contract sum plus the net movement from agreed variations."
    ),
    "percent_of_contract": ("Percent of contract shows a value as a share of the original contract sum."),
    "final_account": (
        "The final account is the settled total of the original contract sum plus every agreed "
        "variation, daywork and claim, less retention held."
    ),
}


def explain_variation_concept(concept: str) -> str:
    """Return a one-line plain-language explanation of a variation concept.

    Recognised concepts: ``agreed_value``, ``pending_value``,
    ``rejected_value``, ``time_impact``, ``contract_sum_movement``,
    ``revised_contract_sum``, ``percent_of_contract`` and
    ``final_account``. An unknown concept returns an empty string so the
    caller can decide whether to show a fallback.
    """
    return _CONCEPT_EXPLANATIONS.get((concept or "").strip().lower(), "")


# Amount fields we understand, tried in priority order. This lets one set of
# roll-up helpers work over variation orders, requests and claims without
# reshaping the rows first.
_AMOUNT_FIELDS: tuple[str, ...] = (
    "amount",
    "final_cost_impact",
    "approved_cost_impact",
    "decided_amount",
    "estimated_cost_impact",
    "total",
)


def _item_field(item: Any, name: str) -> Any:
    """Read ``name`` from an ORM row or a dict, returning ``None`` if absent."""
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _item_amount(item: Any) -> Decimal:
    """Return the money amount of an item as an exact Decimal (0 if none)."""
    for field_name in _AMOUNT_FIELDS:
        raw = _item_field(item, field_name)
        if raw is not None:
            return _to_decimal(raw)
    return Decimal("0")


def _item_status(item: Any) -> str:
    """Return the lowercased status code of an item (blank if none)."""
    return str(_item_field(item, "status") or "").strip().lower()


def _item_currency(item: Any) -> str:
    """Return the uppercased currency code of an item (blank if none)."""
    return str(_item_field(item, "currency") or "").strip().upper()


def assert_single_currency(items: Iterable[Any]) -> str:
    """Return the one shared currency across items, or raise ``ValueError``.

    Blank currency codes mean "inherit" and are ignored. Money must never be
    summed across different ISO currency codes, so two or more distinct
    non-blank codes is a clean input error, never a silently wrong total.
    Returns ``""`` when every item has a blank currency.
    """
    codes = {code for i in items if (code := _item_currency(i))}
    if len(codes) > 1:
        raise ValueError(
            "Cannot roll up money across mixed currencies: "
            + ", ".join(sorted(codes))
            + ". Normalise to one currency first."
        )
    return next(iter(codes), "")


def rollup_by_value_status(items: Iterable[Any]) -> dict[str, Any]:
    """Group variation money into agreed / pending / rejected / other buckets.

    Each item may be an ORM row or a dict carrying a ``status`` and an
    amount (first present of ``amount``, ``final_cost_impact``,
    ``approved_cost_impact``, ``decided_amount``, ``estimated_cost_impact``,
    ``total``). All non-blank currencies must match or a ``ValueError`` is
    raised; money is never blended across currencies.

    Returns a dict with per-bucket Decimal ``totals``, per-bucket ``counts``,
    the shared ``currency`` and the overall ``count``. Empty input yields
    all-zero totals, never a division or a 500.
    """
    rows = [i for i in items if i is not None]
    currency = assert_single_currency(rows)
    totals: dict[str, Decimal] = {
        "agreed": Decimal("0"),
        "pending": Decimal("0"),
        "rejected": Decimal("0"),
        "other": Decimal("0"),
    }
    counts: dict[str, int] = {"agreed": 0, "pending": 0, "rejected": 0, "other": 0}
    for row in rows:
        bucket = variation_value_bucket(_item_status(row))
        totals[bucket] += _item_amount(row)
        counts[bucket] += 1
    return {
        "currency": currency,
        "count": len(rows),
        "totals": totals,
        "counts": counts,
    }


def cumulative_contract_sum_movement(items: Iterable[Any]) -> Decimal:
    """Net movement of the contract sum from AGREED variations only.

    Sums the amounts of agreed-bucket items so positive additions and
    negative omissions (credits) net out. Pending and rejected money is
    excluded because it has not moved the contract sum. Raises
    ``ValueError`` on a genuine currency mix. Empty input returns
    ``Decimal("0")``.
    """
    rows = [i for i in items if i is not None]
    assert_single_currency(rows)
    total = Decimal("0")
    for row in rows:
        if variation_value_bucket(_item_status(row)) == "agreed":
            total += _item_amount(row)
    return total


def percent_of_contract(
    amount: Decimal | float | int | str | None,
    contract_sum: Decimal | float | int | str | None,
    *,
    quantize_to: str = "0.01",
) -> Decimal:
    """Express ``amount`` as a percentage of ``contract_sum``.

    Guards division by zero: a zero or missing contract sum raises
    ``ValueError`` rather than returning NaN or infinity. The result is a
    Decimal quantized to two decimals by default.
    """
    base = _to_decimal(contract_sum)
    if base == 0:
        raise ValueError("Contract sum is zero; percent of contract is undefined.")
    pct = (_to_decimal(amount) / base) * Decimal("100")
    return pct.quantize(Decimal(quantize_to), rounding=ROUND_HALF_UP)


def _summarise_contract_sum_movement(
    original: Decimal,
    net_movement: Decimal,
    revised: Decimal,
    currency: str,
    percent_movement: Decimal | None,
) -> str:
    """One-line plain-language summary of how the contract sum moved."""
    unit = f" {currency}" if currency else ""
    pct = "" if percent_movement is None else f" ({percent_movement}%)"
    if net_movement > 0:
        movement_phrase = f"rises by {net_movement}{unit}{pct}"
    elif net_movement < 0:
        movement_phrase = f"falls by {abs(net_movement)}{unit}{pct}"
    else:
        movement_phrase = "does not change"
    return f"Agreed variations mean the contract sum {movement_phrase}, from {original}{unit} to {revised}{unit}."


def build_contract_sum_rollup(
    original_contract_value: Decimal | float | int | str | None,
    items: Iterable[Any],
    *,
    currency: str | None = None,
) -> dict[str, Any]:
    """Build an explainable revised-contract-sum roll-up from variations.

    Components (all exact Decimals, all in one currency):

    * ``original`` - the starting contract sum.
    * ``agreed_additions`` - agreed variations that increase the sum (>= 0).
    * ``agreed_omissions`` - agreed credits that decrease the sum (< 0).
    * ``net_movement`` - additions plus omissions (the contract sum movement).
    * ``pending`` - proposed value not yet agreed (at risk, excluded).
    * ``rejected`` - declined or voided value (excluded).
    * ``revised_contract_sum`` - original plus net_movement.
    * ``percent_movement`` - net_movement as a percent of the original, or
      ``None`` when the original is zero so there is no division by zero.
    * ``summary`` - a one-line plain-language explanation.

    Pass ``currency`` to assert the expected unit; if given it must match the
    items' own currency. Raises ``ValueError`` on a currency mix. Empty input
    just echoes the original with a zero movement.
    """
    rows = [i for i in items if i is not None]
    detected = assert_single_currency(rows)
    expected = (currency or "").strip().upper()
    if expected and detected and expected != detected:
        raise ValueError(f"Items are denominated in {detected} but {expected} was expected.")
    resolved_currency = expected or detected

    original = _to_decimal(original_contract_value)
    agreed_additions = Decimal("0")
    agreed_omissions = Decimal("0")
    pending = Decimal("0")
    rejected = Decimal("0")
    for row in rows:
        bucket = variation_value_bucket(_item_status(row))
        amount = _item_amount(row)
        if bucket == "agreed":
            if amount >= 0:
                agreed_additions += amount
            else:
                agreed_omissions += amount
        elif bucket == "pending":
            pending += amount
        elif bucket == "rejected":
            rejected += amount
        # "other" contributes nothing to the contract sum.

    net_movement = agreed_additions + agreed_omissions
    revised = original + net_movement
    if original == 0:
        percent_movement: Decimal | None = None
    else:
        percent_movement = (net_movement / original * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "currency": resolved_currency,
        "original": original,
        "agreed_additions": agreed_additions,
        "agreed_omissions": agreed_omissions,
        "net_movement": net_movement,
        "pending": pending,
        "rejected": rejected,
        "revised_contract_sum": revised,
        "percent_movement": percent_movement,
        "summary": _summarise_contract_sum_movement(
            original, net_movement, revised, resolved_currency, percent_movement
        ),
    }


# ── Async event helper ─────────────────────────────────────────────────────


def _safe_publish(name: str, data: dict[str, Any], source_module: str = "variations") -> None:
    """Fire-and-forget event publish."""
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        logger.debug("Event publish skipped: %s", name)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _log_ownership_change(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    from_party: str | None,
    to_party: str | None,
    actor_id: str | None,
    code: str | None = None,
) -> None:
    """Record a ball-in-court hand-off for a variation record (best-effort).

    Feeds the change-intelligence ownership-chain reconstruction so the custody
    history of a notice / request / order survives the single mutable
    ``ball_in_court`` column. The shared helper already wraps the write in
    try/except, so an audit failure never rolls back the field update.
    """
    from app.core.audit_log import log_ownership_handoff

    await log_ownership_handoff(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        from_party=from_party,
        to_party=to_party,
        actor_id=actor_id,
        metadata={"code": code} if code else None,
    )


def is_high_value(amount: Decimal | float | int | str | None) -> bool:
    """R5 audit: True when ``amount`` exceeds the high-value approval bar.

    Pure. Used to decide whether ``variations.approve_high_value`` is
    additionally required on top of ``variations.approve_request``.
    """
    return abs(_to_decimal(amount)) > HIGH_VALUE_APPROVAL_THRESHOLD


def ensure_high_value_authorised(
    amount: Decimal | float | int | str | None,
    *,
    payload: dict[str, Any] | None,
) -> None:
    """R5 audit: raise 403 if ``amount`` exceeds threshold and caller lacks
    ``variations.approve_high_value``.

    ``payload`` is the JWT payload from ``get_current_user_payload``.
    Admins always pass. A None payload only appears in test paths where
    the dependency is bypassed - treat that as "skip" so unit-level tests
    stay self-contained.
    """
    if not is_high_value(amount):
        return
    if payload is None:
        return
    role = str(payload.get("role", "") or "").lower()
    if role == "admin":
        return
    from app.core.permissions import permission_registry as _reg

    perms = payload.get("permissions", []) or []
    if "variations.approve_high_value" in perms:
        return
    if _reg.role_has_permission(role, "variations.approve_high_value"):
        return
    raise HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail=(
            "Variation amount exceeds the high-value approval threshold; "
            "the 'variations.approve_high_value' permission is required."
        ),
    )


def _log_decision(
    event: str,
    *,
    user_id: str | None,
    project_id: uuid.UUID | str | None,
    target_id: uuid.UUID | str | None,
    amount: Decimal | str | None = None,
    currency: str | None = None,
    **extra: Any,
) -> None:
    """R5 audit: emit a structured log record for an approve/reject/decision.

    Sits alongside ``_safe_publish`` (which fans the event out to other
    modules) - the log line goes to operator stdout / Splunk / Datadog so
    the audit trail survives a missing subscriber. Money columns are
    serialised via ``str(Decimal)`` to avoid binary-float drift in
    JSON-encoded log shippers.
    """
    record: dict[str, Any] = {
        "event": event,
        "user_id": user_id,
        "project_id": str(project_id) if project_id else None,
        "target_id": str(target_id) if target_id else None,
    }
    if amount is not None:
        record["amount"] = str(amount)
    if currency is not None:
        record["currency"] = currency
    if extra:
        record.update(extra)
    logger.info(event, extra=record)


# ── Service ────────────────────────────────────────────────────────────────


class VariationsService:
    """Business logic for the variations lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.notice_repo = NoticeRepository(session)
        self.vr_repo = VariationRequestRepository(session)
        self.vo_repo = VariationOrderRepository(session)
        self.cost_impact_repo = VariationCostImpactRepository(session)
        self.schedule_impact_repo = VariationScheduleImpactRepository(session)
        self.site_measurement_repo = SiteMeasurementRepository(session)
        self.daywork_repo = DayworkSheetRepository(session)
        self.daywork_line_repo = DayworkSheetLineRepository(session)
        self.disruption_repo = DisruptionClaimRepository(session)
        self.eot_repo = ExtensionOfTimeClaimRepository(session)
        self.final_account_repo = FinalAccountRepository(session)
        self.boq_trace_repo = VariationBOQTraceRepository(session)

    # ── Notice ────────────────────────────────────────────────────────────

    async def create_notice(self, data: NoticeCreate, user_id: str | None = None) -> Notice:
        code = await self.notice_repo.next_code(data.project_id)
        notice = Notice(
            project_id=data.project_id,
            code=code,
            title=data.title,
            description=data.description,
            raised_at=data.raised_at or _now_iso(),
            raised_by=data.raised_by or user_id,
            recipient_type=data.recipient_type,
            recipient_name=data.recipient_name,
            target_response_date=data.target_response_date,
            response_summary=data.response_summary,
            status=data.status,
            reference_change_order_id=data.reference_change_order_id,
            metadata_=data.metadata,
        )
        notice = await self.notice_repo.create(notice)
        _safe_publish(
            "variations.notice.issued",
            {
                "project_id": str(data.project_id),
                "notice_id": str(notice.id),
                "code": code,
                "recipient_type": data.recipient_type,
            },
        )
        return notice

    async def get_notice(self, notice_id: uuid.UUID) -> Notice:
        row = await self.notice_repo.get_by_id(notice_id)
        if row is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Notice not found")
        return row

    async def update_notice(self, notice_id: uuid.UUID, data: NoticeUpdate, user_id: str | None = None) -> Notice:
        notice = await self.get_notice(notice_id)
        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if not fields:
            return notice
        ball_changed = "ball_in_court" in fields and fields["ball_in_court"] != notice.ball_in_court
        old_ball = notice.ball_in_court
        code_snapshot = notice.code
        await self.notice_repo.update_fields(notice_id, **fields)
        await self.session.refresh(notice)
        if ball_changed:
            await _log_ownership_change(
                self.session,
                entity_type="variation_notice",
                entity_id=notice_id,
                from_party=old_ball,
                to_party=fields["ball_in_court"],
                actor_id=user_id,
                code=code_snapshot,
            )
        return notice

    async def transition_notice(
        self,
        notice_id: uuid.UUID,
        to_status: str,
        user_id: str | None = None,
        response_summary: str | None = None,
    ) -> Notice:
        notice = await self.get_notice(notice_id)
        if to_status not in allowed_notice_transitions(notice.status):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Cannot transition notice from {notice.status} to {to_status}",
            )
        fields: dict[str, Any] = {"status": to_status}
        if to_status == "responded":
            fields["response_received_at"] = _now_iso()
            if response_summary:
                fields["response_summary"] = response_summary
        await self.notice_repo.update_fields(notice_id, **fields)
        await self.session.refresh(notice)
        _safe_publish(
            f"variations.notice.{to_status}",
            {"project_id": str(notice.project_id), "notice_id": str(notice_id)},
        )
        return notice

    # ── VariationRequest ──────────────────────────────────────────────────

    async def create_request(
        self,
        data: VariationRequestCreate,
        user_id: str | None = None,
    ) -> VariationRequest:
        ok, errs = validate_variation_request(data)
        if not ok:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"errors": errs},
            )
        code = await self.vr_repo.next_code(data.project_id)
        standard = (getattr(data, "contract_standard", "") or "").upper()
        clause_ref = getattr(data, "contract_clause_ref", "") or (
            default_clause_for_standard(standard) if standard else ""
        )
        # If a NEC4 contract is selected, auto-compute the SLA timers
        # off the request date (Clause 62.3 - 3 weeks for quotation,
        # Clause 62.5 - 4 weeks for assessment).
        quotation_due = getattr(data, "quotation_due_at", None)
        assessment_due = getattr(data, "assessment_due_at", None)
        if standard.startswith("NEC4") and (quotation_due is None or assessment_due is None):
            timers = compute_nec4_timers(data.requested_at or _now_iso())
            quotation_due = quotation_due or timers["quotation_due_at"]
            assessment_due = assessment_due or timers["assessment_due_at"]
        vr = VariationRequest(
            project_id=data.project_id,
            notice_id=data.notice_id,
            code=code,
            title=data.title,
            description=data.description,
            requested_by=data.requested_by or user_id,
            requested_at=data.requested_at or _now_iso(),
            classification=data.classification,
            urgency=data.urgency,
            estimated_cost_impact=_to_decimal(data.estimated_cost_impact),
            estimated_schedule_days=data.estimated_schedule_days,
            currency=data.currency,
            status=data.status,
            contract_standard=standard,
            contract_clause_ref=clause_ref,
            quotation_due_at=quotation_due,
            assessment_due_at=assessment_due,
            metadata_=data.metadata,
        )
        vr = await self.vr_repo.create(vr)
        _safe_publish(
            "variations.request.created",
            {
                "project_id": str(data.project_id),
                "request_id": str(vr.id),
                "code": code,
                "classification": data.classification,
            },
        )
        return vr

    async def get_request(self, vr_id: uuid.UUID) -> VariationRequest:
        row = await self.vr_repo.get_by_id(vr_id)
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Variation request not found",
            )
        return row

    async def update_request(
        self,
        vr_id: uuid.UUID,
        data: VariationRequestUpdate,
        user_id: str | None = None,
    ) -> VariationRequest:
        vr = await self.get_request(vr_id)
        # A decided / converted VR is a frozen commercial record - editing
        # its scope or cost after approval/rejection destroys the audit
        # trail (and silently moves money once it is a VO). Lifecycle
        # changes go through ``transition_variation_request``, not here.
        if vr.status in {"approved", "rejected", "converted_to_vo"}:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=(f"Variation request is {vr.status} and can no longer be edited; create a new request instead"),
            )
        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if not fields:
            return vr
        if "estimated_cost_impact" in fields and fields["estimated_cost_impact"] is not None:
            fields["estimated_cost_impact"] = _to_decimal(fields["estimated_cost_impact"])
        ball_changed = "ball_in_court" in fields and fields["ball_in_court"] != vr.ball_in_court
        old_ball = vr.ball_in_court
        code_snapshot = vr.code
        await self.vr_repo.update_fields(vr_id, **fields)
        await self.session.refresh(vr)
        if ball_changed:
            await _log_ownership_change(
                self.session,
                entity_type="variation_request",
                entity_id=vr_id,
                from_party=old_ball,
                to_party=fields["ball_in_court"],
                actor_id=user_id,
                code=code_snapshot,
            )
        return vr

    @staticmethod
    def _actor_uuid(user_id: str | None) -> uuid.UUID | None:
        """The actor as the UUID a ``created_by`` column takes, or None.

        Actors reach this service as strings, and not every string is an id:
        a script or a test may name itself. A name is recorded as nobody
        rather than refused, because who pressed submit is already in the
        activity log and the snapshot must not fail to be written over it.
        """
        try:
            return uuid.UUID(str(user_id)) if user_id else None
        except ValueError:
            return None

    async def _freeze_submitted_pricing_state(
        self,
        vr: VariationRequest,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Which bill, at what total, and made of which lines, was put in front of the approver.

        Read once, at submission, and never recomputed. The bill can go on
        being revised after it is submitted - that is the normal way a
        variation gets negotiated - so a total read later answers a
        different question from the one the record has to answer.

        The total is the right thing to agree against and the wrong thing to
        defend a price with: once the bill has moved, nothing says which
        lines, at which quantities and rates, the frozen figure was made of.
        So submission also writes a point-in-time copy of the bill into its
        own version history (``BOQService.create_snapshot``, the same copy
        the editor's history panel lists) and records which one. The copy
        is named after the request so a reader of that history can tell it
        from a snapshot somebody took by hand.

        A request with no bill of its own is priced by its headline figure
        alone, which is a legitimate way to run a small variation, and all
        three columns stay NULL to say so.

        A request whose revision chain has forked is refused rather than
        recorded as NULL. It HAS a bill and we cannot say which one, so
        letting it through would file "no pricing state" against a request
        that has two, and that is the one answer that is worse than an
        error message.
        """
        boq, reason = await self.resolve_request_boq(vr.id)
        if boq is None:
            if reason == "no_active_boq":
                return {
                    "submitted_boq_id": None,
                    "submitted_boq_total": None,
                    "submitted_boq_snapshot_id": None,
                }
            raise self._request_boq_refusal(reason)

        from app.modules.boq.service import BOQService

        boq_service = BOQService(self.session)
        breakdown = (await boq_service.compute_boq_totals([boq.id])).get(boq.id, {})
        snapshot = await boq_service.create_snapshot(
            boq.id,
            name=f"{vr.code}: as submitted for approval"[:255],
            user_id=self._actor_uuid(user_id),
        )
        return {
            "submitted_boq_id": boq.id,
            "submitted_boq_total": _money(breakdown.get("grand_total")),
            "submitted_boq_snapshot_id": snapshot.id,
        }

    def _record_agreed_value(
        self,
        vr: VariationRequest,
        *,
        named_amount: Decimal | None,
        variance_note: str | None,
    ) -> dict[str, Any]:
        """What was agreed, and on what basis, at the moment of approval.

        Three bases, and they are three different facts rather than three
        ways of arriving at one number:

        * ``negotiated`` - a person named the amount. This is the only one
          that can legitimately depart from the pricing state, and when it
          does it has to say why.
        * ``priced_boq`` - nobody named one and the submitted bill had a
          total, so the agreement is that total. Recorded explicitly rather
          than left to be recomputed later, because the bill will move.
        * ``headline_estimate`` - nobody named one and there was no bill.
          The headline is the only figure there has ever been, and saying
          so is the point: it is the case the reporter wanted to stop being
          silently indistinguishable from a priced agreement.

        Raises:
            HTTPException: 422 when a named amount departs from the
                submitted total with nothing said about why.
        """
        baseline = vr.submitted_boq_total
        note = (variance_note or "").strip()
        if named_amount is not None:
            agreed = _to_decimal(named_amount)
            if baseline is not None and abs(agreed - _to_decimal(baseline)) >= _MONEY_EPSILON and not note:
                raise HTTPException(
                    status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "The amount being approved differs from the pricing state that was "
                        "submitted, so the approval needs a reason. Send agreed_variance_note "
                        "saying what was negotiated."
                    ),
                )
            return {
                "agreed_cost_impact": agreed,
                "agreed_basis": AGREED_BASIS_NEGOTIATED,
                "agreed_variance_note": note,
            }
        if baseline is not None:
            return {
                "agreed_cost_impact": _to_decimal(baseline),
                "agreed_basis": AGREED_BASIS_PRICED_BOQ,
                "agreed_variance_note": note,
            }
        return {
            "agreed_cost_impact": _to_decimal(vr.estimated_cost_impact),
            "agreed_basis": AGREED_BASIS_HEADLINE,
            "agreed_variance_note": note,
        }

    async def transition_variation_request(
        self,
        vr_id: uuid.UUID,
        to_status: str,
        user_id: str | None = None,
        decision_notes: str | None = None,
        agreed_cost_impact: Decimal | None = None,
        agreed_variance_note: str | None = None,
    ) -> VariationRequest:
        """Move a VariationRequest along its state machine. Emits events.

        Two of the transitions now write the commercial approval boundary
        (Issue #435) as well as the status.

        Submitting freezes which pricing state was put in front of the
        approver, and keeps a copy of the bill as it stood, so the frozen
        total has lines behind it after the bill has been revised. Approving
        records what was actually agreed and why it is
        that number, which is the half that was missing: without it the
        agreed value is whatever figure happened to be on the request, and a
        negotiated amount cannot be told from a stale headline.

        ``agreed_cost_impact`` is what a person named. Naming one that
        differs from the pricing state it was agreed against requires
        ``agreed_variance_note``, because an unexplained difference is
        exactly the thing this boundary exists to stop being invisible.
        """
        vr = await self.get_request(vr_id)
        if to_status not in allowed_vr_transitions(vr.status):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Cannot transition VR from {vr.status} to {to_status}",
            )
        # Snapshot immutable fields before update_fields() may expire ORM state.
        from_status_snapshot = vr.status
        code_snapshot = vr.code
        fields: dict[str, Any] = {"status": to_status}
        if to_status == "submitted":
            fields["submitted_at"] = _now_iso()
            fields.update(await self._freeze_submitted_pricing_state(vr, user_id=user_id))
        if to_status in {"approved", "rejected"}:
            fields["decision_at"] = _now_iso()
            fields["decided_by"] = user_id
            if decision_notes is not None:
                fields["decision_notes"] = decision_notes
        if to_status == "approved":
            fields.update(
                self._record_agreed_value(
                    vr,
                    named_amount=agreed_cost_impact,
                    variance_note=agreed_variance_note,
                )
            )
        await self.vr_repo.update_fields(vr_id, **fields)
        await self.session.refresh(vr)
        event_name = {
            "submitted": "variations.request.submitted",
            "under_review": "variations.request.under_review",
            "approved": "variations.request.approved",
            "rejected": "variations.request.rejected",
            "converted_to_vo": "variations.request.converted",
        }.get(to_status, f"variations.request.{to_status}")
        _safe_publish(
            event_name,
            {
                "project_id": str(vr.project_id),
                "request_id": str(vr_id),
                "code": vr.code,
                "to_status": to_status,
            },
        )
        # R5 audit: structured log on decision-grade transitions so the
        # audit trail survives a missing event subscriber.
        if to_status in {"approved", "rejected"}:
            _log_decision(
                f"variations.request.{to_status}",
                user_id=user_id,
                project_id=vr.project_id,
                target_id=vr_id,
                amount=_to_decimal(vr.estimated_cost_impact),
                currency=vr.currency or None,
                code=vr.code,
                decision_notes=decision_notes,
            )
        # R7 audit trail: persist every status change to ActivityLog in the
        # same transaction so the trail is atomic with the status write.
        try:
            from app.core.audit_log import log_activity as _log_act

            await _log_act(
                self.session,
                actor_id=user_id,
                entity_type="variation_request",
                entity_id=str(vr_id),
                action="status_changed",
                from_status=from_status_snapshot,
                to_status=to_status,
                reason=decision_notes,
                metadata={"code": code_snapshot},
            )
        except Exception:
            logger.warning(
                "ActivityLog write skipped for variation_request %s (%s)",
                vr_id,
                to_status,
                exc_info=True,
            )
        return vr

    async def delete_request(self, vr_id: uuid.UUID) -> None:
        await self.get_request(vr_id)
        await self.vr_repo.delete(vr_id)

    # ── Variation request BOQ (Issue #435) ────────────────────────────────
    #
    # A variation request may own a dedicated bill of quantities holding only
    # the scope that variation changes. Nothing here re-implements a bill: the
    # row is an ordinary ``oe_boq_boq`` created through ``BOQService``, so
    # positions, assemblies, resource costing, markups, calculation, the
    # revision chain, snapshots and every export come with it. What lives here
    # is the two things the BOQ module has no place for - which request a bill
    # belongs to, and what each of its lines traces back to.
    #
    # Every request that has no bill is untouched by all of it. The headline
    # ``estimated_cost_impact`` remains the only figure such a request has,
    # which is exactly how it behaved before.

    async def resolve_request_boq(self, vr_id: uuid.UUID) -> tuple[Any | None, str | None]:
        """Which bill a variation request's priced scope currently lives in.

        Returns ``(boq, None)`` when the answer is unambiguous and
        ``(None, reason)`` when it is not, where ``reason`` is a key of
        :data:`app.core.boq_target.BOQ_TARGET_REFUSALS`. Exactly one of the
        two is ever set.

        A request may own more than one bill, because revising a bill copies
        it (``BOQService.duplicate_boq``) and the copy is still that request's
        bill. The current one is the head of the revision chain: the bill no
        other bill of this request names as its ``parent_estimate_id``. One
        head is the answer. Two heads means the chain forked, and a fork is a
        question - answered by naming the bill, not by guessing between them.
        This is the rule ``app/core/boq_target.py`` states for projects,
        applied to the smaller scope; the refusal vocabulary is shared so a
        client that learned these codes on one endpoint reads them here too.
        """
        from sqlalchemy import select

        from app.modules.boq.models import BOQ

        rows = list(
            (await self.session.execute(select(BOQ).where(BOQ.variation_request_id == vr_id).order_by(BOQ.created_at)))
            .scalars()
            .all()
        )
        if not rows:
            return None, "no_active_boq"
        superseded = {row.parent_estimate_id for row in rows if row.parent_estimate_id is not None}
        heads = [row for row in rows if row.id not in superseded]
        if len(heads) == 1:
            return heads[0], None
        logger.warning(
            "Variation request %s owns %d bills with %d chain heads - the current one cannot be named",
            vr_id,
            len(rows),
            len(heads),
        )
        return None, "ambiguous_boq"

    @staticmethod
    def _request_boq_refusal(reason: str | None) -> HTTPException:
        """The refusal that names why a request's bill could not be resolved.

        Built rather than raised so a caller that already holds the reason can
        raise it without resolving a second time. ``resolve_request_boq``
        hands back the reason with the answer, and asking the database again
        to rediscover it is both a wasted round trip and a chance for the two
        reads to disagree.
        """
        if reason == "no_active_boq":
            return HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "no_variation_boq",
                    "message": "This variation request has no bill of quantities yet.",
                },
            )
        from app.core.boq_target import BOQ_TARGET_REFUSALS

        code = reason or "ambiguous_boq"
        return HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={"error": code, "message": BOQ_TARGET_REFUSALS.get(code, "")},
        )

    async def _require_request_boq(self, vr_id: uuid.UUID) -> Any:
        """The request's current bill, or an HTTP refusal naming why not."""
        boq, reason = await self.resolve_request_boq(vr_id)
        if boq is None:
            raise self._request_boq_refusal(reason)
        return boq

    async def _load_source_positions(
        self,
        project_id: uuid.UUID,
        position_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, Any]:
        """Estimating positions the variation takes scope from, by id.

        Every id must resolve to a position on an *estimating* bill of this
        project. A request that names a position from somewhere else is
        refused rather than silently skipped: seeding a bill with fewer lines
        than were asked for, and saying nothing, is how a variation ends up
        understated.

        Another variation's bill is somewhere else, and is excluded by the
        same ``variation_request_id IS NULL`` filter the three other places
        that mean "the project's own bills" already apply
        (``app/core/boq_target.py``, ``BOQRepository.list_for_project``,
        ``_resolve_writeback_boq`` in change orders). It is priced scope that
        nobody has agreed to yet, so estimating provenance pointing at it
        would defend one unagreed figure with another.
        """
        if not position_ids:
            return {}
        from sqlalchemy import select

        from app.modules.boq.models import BOQ, Position

        rows = list(
            (
                await self.session.execute(
                    select(Position)
                    .join(BOQ, BOQ.id == Position.boq_id)
                    .where(
                        Position.id.in_(position_ids),
                        BOQ.project_id == project_id,
                        BOQ.variation_request_id.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        found = {row.id: row for row in rows}
        missing = [str(pid) for pid in position_ids if pid not in found]
        if missing:
            # One code for one refusal. A caller that learned it when the only
            # filter was the project keeps reading it, and the message says
            # what the filter is now rather than a narrower thing it once was.
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "source_position_not_in_project",
                    "message": (
                        "These positions are not on any estimating bill of this project, so a "
                        "variation on this project cannot take scope from them. Another "
                        "variation's own bill is not estimating scope."
                    ),
                    "position_ids": missing,
                },
            )
        return found

    async def _load_source_contract_lines(
        self,
        project_id: uuid.UUID,
        line_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, Any]:
        """Schedule-of-values lines the variation affects, by id.

        Same project guard as the positions. A missing contracts module is a
        different fact from a wrong id and is answered as such - the caller
        asked for something the installation cannot provide.
        """
        if not line_ids:
            return {}
        from sqlalchemy import select

        try:
            from app.modules.contracts.models import Contract, ContractLine
        except ImportError as exc:  # pragma: no cover - depends on install set
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail={
                    "error": "contracts_module_unavailable",
                    "message": "Contract schedule-of-values lines cannot be read - the contracts module is not installed.",
                },
            ) from exc

        rows = list(
            (
                await self.session.execute(
                    select(ContractLine)
                    .join(Contract, Contract.id == ContractLine.contract_id)
                    .where(ContractLine.id.in_(line_ids), Contract.project_id == project_id)
                )
            )
            .scalars()
            .all()
        )
        found = {row.id: row for row in rows}
        missing = [str(lid) for lid in line_ids if lid not in found]
        if missing:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "contract_line_not_in_project",
                    "message": (
                        "These schedule-of-values lines belong to no contract on this project, so a "
                        "variation on this project cannot be raised against them."
                    ),
                    "contract_line_ids": missing,
                },
            )
        return found

    async def create_request_boq(
        self,
        vr_id: uuid.UUID,
        data: VariationBOQCreate,
        user_id: str | None = None,
    ) -> Any:
        """Open a dedicated bill for a variation request and seed its scope.

        The bill is created through ``BOQService.create_boq`` so it is the
        same kind of row as every other bill, then stamped with the request
        it belongs to. Seeding copies the named estimating positions and
        schedule-of-values lines into it and records where each line came
        from, so the priced figure can be defended line by line.

        A request may own only one bill at a time. Wanting a second one is
        wanting a revision, and the BOQ module already has that
        (``POST /boqs/{id}/create-revision/``), with a chain that says which
        of the two supersedes the other. Two unrelated bills would say
        nothing, and the priced total would stop having an answer.
        """
        from app.modules.boq.schemas import BOQCreate
        from app.modules.boq.service import BOQService

        vr = await self.get_request(vr_id)
        existing, reason = await self.resolve_request_boq(vr_id)
        if existing is not None or reason != "no_active_boq":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail={
                    "error": "variation_boq_exists",
                    "message": (
                        "This variation request already has a bill of quantities. Revise that bill "
                        "instead of opening a second one."
                    ),
                    "boq_id": str(existing.id) if existing is not None else None,
                },
            )

        position_ids = [item.position_id for item in data.source_positions]
        line_ids = [item.contract_line_id for item in data.source_contract_lines]
        sources = await self._load_source_positions(vr.project_id, position_ids)
        contract_lines = await self._load_source_contract_lines(vr.project_id, line_ids)

        title = (vr.title or "").strip()
        default_name = f"{vr.code} - {title}" if title else f"{vr.code} variation bill"
        boq_service = BOQService(self.session)
        boq = await boq_service.create_boq(
            BOQCreate(
                project_id=vr.project_id,
                name=(data.name or default_name)[:255],
                description=(
                    data.description
                    or f"Priced scope of variation request {vr.code}. Separate from the project estimate."
                ),
                # The house discriminator for "what kind of bill is this",
                # alongside the link that actually carries the filtering.
                estimate_type="variation",
                base_date=data.base_date,
            )
        )
        boq_id = boq.id
        await boq_service.boq_repo.update_fields(boq_id, variation_request_id=vr_id)

        traces = await self._seed_variation_boq(
            vr=vr,
            boq_id=boq_id,
            data=data,
            sources=sources,
            contract_lines=contract_lines,
        )

        _safe_publish(
            "variations.request.boq_opened",
            {
                "project_id": str(vr.project_id),
                "variation_request_id": str(vr_id),
                "code": vr.code,
                "boq_id": str(boq_id),
                "lines_seeded": len(traces),
                "actor_id": user_id or "",
            },
        )
        logger.info(
            "Variation request %s opened bill %s with %d seeded line(s)",
            vr.code,
            boq_id,
            len(traces),
        )
        return await boq_service.get_boq(boq_id)

    async def _seed_variation_boq(
        self,
        *,
        vr: VariationRequest,
        boq_id: uuid.UUID,
        data: VariationBOQCreate,
        sources: dict[uuid.UUID, Any],
        contract_lines: dict[uuid.UUID, Any],
    ) -> list[VariationBOQTrace]:
        """Write the seeded lines and their provenance rows.

        Ordinals are ``0010``, ``0020``, … in the order the caller named the
        sources, so the bill reads in the order the estimator described the
        change rather than in whatever order the database returned.
        """
        from app.modules.boq.models import Position

        positions: list[Any] = []
        pending: list[dict[str, Any]] = []
        index = 0

        for item in data.source_positions:
            source = sources[item.position_id]
            quantity = _to_decimal(item.quantity) if item.quantity is not None else _to_decimal(source.quantity)
            rate = _to_decimal(source.unit_rate)
            index += 1
            positions.append(
                Position(
                    boq_id=boq_id,
                    ordinal=f"{index * 10:04d}",
                    description=source.description,
                    unit=source.unit,
                    quantity=format(quantity, "f"),
                    unit_rate=format(rate, "f"),
                    total=format(quantity * rate, "f"),
                    classification=dict(source.classification or {}),
                    source="manual",
                    cad_element_ids=[],
                    sort_order=index,
                )
            )
            pending.append(
                {
                    "origin": "boq_position",
                    "source_boq_id": source.boq_id,
                    "source_position_id": source.id,
                    "contract_id": None,
                    "contract_line_id": None,
                    "note": item.note,
                }
            )

        for item in data.source_contract_lines:
            line = contract_lines[item.contract_line_id]
            quantity = _to_decimal(item.quantity) if item.quantity is not None else _to_decimal(line.quantity)
            rate = _to_decimal(line.unit_rate)
            index += 1
            positions.append(
                Position(
                    boq_id=boq_id,
                    ordinal=f"{index * 10:04d}",
                    description=line.description or line.code or "",
                    unit=line.unit or "",
                    quantity=format(quantity, "f"),
                    unit_rate=format(rate, "f"),
                    total=format(quantity * rate, "f"),
                    classification={},
                    source="manual",
                    cad_element_ids=[],
                    sort_order=index,
                )
            )
            pending.append(
                {
                    "origin": "contract_line",
                    "source_boq_id": None,
                    "source_position_id": None,
                    "contract_id": line.contract_id,
                    "contract_line_id": line.id,
                    "note": item.note,
                }
            )

        if not positions:
            return []

        self.session.add_all(positions)
        await self.session.flush()

        traces = [
            VariationBOQTrace(
                variation_request_id=vr.id,
                boq_id=boq_id,
                position_id=position.id,
                origin=str(fields["origin"]),
                source_boq_id=fields["source_boq_id"],
                source_position_id=fields["source_position_id"],
                contract_id=fields["contract_id"],
                contract_line_id=fields["contract_line_id"],
                note=str(fields["note"] or ""),
            )
            for position, fields in zip(positions, pending, strict=True)
        ]
        return await self.boq_trace_repo.bulk_create(traces)

    async def _require_variation_boq_line(self, vr_id: uuid.UUID, position_id: uuid.UUID) -> Any:
        """The line, once it is established that it is a line of *this* bill.

        Two separate facts, and both have to hold. Project access, checked at
        the route, says the caller may touch this request. It says nothing at
        all about the position id in the path, which is a bare id from another
        module's table: without the ``boq_id`` comparison below, a caller with
        access to one project could write a provenance row naming a line of a
        different project's bill, and the trace table would then hold a row
        about a line its own request has never seen.
        """
        from app.modules.boq.models import Position

        boq = await self._require_request_boq(vr_id)
        position = await self.session.get(Position, position_id)
        if position is None or position.boq_id != boq.id:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "line_not_in_variation_boq",
                    "message": (
                        "This line is not part of this variation request's bill of quantities, so "
                        "its provenance cannot be recorded here."
                    ),
                },
            )
        return position

    async def _write_boq_line_trace(
        self,
        *,
        vr: VariationRequest,
        boq_id: uuid.UUID,
        position_id: uuid.UUID,
        origin: str,
        source_boq_id: uuid.UUID | None,
        source_position_id: uuid.UUID | None,
        contract_id: uuid.UUID | None,
        contract_line_id: uuid.UUID | None,
        note: str,
    ) -> VariationBOQTrace:
        """Upsert the one trace row a line is allowed to have.

        ``uq_oe_variations_boq_trace_position`` permits exactly one row per
        line, so writing provenance a second time has to replace the first
        answer rather than add a second one. Every field is written on both
        paths, including the ones being cleared: a partial update would leave
        the previous answer's ``contract_id`` sitting under a new
        ``source_position_id`` and read as a line traced to both.
        """
        fields = {
            "origin": origin,
            "source_boq_id": source_boq_id,
            "source_position_id": source_position_id,
            "contract_id": contract_id,
            "contract_line_id": contract_line_id,
            "note": note,
        }
        existing = await self.boq_trace_repo.get_for_position(position_id)
        if existing is not None:
            await self.boq_trace_repo.update_fields(existing.id, **fields)
            return existing
        return await self.boq_trace_repo.create(
            VariationBOQTrace(
                variation_request_id=vr.id,
                boq_id=boq_id,
                position_id=position_id,
                **fields,
            )
        )

    async def set_boq_line_trace(
        self,
        vr_id: uuid.UUID,
        position_id: uuid.UUID,
        data: VariationBOQLineTraceUpdate,
        user_id: str | None = None,
    ) -> VariationBOQTrace:
        """Record where one line of a variation's bill came from.

        Seeding a bill records this for the lines it copies, and until this
        existed that was the only moment at which a line could acquire it. A
        bill is an ordinary bill, so it grows through the BOQ editor like any
        other, and every line added that way stayed permanently untraced -
        which ``variations.boq_lines_are_traced`` reported, correctly, with no
        way for the reader to act on it.

        The references are validated against the request's project, which is
        the only scope available: a variation request names a project, not a
        contract, so "the contract this variation is against" is not a fact
        this record holds. A schedule-of-values line of any contract on the
        project is therefore accepted, and one belonging to another project's
        contract is refused by the same loader the seeding path uses.

        The estimating position goes through the same loader, which admits
        only the project's estimating bills. A line of this bill, or of any
        other variation's bill, is refused there rather than guarded against
        here, so there is one answer to "what may a line be traced to" and
        both paths give it.
        """
        vr = await self.get_request(vr_id)
        position = await self._require_variation_boq_line(vr_id, position_id)

        contract_lines = await self._load_source_contract_lines(
            vr.project_id, [data.contract_line_id] if data.contract_line_id else []
        )
        sources = await self._load_source_positions(
            vr.project_id, [data.source_position_id] if data.source_position_id else []
        )
        line = contract_lines.get(data.contract_line_id) if data.contract_line_id else None
        source = sources.get(data.source_position_id) if data.source_position_id else None

        # The contract line is the stronger statement of the two: it says
        # what contracted scope this line changes, which is what a variation
        # argues about. The estimating position is provenance for the money.
        origin = "contract_line" if line is not None else "boq_position" if source is not None else "manual"
        trace = await self._write_boq_line_trace(
            vr=vr,
            boq_id=position.boq_id,
            position_id=position_id,
            origin=origin,
            source_boq_id=source.boq_id if source is not None else None,
            source_position_id=source.id if source is not None else None,
            contract_id=line.contract_id if line is not None else None,
            contract_line_id=line.id if line is not None else None,
            note=data.note,
        )
        _safe_publish(
            "variations.request.boq_line_traced",
            {
                "project_id": str(vr.project_id),
                "variation_request_id": str(vr_id),
                "code": vr.code,
                "boq_id": str(position.boq_id),
                "position_id": str(position_id),
                "origin": origin,
                "actor_id": user_id or "",
            },
        )
        logger.info(
            "Variation request %s traced line %s of bill %s as %s",
            vr.code,
            position_id,
            position.boq_id,
            origin,
        )
        return trace

    async def clear_boq_line_trace(
        self,
        vr_id: uuid.UUID,
        position_id: uuid.UUID,
        user_id: str | None = None,
    ) -> VariationBOQTrace:
        """Withdraw a line's provenance without withdrawing the answer.

        The row survives with ``origin='manual'`` and both references null,
        which is the state the model describes for a line entered by hand:
        "recorded with ``origin='manual'`` rather than left without a row, so
        the trace covers the bill rather than only the parts of it that were
        derived". Deleting the row instead would make "nobody has said" and
        "somebody said it derives from nothing" the same absence.

        The line then fails ``variations.boq_lines_are_traced`` again, which
        is correct: it no longer traces anywhere.
        """
        vr = await self.get_request(vr_id)
        position = await self._require_variation_boq_line(vr_id, position_id)
        trace = await self._write_boq_line_trace(
            vr=vr,
            boq_id=position.boq_id,
            position_id=position_id,
            origin="manual",
            source_boq_id=None,
            source_position_id=None,
            contract_id=None,
            contract_line_id=None,
            note="",
        )
        _safe_publish(
            "variations.request.boq_line_trace_cleared",
            {
                "project_id": str(vr.project_id),
                "variation_request_id": str(vr_id),
                "code": vr.code,
                "boq_id": str(position.boq_id),
                "position_id": str(position_id),
                "actor_id": user_id or "",
            },
        )
        return trace

    async def get_request_boq_view(self, vr_id: uuid.UUID) -> dict[str, Any]:
        """Everything the request's bill says, priced and traced.

        A request with no bill answers ``has_boq`` false with its headline
        estimate and nothing else - the shape a request has always had. A
        request with a bill answers with the bill's own FX-correct totals,
        taken from ``BOQService.compute_boq_totals`` rather than summed here,
        so the figure is the same one the BOQ list, detail and export paths
        report.
        """
        vr = await self.get_request(vr_id)
        headline = _to_decimal(vr.estimated_cost_impact)
        boq, reason = await self.resolve_request_boq(vr_id)
        if boq is None:
            if reason == "no_active_boq":
                return {
                    "variation_request_id": vr_id,
                    "has_boq": False,
                    "estimated_cost_impact": headline,
                }
            # The revision chain forked. The reason came back with the answer,
            # so raise it here rather than resolving again to rediscover it.
            raise self._request_boq_refusal(reason)

        from sqlalchemy import select

        from app.modules.boq.models import Position
        from app.modules.boq.service import BOQService

        boq_id = boq.id
        breakdown = (await BOQService(self.session).compute_boq_totals([boq_id])).get(boq_id, {})
        rows = list(
            (
                await self.session.execute(
                    select(Position).where(Position.boq_id == boq_id).order_by(Position.sort_order)
                )
            )
            .scalars()
            .all()
        )
        traces = await self.boq_trace_repo.list_for_boq(boq_id)
        by_position = {trace.position_id: trace for trace in traces}

        grand_total = _money(breakdown.get("grand_total"))
        payload: dict[str, Any] = {
            "variation_request_id": vr_id,
            "has_boq": True,
            "boq_id": boq_id,
            "name": boq.name,
            "status": boq.status,
            "is_locked": bool(boq.is_locked),
            "parent_estimate_id": boq.parent_estimate_id,
            "position_count": sum(1 for row in rows if (row.unit or "") not in ("", "section")),
            "base_currency": str(breakdown.get("base_currency") or ""),
            "direct_cost": _money(breakdown.get("direct_cost")),
            "markups_total": _money(breakdown.get("markups_total")),
            "grand_total": grand_total,
            "is_mixed_currency": bool(breakdown.get("is_mixed_currency")),
            "estimated_cost_impact": headline,
            "estimate_matches_boq": abs(headline - grand_total) < _MONEY_EPSILON,
            "traces": traces,
        }
        payload["checks"] = await self._run_variation_boq_rules(payload, rows, by_position)
        return payload

    async def _run_variation_boq_rules(
        self,
        payload: dict[str, Any],
        rows: list[Any],
        by_position: dict[uuid.UUID, VariationBOQTrace],
    ) -> list[dict[str, Any]]:
        """Run the variation rule set over the bill and flatten the report.

        Validation is part of reading the bill, not a screen somebody has to
        know to open. A failure to validate is never allowed to take the
        priced figure down with it - the rules explain the number, they do not
        produce it - so a broken engine comes back as an empty list.
        """
        try:
            from app.core.validation.engine import ValidationEngine, rule_registry
            from app.modules.variations.validators import (
                VARIATIONS_RULE_SET,
                register_variations_rules,
            )

            register_variations_rules()
            report = await ValidationEngine(rule_registry).validate(
                data={
                    "variation_request_id": str(payload["variation_request_id"]),
                    "grand_total": payload["grand_total"],
                    "estimated_cost_impact": payload["estimated_cost_impact"],
                    "is_mixed_currency": payload["is_mixed_currency"],
                    "lines": [
                        {
                            "id": str(row.id),
                            "ordinal": row.ordinal,
                            "unit": row.unit,
                            "source_position_id": (
                                str(by_position[row.id].source_position_id)
                                if row.id in by_position and by_position[row.id].source_position_id
                                else None
                            ),
                            "contract_line_id": (
                                str(by_position[row.id].contract_line_id)
                                if row.id in by_position and by_position[row.id].contract_line_id
                                else None
                            ),
                        }
                        for row in rows
                    ],
                },
                rule_sets=[VARIATIONS_RULE_SET],
                target_type="boq",
                target_id=str(payload.get("boq_id") or ""),
                metadata={"locale": get_locale()},
            )
        except Exception:
            logger.warning(
                "Validation of the bill of variation request %s could not be run",
                payload.get("variation_request_id"),
                exc_info=True,
            )
            return []
        return [
            {
                "rule_id": result.rule_id,
                "severity": getattr(result.severity, "value", str(result.severity)),
                "passed": bool(result.passed),
                "message": result.message,
            }
            for result in report.results
            if not result.passed
        ]

    async def adopt_request_boq_total(
        self,
        vr_id: uuid.UUID,
        user_id: str | None = None,
    ) -> VariationRequest:
        """Make the bill's priced total the request's headline figure.

        Deliberately an explicit act rather than a side effect of pricing.
        The headline is what every other module reads off a request - the
        approval threshold, the dashboards, the change-intelligence roll-up -
        so moving it is a decision, and a bill that is still being worked on
        would otherwise move it on every keystroke.

        Refused on a decided request: the figure a decision was taken on has
        to stay the figure that was decided on. Refused on a bill that blends
        currencies, because the total is then a blend nobody agreed to a
        rate for.
        """
        vr = await self.get_request(vr_id)
        if vr.status in ("approved", "rejected", "converted_to_vo"):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail={
                    "error": "variation_request_decided",
                    "message": (
                        "This variation request has already been decided, so the figure it was "
                        "decided on cannot be replaced."
                    ),
                },
            )
        boq = await self._require_request_boq(vr_id)

        from app.modules.boq.service import BOQService

        breakdown = (await BOQService(self.session).compute_boq_totals([boq.id])).get(boq.id, {})
        if bool(breakdown.get("is_mixed_currency")):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail={
                    "error": "mixed_currency_boq",
                    "message": (
                        "This bill blends currencies, so its total is not a figure the request can "
                        "carry. Settle the lines on one currency first."
                    ),
                },
            )
        priced = _money(breakdown.get("grand_total"))
        fields: dict[str, Any] = {"estimated_cost_impact": priced}
        base_currency = str(breakdown.get("base_currency") or "")
        if not (vr.currency or "").strip() and base_currency:
            # Only ever fills a blank. A currency somebody chose is theirs.
            fields["currency"] = base_currency[:10]
        await self.vr_repo.update_fields(vr_id, **fields)
        await self.session.refresh(vr)

        _safe_publish(
            "variations.request.boq_adopted",
            {
                "project_id": str(vr.project_id),
                "variation_request_id": str(vr_id),
                "code": vr.code,
                "boq_id": str(boq.id),
                "estimated_cost_impact": str(priced),
                "currency": vr.currency or "",
                "actor_id": user_id or "",
            },
        )
        return vr

    # ── VariationOrder ────────────────────────────────────────────────────

    async def create_order(
        self,
        data: VariationOrderCreate,
        user_id: str | None = None,
    ) -> VariationOrder:
        code = await self.vo_repo.next_code(data.project_id)
        # Inherit clause-ref from the upstream VR if not specified on the VO.
        standard = (getattr(data, "contract_standard", "") or "").upper()
        clause_ref = getattr(data, "contract_clause_ref", "") or ""
        if (not standard or not clause_ref) and data.variation_request_id:
            try:
                vr = await self.get_request(data.variation_request_id)
                standard = standard or (vr.contract_standard or "")
                clause_ref = clause_ref or (vr.contract_clause_ref or "")
            except HTTPException:
                # Upstream VR vanished - proceed without clause carry-over.
                pass
        affected_contract = getattr(data, "affected_contract_id", None)
        vo = VariationOrder(
            project_id=data.project_id,
            variation_request_id=data.variation_request_id,
            code=code,
            title=data.title,
            final_cost_impact=_to_decimal(data.final_cost_impact),
            final_schedule_days=data.final_schedule_days,
            currency=data.currency,
            agreed_at=data.agreed_at or _now_iso(),
            signed_by=data.signed_by or user_id,
            status=data.status,
            reference_change_order_id=data.reference_change_order_id,
            affected_contract_id=affected_contract,
            contract_standard=standard,
            contract_clause_ref=clause_ref,
            metadata_=data.metadata,
        )
        vo = await self.vo_repo.create(vo)
        _safe_publish(
            "variations.vo.issued",
            {
                "project_id": str(data.project_id),
                "vo_id": str(vo.id),
                "code": code,
                "final_cost_impact": str(vo.final_cost_impact),
            },
        )
        return vo

    async def get_order(self, vo_id: uuid.UUID) -> VariationOrder:
        row = await self.vo_repo.get_by_id(vo_id)
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Variation order not found",
            )
        return row

    async def update_order(
        self,
        vo_id: uuid.UUID,
        data: VariationOrderUpdate,
        user_id: str | None = None,
    ) -> VariationOrder:
        vo = await self.get_order(vo_id)
        # A completed VO has already adjusted the contract sum / final
        # account; a voided VO is a closed record. Either way its money
        # must not be silently rewritten - that would desync the final
        # account on the next recompute. Status moves via
        # ``transition_variation_order`` only.
        if vo.status in {"completed", "voided"}:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=(f"Variation order is {vo.status} and is no longer editable"),
            )
        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if "final_cost_impact" in fields and fields["final_cost_impact"] is not None:
            fields["final_cost_impact"] = _to_decimal(fields["final_cost_impact"])
        if not fields:
            return vo
        ball_changed = "ball_in_court" in fields and fields["ball_in_court"] != vo.ball_in_court
        old_ball = vo.ball_in_court
        code_snapshot = vo.code
        await self.vo_repo.update_fields(vo_id, **fields)
        await self.session.refresh(vo)
        if ball_changed:
            await _log_ownership_change(
                self.session,
                entity_type="variation_order",
                entity_id=vo_id,
                from_party=old_ball,
                to_party=fields["ball_in_court"],
                actor_id=user_id,
                code=code_snapshot,
            )
        return vo

    async def transition_variation_order(
        self,
        vo_id: uuid.UUID,
        to_status: str,
        user_id: str | None = None,
    ) -> VariationOrder:
        vo = await self.get_order(vo_id)
        if to_status not in allowed_vo_transitions(vo.status):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Cannot transition VO from {vo.status} to {to_status}",
            )
        fields: dict[str, Any] = {"status": to_status}
        now = _now_iso()
        if to_status == "in_progress":
            fields["implementation_started_at"] = now
        if to_status == "completed":
            fields["implementation_completed_at"] = now
        await self.vo_repo.update_fields(vo_id, **fields)
        await self.session.refresh(vo)
        event_name = {
            "in_progress": "variations.vo.started",
            "completed": "variations.vo.completed",
            "voided": "variations.vo.voided",
        }.get(to_status, f"variations.vo.{to_status}")
        _safe_publish(
            event_name,
            {
                "project_id": str(vo.project_id),
                "vo_id": str(vo_id),
                "code": vo.code,
                "to_status": to_status,
            },
        )

        # When a VO completes against a contract, emit a structured event
        # that oe_contracts can subscribe to and bump the contract sum.
        affected_contract = getattr(vo, "affected_contract_id", None)
        if to_status == "completed" and affected_contract:
            _safe_publish(
                "variations.contract_sum.updated",
                {
                    "project_id": str(vo.project_id),
                    "vo_id": str(vo_id),
                    "contract_id": str(affected_contract),
                    "code": vo.code,
                    "delta_amount": str(vo.final_cost_impact),
                    "currency": vo.currency,
                    "contract_standard": getattr(vo, "contract_standard", "") or "",
                    "contract_clause_ref": getattr(vo, "contract_clause_ref", "") or "",
                },
            )
        return vo

    async def delete_order(self, vo_id: uuid.UUID) -> None:
        await self.get_order(vo_id)
        await self.vo_repo.delete(vo_id)

    async def convert_vr_to_vo(
        self,
        vr_id: uuid.UUID,
        vo_payload: VariationOrderCreate,
        user_id: str | None = None,
    ) -> VariationOrder:
        """Promote an approved VariationRequest into a VariationOrder.

        R7 audit: in addition to creating the VariationOrder we now
        atomically mirror it into oe_changeorders as a draft ChangeOrder
        and stamp the cross-module soft link
        (``vo.reference_change_order_id``). All three writes (VO insert,
        VR.status flip, CO insert) share the calling AsyncSession so a
        failure in any rolls back the entire promotion - previously the
        only cross-module linkage was an event publish, which made the CO
        eventually-consistent at best and silently-dropped at worst when
        the subscriber wasn't wired up.

        Currency consistency: the CO inherits the VO's currency (which
        itself inherited from the project on create). Money figures
        propagate as Decimal throughout - no float coercion.

        Emits ``variations.vo.issued`` and ``variations.change_order.created``
        once the writes have flushed.
        """
        vr = await self.get_request(vr_id)
        if vr.status != "approved":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Only approved VRs can be converted (current: {vr.status})",
            )

        # R8 race-safety: flip the VR status to ``converted_to_vo`` BEFORE
        # creating the VO. Without this, two concurrent calls both pass the
        # ``status == "approved"`` guard above and both reach ``create_order``,
        # resulting in two VOs (and two COs) for one VR - a commercial ledger
        # integrity violation. The conditional UPDATE below is atomic at the
        # database level: only ONE caller's WHERE clause can match a row that is
        # still ``approved``; the loser sees rowcount == 0 and 409s cleanly.
        # This replaces the earlier ``vr_repo.update_fields(status=…)`` call at
        # the bottom of the method which was a TOCTOU window.
        from sqlalchemy import update as _sa_update

        guard_stmt = (
            _sa_update(VariationRequest)
            .where(VariationRequest.id == vr_id)
            .where(VariationRequest.status == "approved")
            .values(status="converted_to_vo")
        )
        guard_result = await self.session.execute(guard_stmt)
        affected = getattr(guard_result, "rowcount", None)
        if affected == 0:
            # A concurrent call already flipped the status - re-fetch for the
            # current status so the error message is accurate.
            refreshed = await self.vr_repo.get_by_id(vr_id)
            current_status = getattr(refreshed, "status", "unknown") if refreshed else "unknown"
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=(
                    f"Variation request was concurrently converted (current: {current_status}). "
                    "Only one VO may be created per approved VR."
                ),
            )
        # Keep the in-memory VR instance in sync so subsequent code and the
        # ActivityLog writer see the new status without an extra round-trip.
        vr.status = "converted_to_vo"
        await self.session.flush()

        # Force link to the source VR, and carry the request's own figures
        # into the order for everything the caller did not name.
        #
        # Every field of ``VariationOrderCreate`` has a schema default, so a
        # caller that sends only a currency - which is what the variations
        # page does - used to land an order titled "" and valued at zero,
        # losing the figures the request was approved on. ``model_fields_set``
        # is what tells "not sent" apart from "sent as empty", so an order
        # deliberately agreed at zero, or retitled on promotion, still gets
        # exactly what was asked for. Read before the ``model_dump()``
        # round-trip below, which does not preserve it.
        named = vo_payload.model_fields_set
        payload_dict = vo_payload.model_dump()
        payload_dict["project_id"] = vr.project_id
        payload_dict["variation_request_id"] = vr_id
        if "title" not in named:
            payload_dict["title"] = vr.title or ""
        if "final_cost_impact" not in named:
            # Issue #435: the agreed value is what flows, and it flows without
            # being re-entered. The headline is the fallback only for a
            # request approved before the agreement was recorded at all;
            # for anything approved since, falling back to it would be the
            # implicit inheritance the approval boundary exists to end.
            agreed = getattr(vr, "agreed_cost_impact", None)
            payload_dict["final_cost_impact"] = (
                _to_decimal(agreed) if agreed is not None else _to_decimal(vr.estimated_cost_impact)
            )
        if "final_schedule_days" not in named:
            payload_dict["final_schedule_days"] = vr.estimated_schedule_days or 0
        if "currency" not in named:
            payload_dict["currency"] = vr.currency or ""
        forced = VariationOrderCreate(**payload_dict)
        vo = await self.create_order(forced, user_id=user_id)

        # R7 audit: mirror into oe_changeorders inside the same txn. Both
        # writes share ``self.session`` so a rollback unwinds both. The
        # CO carries the VO's cost impact + currency so the two rows are
        # immediately reconcilable; subsequent VO completion can transition
        # the CO through its own approval chain.
        co_id: uuid.UUID | None = None
        try:
            from app.modules.changeorders.schemas import ChangeOrderCreate
            from app.modules.changeorders.service import ChangeOrderService

            co_service = ChangeOrderService(self.session)
            co_payload = ChangeOrderCreate(
                project_id=vr.project_id,
                title=vo.title or vr.title or f"VO {vo.code}",
                description=(
                    f"Auto-created from variation order {vo.code} (VR {vr.code}). Cost impact mirrors the VO."
                ),
                reason_category="design_change",
                schedule_impact_days=max(0, int(vo.final_schedule_days or 0)),
                currency=vo.currency or vr.currency or "",
                cost_impact=str(_to_decimal(vo.final_cost_impact)),
                metadata={
                    "origin": "variations.convert_vr_to_vo",
                    "variation_request_id": str(vr_id),
                    "variation_order_id": str(vo.id),
                },
            )
            co = await co_service.create_order(co_payload)
            co_id = co.id
            await self.vo_repo.update_fields(
                vo.id,
                reference_change_order_id=co_id,
            )
        except HTTPException:
            raise
        except Exception:
            # Mirror failure must roll back the whole promotion - the
            # whole point of doing it in the same txn is to avoid an
            # orphan VO with no CO. Re-raise as 500.
            logger.exception(
                "Failed to mirror VR %s -> VO %s into ChangeOrder; rolling back the promotion",
                vr_id,
                vo.id,
            )
            await self.session.rollback()
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=("Failed to mirror variation order into change orders module; promotion rolled back."),
            )

        # VR.status was already flipped to converted_to_vo by the guard above.
        await self.session.refresh(vr)
        await self.session.refresh(vo)

        _safe_publish(
            "variations.change_order.created",
            {
                "project_id": str(vr.project_id),
                "request_id": str(vr_id),
                "vo_id": str(vo.id),
                "change_order_id": str(co_id) if co_id else None,
                "title": vo.title,
                "cost_impact": str(vo.final_cost_impact),
                "schedule_days": vo.final_schedule_days,
                "currency": vo.currency,
            },
        )
        return vo

    # ── Cost impact lines ─────────────────────────────────────────────────

    async def add_cost_impact(
        self,
        data: VariationCostImpactCreate,
    ) -> VariationCostImpact:
        # Validate VO exists.
        vo = await self.get_order(data.variation_order_id)
        qty = _to_decimal(data.quantity)
        rate = _to_decimal(data.unit_rate)
        # R5 audit: line-level currency MUST be normalised to the owning VO
        # when the line was created without one. A blank-currency line lets
        # the dashboard / final-account roll-up sum mixed currencies into a
        # single number - a "100 EUR" line and a "100 USD" line become
        # "200" in the bag with no FX trail. Inheriting at write time is
        # the only place we still have the canonical currency.
        line_currency = (data.currency or "").strip() or (vo.currency or "")
        row = VariationCostImpact(
            variation_order_id=data.variation_order_id,
            category=data.category,
            description=data.description,
            quantity=qty,
            unit=data.unit,
            unit_rate=rate,
            total=(qty * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            currency=line_currency,
            source=data.source,
        )
        return await self.cost_impact_repo.create(row)

    async def update_cost_impact(
        self,
        line_id: uuid.UUID,
        data: VariationCostImpactUpdate,
    ) -> VariationCostImpact:
        row = await self.cost_impact_repo.get_by_id(line_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Cost-impact line not found")
        fields = data.model_dump(exclude_unset=True)
        if "quantity" in fields and fields["quantity"] is not None:
            fields["quantity"] = _to_decimal(fields["quantity"])
        if "unit_rate" in fields and fields["unit_rate"] is not None:
            fields["unit_rate"] = _to_decimal(fields["unit_rate"])
        new_qty = fields.get("quantity", row.quantity)
        new_rate = fields.get("unit_rate", row.unit_rate)
        fields["total"] = (_to_decimal(new_qty) * _to_decimal(new_rate)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        await self.cost_impact_repo.update_fields(line_id, **fields)
        await self.session.refresh(row)
        return row

    async def delete_cost_impact(self, line_id: uuid.UUID) -> None:
        row = await self.cost_impact_repo.get_by_id(line_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Cost-impact line not found")
        await self.cost_impact_repo.delete(line_id)

    async def bulk_cost_impacts(
        self,
        vo_id: uuid.UUID,
        lines: list[VariationCostImpactCreate],
    ) -> list[VariationCostImpact]:
        # R5 audit: cap bulk payload - unbounded POST is a trivial DoS /
        # disk-fill vector (the router has no other size gate beyond
        # uvicorn's body limit, which is generous).
        if len(lines) > BULK_LINES_MAX:
            raise HTTPException(
                status_code=http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Bulk payload exceeds {BULK_LINES_MAX} lines",
            )
        out: list[VariationCostImpact] = []
        for line in lines:
            forced = line.model_copy(update={"variation_order_id": vo_id})
            out.append(await self.add_cost_impact(forced))
        return out

    # ── Schedule impact lines ─────────────────────────────────────────────

    async def add_schedule_impact(
        self,
        data: VariationScheduleImpactCreate,
    ) -> VariationScheduleImpact:
        await self.get_order(data.variation_order_id)
        row = VariationScheduleImpact(
            variation_order_id=data.variation_order_id,
            affected_activity_ref=data.affected_activity_ref,
            original_finish_date=data.original_finish_date,
            revised_finish_date=data.revised_finish_date,
            days_added=data.days_added,
            is_critical_path=data.is_critical_path,
            justification=data.justification,
        )
        return await self.schedule_impact_repo.create(row)

    async def update_schedule_impact(
        self,
        line_id: uuid.UUID,
        data: VariationScheduleImpactUpdate,
    ) -> VariationScheduleImpact:
        row = await self.schedule_impact_repo.get_by_id(line_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Schedule-impact line not found")
        fields = data.model_dump(exclude_unset=True)
        if not fields:
            return row
        await self.schedule_impact_repo.update_fields(line_id, **fields)
        await self.session.refresh(row)
        return row

    async def delete_schedule_impact(self, line_id: uuid.UUID) -> None:
        row = await self.schedule_impact_repo.get_by_id(line_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Schedule-impact line not found")
        await self.schedule_impact_repo.delete(line_id)

    # ── Site measurement ─────────────────────────────────────────────────

    async def record_site_measurement(
        self,
        data: SiteMeasurementCreate,
        user_id: str | None = None,
    ) -> SiteMeasurement:
        sm = SiteMeasurement(
            project_id=data.project_id,
            recorded_at=data.recorded_at or _now_iso(),
            recorded_by=data.recorded_by or user_id,
            location=data.location,
            item_description=data.item_description,
            unit=data.unit,
            measured_quantity=_to_decimal(data.measured_quantity),
            agreed_with_owner_at=data.agreed_with_owner_at,
            owner_signature_ref=data.owner_signature_ref,
            photos=list(data.photos or []),
            notes=data.notes,
            contract_line_id=data.contract_line_id,
            variation_order_id=data.variation_order_id,
        )
        sm = await self.site_measurement_repo.create(sm)
        _safe_publish(
            "variations.measurement.recorded",
            {
                "project_id": str(data.project_id),
                "measurement_id": str(sm.id),
                "variation_order_id": (str(data.variation_order_id) if data.variation_order_id else None),
                "quantity": str(sm.measured_quantity),
                "unit": sm.unit,
            },
        )
        return sm

    async def get_site_measurement(self, sm_id: uuid.UUID) -> SiteMeasurement:
        row = await self.site_measurement_repo.get_by_id(sm_id)
        if row is None:
            raise HTTPException(status_code=404, detail=translate("errors.measurement_not_found", locale=get_locale()))
        return row

    async def update_site_measurement(
        self,
        sm_id: uuid.UUID,
        data: SiteMeasurementUpdate,
    ) -> SiteMeasurement:
        sm = await self.site_measurement_repo.get_by_id(sm_id)
        if sm is None:
            raise HTTPException(status_code=404, detail=translate("errors.measurement_not_found", locale=get_locale()))
        fields = data.model_dump(exclude_unset=True)
        if "measured_quantity" in fields and fields["measured_quantity"] is not None:
            fields["measured_quantity"] = _to_decimal(fields["measured_quantity"])
        if not fields:
            return sm
        await self.site_measurement_repo.update_fields(sm_id, **fields)
        await self.session.refresh(sm)
        return sm

    async def agree_site_measurement(
        self,
        sm_id: uuid.UUID,
        user_id: str | None = None,
    ) -> SiteMeasurement:
        sm = await self.site_measurement_repo.get_by_id(sm_id)
        if sm is None:
            raise HTTPException(status_code=404, detail=translate("errors.measurement_not_found", locale=get_locale()))
        await self.site_measurement_repo.update_fields(
            sm_id,
            agreed_with_owner_at=_now_iso(),
        )
        await self.session.refresh(sm)
        _safe_publish(
            "variations.measurement.agreed",
            {"project_id": str(sm.project_id), "measurement_id": str(sm_id)},
        )
        # R5 audit: structured log on the decision so the audit trail is
        # independent of the event-bus subscriber graph.
        _log_decision(
            "variations.measurement.agreed",
            user_id=user_id,
            project_id=sm.project_id,
            target_id=sm_id,
            quantity=str(sm.measured_quantity),
            unit=sm.unit,
        )
        return sm

    async def delete_site_measurement(self, sm_id: uuid.UUID) -> None:
        sm = await self.site_measurement_repo.get_by_id(sm_id)
        if sm is None:
            raise HTTPException(status_code=404, detail=translate("errors.measurement_not_found", locale=get_locale()))
        await self.site_measurement_repo.delete(sm_id)

    # ── Daywork sheets ───────────────────────────────────────────────────

    async def create_daywork_sheet(
        self,
        data: DayworkSheetCreate,
        user_id: str | None = None,
    ) -> DayworkSheet:
        sheet_number = await self.daywork_repo.next_sheet_number(data.project_id)
        ds = DayworkSheet(
            project_id=data.project_id,
            sheet_number=sheet_number,
            work_date=data.work_date,
            description=data.description,
            subtotal_amount=Decimal("0"),
            markup_percent=_to_decimal(getattr(data, "markup_percent", 0)),
            total_amount=Decimal("0"),
            currency=data.currency,
            status=data.status,
            owner_signature_ref=data.owner_signature_ref,
            supplied_via_contract_id=data.supplied_via_contract_id,
        )
        ds = await self.daywork_repo.create(ds)
        _safe_publish(
            "variations.daywork.created",
            {"project_id": str(data.project_id), "sheet_id": str(ds.id), "sheet_number": sheet_number},
        )
        return ds

    async def get_daywork_sheet(self, sheet_id: uuid.UUID) -> DayworkSheet:
        row = await self.daywork_repo.get_by_id(sheet_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Daywork sheet not found")
        return row

    async def update_daywork_sheet(
        self,
        sheet_id: uuid.UUID,
        data: DayworkSheetUpdate,
    ) -> DayworkSheet:
        ds = await self.get_daywork_sheet(sheet_id)
        fields = data.model_dump(exclude_unset=True)
        if not fields:
            return ds
        await self.daywork_repo.update_fields(sheet_id, **fields)
        await self.session.refresh(ds)
        return ds

    async def sign_daywork_sheet(
        self,
        sheet_id: uuid.UUID,
        signer_id: str | None,
    ) -> DayworkSheet:
        ds = await self.get_daywork_sheet(sheet_id)
        if "signed" not in allowed_daywork_transitions(ds.status):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Cannot sign daywork in status {ds.status}",
            )
        # Recompute subtotal + apply BS 6079 markup before signing.
        lines = await self.daywork_line_repo.list_for_sheet(sheet_id)
        subtotal = compute_daywork_sheet_total(lines)
        markup_pct = _to_decimal(getattr(ds, "markup_percent", 0))
        total = apply_daywork_markup(subtotal, markup_pct)
        await self.daywork_repo.update_fields(
            sheet_id,
            status="signed",
            signed_by=signer_id,
            signed_at=_now_iso(),
            subtotal_amount=subtotal,
            total_amount=total,
        )
        await self.session.refresh(ds)
        _safe_publish(
            "variations.daywork.signed",
            {
                "project_id": str(ds.project_id),
                "sheet_id": str(sheet_id),
                "sheet_number": ds.sheet_number,
                "subtotal": str(subtotal),
                "markup_percent": str(markup_pct),
                "total": str(total),
                "currency": ds.currency,
            },
        )
        return ds

    async def transition_daywork(
        self,
        sheet_id: uuid.UUID,
        to_status: str,
    ) -> DayworkSheet:
        ds = await self.get_daywork_sheet(sheet_id)
        if to_status not in allowed_daywork_transitions(ds.status):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Cannot transition daywork from {ds.status} to {to_status}",
            )
        await self.daywork_repo.update_fields(sheet_id, status=to_status)
        await self.session.refresh(ds)
        _safe_publish(
            f"variations.daywork.{to_status}",
            {"project_id": str(ds.project_id), "sheet_id": str(sheet_id)},
        )
        return ds

    async def delete_daywork_sheet(self, sheet_id: uuid.UUID) -> None:
        await self.get_daywork_sheet(sheet_id)
        await self.daywork_repo.delete(sheet_id)

    # ── Daywork lines ─────────────────────────────────────────────────────

    async def add_daywork_line(
        self,
        data: DayworkSheetLineCreate,
    ) -> DayworkSheetLine:
        await self.get_daywork_sheet(data.sheet_id)
        qty = _to_decimal(data.quantity)
        rate = _to_decimal(data.unit_rate)
        row = DayworkSheetLine(
            sheet_id=data.sheet_id,
            line_type=data.line_type,
            description=data.description,
            quantity=qty,
            unit=data.unit,
            unit_rate=rate,
            total=(qty * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            worker_name=data.worker_name,
            equipment_code=data.equipment_code,
        )
        row = await self.daywork_line_repo.create(row)
        # Refresh sheet total.
        lines = await self.daywork_line_repo.list_for_sheet(data.sheet_id)
        subtotal = compute_daywork_sheet_total(lines)
        sheet = await self.get_daywork_sheet(data.sheet_id)
        total = apply_daywork_markup(subtotal, getattr(sheet, "markup_percent", 0))
        await self.daywork_repo.update_fields(
            data.sheet_id,
            subtotal_amount=subtotal,
            total_amount=total,
        )
        # Re-load the just-created ``row`` so the caller serializes it with the
        # sheet totals recomputed above and never lazy-loads mid-serialise,
        # which raises MissingGreenlet.
        await self.session.refresh(row)
        return row

    async def update_daywork_line(
        self,
        line_id: uuid.UUID,
        data: DayworkSheetLineUpdate,
    ) -> DayworkSheetLine:
        row = await self.daywork_line_repo.get_by_id(line_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Daywork line not found")
        fields = data.model_dump(exclude_unset=True)
        if "quantity" in fields and fields["quantity"] is not None:
            fields["quantity"] = _to_decimal(fields["quantity"])
        if "unit_rate" in fields and fields["unit_rate"] is not None:
            fields["unit_rate"] = _to_decimal(fields["unit_rate"])
        new_qty = fields.get("quantity", row.quantity)
        new_rate = fields.get("unit_rate", row.unit_rate)
        fields["total"] = (_to_decimal(new_qty) * _to_decimal(new_rate)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        await self.daywork_line_repo.update_fields(line_id, **fields)
        await self.session.refresh(row)
        # Refresh sheet total.
        lines = await self.daywork_line_repo.list_for_sheet(row.sheet_id)
        subtotal = compute_daywork_sheet_total(lines)
        sheet = await self.get_daywork_sheet(row.sheet_id)
        total = apply_daywork_markup(subtotal, getattr(sheet, "markup_percent", 0))
        await self.daywork_repo.update_fields(
            row.sheet_id,
            subtotal_amount=subtotal,
            total_amount=total,
        )
        # Reload before returning so the response carries the line together with
        # the sheet totals recomputed above, without a lazy load that would
        # raise MissingGreenlet.
        await self.session.refresh(row)
        return row

    async def delete_daywork_line(self, line_id: uuid.UUID) -> None:
        row = await self.daywork_line_repo.get_by_id(line_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Daywork line not found")
        sheet_id = row.sheet_id
        await self.daywork_line_repo.delete(line_id)
        lines = await self.daywork_line_repo.list_for_sheet(sheet_id)
        subtotal = compute_daywork_sheet_total(lines)
        sheet = await self.get_daywork_sheet(sheet_id)
        total = apply_daywork_markup(subtotal, getattr(sheet, "markup_percent", 0))
        await self.daywork_repo.update_fields(
            sheet_id,
            subtotal_amount=subtotal,
            total_amount=total,
        )

    async def bulk_daywork_lines(
        self,
        sheet_id: uuid.UUID,
        lines: list[DayworkSheetLineCreate],
    ) -> list[DayworkSheetLine]:
        # R5 audit: same DoS guard as ``bulk_cost_impacts``.
        if len(lines) > BULK_LINES_MAX:
            raise HTTPException(
                status_code=http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Bulk payload exceeds {BULK_LINES_MAX} lines",
            )
        out: list[DayworkSheetLine] = []
        for line in lines:
            forced = line.model_copy(update={"sheet_id": sheet_id})
            out.append(await self.add_daywork_line(forced))
        return out

    # ── Disruption claims ────────────────────────────────────────────────

    async def submit_disruption_claim(
        self,
        data: DisruptionClaimCreate,
        user_id: str | None = None,
    ) -> DisruptionClaim:
        # AICPA measured-mile: if baseline + impacted productivity are
        # supplied, derive labour_hours_lost from the measured quantity
        # (when omitted) using the formula in compute_disruption_lost_hours.
        baseline = getattr(data, "baseline_productivity", None)
        impacted = getattr(data, "impacted_productivity", None)
        measured_qty = getattr(data, "measured_quantity", None) or 0
        labour_hours = getattr(data, "labour_hours_lost", None)
        if labour_hours is None and baseline is not None and impacted is not None:
            labour_hours = compute_disruption_lost_hours(
                baseline,
                impacted,
                measured_qty,
            )
        claim = DisruptionClaim(
            project_id=data.project_id,
            raised_at=data.raised_at or _now_iso(),
            raised_by=data.raised_by or user_id,
            claim_period_start=data.claim_period_start,
            claim_period_end=data.claim_period_end,
            description=data.description,
            root_cause=data.root_cause,
            cost_amount=_to_decimal(data.cost_amount),
            schedule_days=data.schedule_days,
            currency=data.currency,
            evidence_refs=list(data.evidence_refs or []),
            status=data.status,
            notes=data.notes,
            baseline_productivity=(_to_decimal(baseline) if baseline is not None else None),
            impacted_productivity=(_to_decimal(impacted) if impacted is not None else None),
            unit_of_measure=getattr(data, "unit_of_measure", "") or "",
            labour_hours_lost=(_to_decimal(labour_hours) if labour_hours is not None else None),
        )
        claim = await self.disruption_repo.create(claim)
        # If status is submitted at creation, emit submitted event too.
        _safe_publish(
            "variations.disruption.submitted" if claim.status == "submitted" else "variations.disruption.created",
            {
                "project_id": str(data.project_id),
                "claim_id": str(claim.id),
                "cost_amount": str(claim.cost_amount),
                "currency": claim.currency,
            },
        )
        return claim

    async def get_disruption_claim(self, claim_id: uuid.UUID) -> DisruptionClaim:
        row = await self.disruption_repo.get_by_id(claim_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Disruption claim not found")
        return row

    async def update_disruption_claim(
        self,
        claim_id: uuid.UUID,
        data: DisruptionClaimUpdate,
    ) -> DisruptionClaim:
        claim = await self.get_disruption_claim(claim_id)
        fields = data.model_dump(exclude_unset=True)
        for money_key in ("cost_amount", "decided_amount"):
            if money_key in fields and fields[money_key] is not None:
                fields[money_key] = _to_decimal(fields[money_key])
        if not fields:
            return claim
        await self.disruption_repo.update_fields(claim_id, **fields)
        await self.session.refresh(claim)
        return claim

    async def transition_disruption(
        self,
        claim_id: uuid.UUID,
        to_status: str,
        decided_amount: Decimal | None = None,
    ) -> DisruptionClaim:
        claim = await self.get_disruption_claim(claim_id)
        if to_status not in allowed_disruption_transitions(claim.status):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Cannot transition disruption claim from {claim.status} to {to_status}",
            )
        fields: dict[str, Any] = {"status": to_status}
        if to_status in {"agreed", "rejected"}:
            fields["decision_at"] = _now_iso()
            if decided_amount is not None:
                fields["decided_amount"] = _to_decimal(decided_amount)
        await self.disruption_repo.update_fields(claim_id, **fields)
        await self.session.refresh(claim)
        if to_status == "submitted":
            _safe_publish(
                "variations.disruption.submitted",
                {"project_id": str(claim.project_id), "claim_id": str(claim_id)},
            )
        else:
            _safe_publish(
                f"variations.disruption.{to_status}",
                {"project_id": str(claim.project_id), "claim_id": str(claim_id)},
            )
        return claim

    async def delete_disruption_claim(self, claim_id: uuid.UUID) -> None:
        await self.get_disruption_claim(claim_id)
        await self.disruption_repo.delete(claim_id)

    # ── EOT claims ───────────────────────────────────────────────────────

    async def submit_eot_claim(
        self,
        data: ExtensionOfTimeClaimCreate,
        user_id: str | None = None,
    ) -> ExtensionOfTimeClaim:
        claim = ExtensionOfTimeClaim(
            project_id=data.project_id,
            raised_at=data.raised_at or _now_iso(),
            raised_by=data.raised_by or user_id,
            claim_period_start=data.claim_period_start,
            claim_period_end=data.claim_period_end,
            description=data.description,
            root_cause_category=data.root_cause_category,
            requested_days=data.requested_days,
            critical_path_impact=data.critical_path_impact,
            status=data.status,
            affected_activity_ref=getattr(data, "affected_activity_ref", "") or "",
        )
        claim = await self.eot_repo.create(claim)
        _safe_publish(
            "variations.eot.submitted" if claim.status == "submitted" else "variations.eot.created",
            {
                "project_id": str(data.project_id),
                "claim_id": str(claim.id),
                "requested_days": claim.requested_days,
                "critical_path_impact": claim.critical_path_impact,
            },
        )
        return claim

    async def get_eot_claim(self, claim_id: uuid.UUID) -> ExtensionOfTimeClaim:
        row = await self.eot_repo.get_by_id(claim_id)
        if row is None:
            raise HTTPException(status_code=404, detail="EOT claim not found")
        return row

    async def update_eot_claim(
        self,
        claim_id: uuid.UUID,
        data: ExtensionOfTimeClaimUpdate,
    ) -> ExtensionOfTimeClaim:
        claim = await self.get_eot_claim(claim_id)
        fields = data.model_dump(exclude_unset=True)
        if not fields:
            return claim
        await self.eot_repo.update_fields(claim_id, **fields)
        await self.session.refresh(claim)
        return claim

    async def transition_eot(
        self,
        claim_id: uuid.UUID,
        to_status: str,
        granted_days: int | None = None,
        decision_notes: str | None = None,
    ) -> ExtensionOfTimeClaim:
        claim = await self.get_eot_claim(claim_id)
        if to_status not in allowed_eot_transitions(claim.status):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Cannot transition EOT claim from {claim.status} to {to_status}",
            )
        fields: dict[str, Any] = {"status": to_status}
        if to_status in {"granted", "rejected"}:
            fields["decision_at"] = _now_iso()
            if decision_notes is not None:
                fields["decision_notes"] = decision_notes
        if to_status == "granted" and granted_days is not None:
            fields["granted_days"] = int(granted_days)
        await self.eot_repo.update_fields(claim_id, **fields)
        await self.session.refresh(claim)
        if to_status == "submitted":
            _safe_publish(
                "variations.eot.submitted",
                {"project_id": str(claim.project_id), "claim_id": str(claim_id)},
            )
        else:
            _safe_publish(
                f"variations.eot.{to_status}",
                {"project_id": str(claim.project_id), "claim_id": str(claim_id)},
            )
        return claim

    async def delete_eot_claim(self, claim_id: uuid.UUID) -> None:
        await self.get_eot_claim(claim_id)
        await self.eot_repo.delete(claim_id)

    async def record_eot_tia(
        self,
        claim_id: uuid.UUID,
        tia_delta_days: int,
        critical_path_impact: bool | None = None,
    ) -> ExtensionOfTimeClaim:
        """Stamp a Time-Impact-Analysis result onto an EoT claim.

        The TIA is computed by the schedule_advanced ``/tia`` endpoint;
        this method only records the result so the EoT-claim audit trail
        and decision sheet show the data point. ``critical_path_impact``
        is auto-set to True when ``tia_delta_days > 0`` if the caller
        doesn't override.
        """
        claim = await self.get_eot_claim(claim_id)
        cp_impact = critical_path_impact if critical_path_impact is not None else (tia_delta_days > 0)
        await self.eot_repo.update_fields(
            claim_id,
            tia_delta_days=int(tia_delta_days),
            tia_computed_at=_now_iso(),
            critical_path_impact=cp_impact,
        )
        await self.session.refresh(claim)
        _safe_publish(
            "variations.eot.tia_recorded",
            {
                "project_id": str(claim.project_id),
                "claim_id": str(claim_id),
                "tia_delta_days": int(tia_delta_days),
                "critical_path_impact": cp_impact,
            },
        )
        return claim

    # ── Final account ─────────────────────────────────────────────────────

    async def create_final_account(
        self,
        data: FinalAccountCreate,
    ) -> FinalAccount:
        existing = await self.final_account_repo.for_project(data.project_id)
        if existing is not None:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Final account already exists for this project",
            )
        fa = FinalAccount(
            project_id=data.project_id,
            original_contract_value=_to_decimal(data.original_contract_value),
            currency=data.currency,
            retention_held=_to_decimal(data.retention_held),
            retention_released=_to_decimal(data.retention_released),
            status=data.status,
        )
        # R5 audit: a concurrent insert on the same project would otherwise
        # surface as a raw IntegrityError (uq_oe_variations_final_account_
        # project) -> 500. Translate to 409 so the client gets an
        # actionable response.
        try:
            fa = await self.final_account_repo.create(fa)
        except Exception as exc:  # broad-catch: SQLA wraps dialect errors
            from sqlalchemy.exc import IntegrityError

            if isinstance(exc, IntegrityError):
                raise HTTPException(
                    status_code=http_status.HTTP_409_CONFLICT,
                    detail="Final account already exists for this project",
                ) from exc
            raise
        await self.recompute_final_account(data.project_id)
        return fa

    async def get_final_account(self, fa_id: uuid.UUID) -> FinalAccount:
        row = await self.final_account_repo.get_by_id(fa_id)
        if row is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.final_account_not_found", locale=get_locale())
            )
        return row

    async def update_final_account(
        self,
        fa_id: uuid.UUID,
        data: FinalAccountUpdate,
    ) -> FinalAccount:
        fa = await self.get_final_account(fa_id)
        fields = data.model_dump(exclude_unset=True)
        for money_key in (
            "original_contract_value",
            "variations_total",
            "daywork_total",
            "claims_total",
            "retention_held",
            "retention_released",
        ):
            if money_key in fields and fields[money_key] is not None:
                fields[money_key] = _to_decimal(fields[money_key])
        if not fields:
            return fa
        await self.final_account_repo.update_fields(fa_id, **fields)
        await self.session.refresh(fa)
        await self.recompute_final_account(fa.project_id)
        # Refresh once more to pick up the recomputed totals.
        await self.session.refresh(fa)
        return fa

    async def close_final_account(
        self,
        fa_id: uuid.UUID,
        signer_id: str | None = None,
    ) -> FinalAccount:
        fa = await self.get_final_account(fa_id)
        if "closed" not in allowed_final_account_transitions(fa.status):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Cannot close final account from status {fa.status}",
            )
        now = _now_iso()
        await self.final_account_repo.update_fields(
            fa_id,
            status="closed",
            closed_at=now,
        )
        await self.session.refresh(fa)
        _safe_publish(
            "variations.final_account.closed",
            {
                "project_id": str(fa.project_id),
                "final_account_id": str(fa_id),
                "final_value": str(fa.final_value),
                "currency": fa.currency,
                "signer_id": signer_id,
            },
        )
        return fa

    async def apply_variation_to_final_account(
        self,
        vo_id: uuid.UUID,
        final_account_id: uuid.UUID,
    ) -> FinalAccount:
        """Add the VO total to ``variations_total`` and recompute ``final_value``.

        R5 audit:
          * Cross-project IDOR - caller could supply a VO and a Final Account
            from two different projects and roll a sibling-project's VO into
            an unrelated final account. Verify both rows live in the same
            project before mutating anything.
          * Currency drift - adding a VO denominated in USD to an EUR final
            account silently overstates the number. Reject when the
            currencies disagree (operator must FX-normalise first).
        """
        vo = await self.get_order(vo_id)
        if vo.status == "voided":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="A voided variation order cannot be added to the final account",
            )
        fa = await self.get_final_account(final_account_id)
        if fa.project_id != vo.project_id:
            # IDOR guard - do not leak whether the FA exists; the caller
            # should never have asked.
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=translate("errors.final_account_not_found", locale=get_locale()),
            )
        vo_currency = (vo.currency or "").strip()
        fa_currency = (fa.currency or "").strip()
        if vo_currency and fa_currency and vo_currency != fa_currency:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=(
                    "Currency mismatch: VO is in "
                    f"{vo_currency}, final account is in {fa_currency}. "
                    "FX-normalise the VO before applying."
                ),
            )
        new_variations = _to_decimal(fa.variations_total) + _to_decimal(vo.final_cost_impact)
        new_final = (
            _to_decimal(fa.original_contract_value)
            + new_variations
            + _to_decimal(fa.daywork_total)
            + _to_decimal(fa.claims_total)
            - _to_decimal(fa.retention_held)
            + _to_decimal(fa.retention_released)
        )
        await self.final_account_repo.update_fields(
            final_account_id,
            variations_total=new_variations,
            final_value=new_final,
        )
        await self.session.refresh(fa)
        return fa

    async def recompute_final_account(self, project_id: uuid.UUID) -> FinalAccount | None:
        """Rebuild totals on the project's FinalAccount from all VOs/daywork/claims.

        R5 audit: currency-aware aggregation. A row whose currency does not
        match the final-account currency is **excluded** with a warning log
        - silently summing 100 EUR + 100 USD into "200" corrupts the
        forecast. Operator must FX-normalise the offending rows first.
        """
        fa = await self.final_account_repo.for_project(project_id)
        if fa is None:
            return None

        fa_currency = (fa.currency or "").strip()

        def _accept(row: Any) -> bool:
            """True when ``row.currency`` matches FA currency (or FA is blank)."""
            if not fa_currency:
                return True
            row_cur = (getattr(row, "currency", "") or "").strip()
            if not row_cur:
                # Best-effort: blank line-currency means "inherit" - accepted
                # to keep legacy roll-ups stable; new writes are normalised.
                return True
            if row_cur != fa_currency:
                logger.warning(
                    "variations.final_account.currency_skip",
                    extra={
                        "event": "variations.final_account.currency_skip",
                        "project_id": str(project_id),
                        "row_currency": row_cur,
                        "fa_currency": fa_currency,
                        "row_id": str(getattr(row, "id", "")),
                    },
                )
                return False
            return True

        # Voided VOs carry no commercial value - exclude them so the
        # revised contract sum is not overstated.
        vos = await self.vo_repo.list_valued_for_project(project_id)
        variations_total = sum(
            (_to_decimal(v.final_cost_impact) for v in vos if _accept(v)),
            Decimal("0"),
        )

        daywork_sheets = await self.daywork_repo.list_signed(project_id)
        daywork_total = sum(
            (_to_decimal(ds.total_amount) for ds in daywork_sheets if _accept(ds)),
            Decimal("0"),
        )

        # Only agreed claims count toward totals -- pending_claims excludes agreed,
        # so re-query agreed via a list-for-project filter.
        agreed_disruption, _ = await self.disruption_repo.list_for_project(
            project_id,
            limit=1000,
            status="agreed",
        )
        disruption_total = sum(
            (_to_decimal(c.decided_amount or c.cost_amount) for c in agreed_disruption if _accept(c)),
            Decimal("0"),
        )

        # EOT claims don't have a cost amount -- skip (EOT contributes time, not money).
        claims_total = disruption_total

        final_value = (
            _to_decimal(fa.original_contract_value)
            + variations_total
            + daywork_total
            + claims_total
            - _to_decimal(fa.retention_held)
            + _to_decimal(fa.retention_released)
        )

        await self.final_account_repo.update_fields(
            fa.id,
            variations_total=variations_total,
            daywork_total=daywork_total,
            claims_total=claims_total,
            final_value=final_value,
        )
        await self.session.refresh(fa)
        return fa

    # ── Project-scope resolvers (object-level authorization) ──────────────

    async def cost_impact_project_id(self, line_id: uuid.UUID) -> uuid.UUID:
        """Resolve the owning project for a cost-impact line (IDOR guard)."""
        row = await self.cost_impact_repo.get_by_id(line_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Cost-impact line not found")
        vo = await self.get_order(row.variation_order_id)
        return vo.project_id

    async def schedule_impact_project_id(self, line_id: uuid.UUID) -> uuid.UUID:
        """Resolve the owning project for a schedule-impact line (IDOR guard)."""
        row = await self.schedule_impact_repo.get_by_id(line_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Schedule-impact line not found",
            )
        vo = await self.get_order(row.variation_order_id)
        return vo.project_id

    async def daywork_line_project_id(self, line_id: uuid.UUID) -> uuid.UUID:
        """Resolve the owning project for a daywork line (IDOR guard)."""
        row = await self.daywork_line_repo.get_by_id(line_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Daywork line not found")
        sheet = await self.get_daywork_sheet(row.sheet_id)
        return sheet.project_id

    # ── Dashboard ────────────────────────────────────────────────────────

    async def get_dashboard(self, project_id: uuid.UUID) -> dict[str, Any]:
        # Status histograms via GROUP BY (no row materialisation / N+1).
        notice_counts = await self.notice_repo.status_counts(project_id)
        n_total = sum(notice_counts.values())
        notices_open = sum(c for s, c in notice_counts.items() if s in {"issued", "acknowledged", "responded"})

        vr_counts = await self.vr_repo.status_counts(project_id)
        vr_total = sum(vr_counts.values())
        vr_pending = sum(c for s, c in vr_counts.items() if s in {"draft", "submitted", "under_review"})
        vr_approved = vr_counts.get("approved", 0)
        vr_rejected = vr_counts.get("rejected", 0)

        vo_counts = await self.vo_repo.status_counts(project_id)
        vo_total = sum(vo_counts.values())
        vo_active = sum(c for s, c in vo_counts.items() if s in {"issued", "in_progress"})
        vo_completed = vo_counts.get("completed", 0)
        # Money / schedule roll-ups exclude voided VOs (no commercial value).
        cost_total = await self.vo_repo.cost_impact_sum(project_id)
        schedule_total = await self.vo_repo.schedule_days_sum(project_id)

        dw_counts = await self.daywork_repo.status_counts(project_id)
        dw_total = sum(dw_counts.values())
        dw_signed = sum(c for s, c in dw_counts.items() if s in {"signed", "billed"})
        dw_value = await self.daywork_repo.signed_value(project_id)

        # Currency bug fix: ``cost_total`` / ``dw_value`` above are scalar
        # SUMs that blend VOs / daywork sheets of different ISO currencies
        # into one number. Re-derive them per-currency and FX-convert to
        # the project BASE currency so the scalar totals are honest rather
        # than a meaningless mix. Falls back gracefully when the repos
        # don't expose the by-currency helpers (e.g. in-memory test stubs).
        project = await _load_project_currency_meta(self.session, project_id)
        base_code = ((getattr(project, "currency", "") if project is not None else "") or "").strip().upper()
        fx_map = _project_fx_map(project)
        cost_by_cur = await _safe_by_currency(self.vo_repo, "cost_impact_by_currency", project_id)
        dw_by_cur = await _safe_by_currency(self.daywork_repo, "signed_value_by_currency", project_id)  # noqa: E501
        # Only override the legacy scalar totals when the by-currency
        # breakdown is actually available (production repos). If a repo
        # doesn't expose the helper (in-memory test stubs return ``{}``),
        # keep the original ``cost_impact_sum`` / ``signed_value`` scalar
        # so we never replace a real figure with a spurious 0.
        cost_unconverted: dict[str, Decimal] = {}
        dw_unconverted: dict[str, Decimal] = {}
        if cost_by_cur:
            cost_total, cost_unconverted = _convert_money_buckets(cost_by_cur, base_code, fx_map)
        if dw_by_cur:
            dw_value, dw_unconverted = _convert_money_buckets(dw_by_cur, base_code, fx_map)
        # ``multi_currency`` = more than one DISTINCT non-blank currency
        # seen across either money stream.
        distinct_codes = {c for c in (*cost_by_cur.keys(), *dw_by_cur.keys()) if c}
        multi_currency = len(distinct_codes) > 1

        # R5 audit: COUNT-only - previous code materialised the full claim
        # rows just to read ``len(...)``. Fallback to ``len(pending_claims)``
        # so the unit-test in-memory stubs (which don't define
        # ``pending_count``) still work.
        if hasattr(self.disruption_repo, "pending_count"):
            disruption_open = await self.disruption_repo.pending_count(project_id)
        else:
            disruption_open = len(await self.disruption_repo.pending_claims(project_id))
        if hasattr(self.eot_repo, "pending_count"):
            eot_open = await self.eot_repo.pending_count(project_id)
        else:
            eot_open = len(await self.eot_repo.pending_claims(project_id))

        fa = await self.final_account_repo.for_project(project_id)
        fa_status = fa.status if fa is not None else "none"
        # Currency bug fix: the dashboard currency is now the project BASE
        # currency (the one the FX-converted scalar totals are expressed
        # in), NOT ``first_currency`` (the earliest-created row's currency,
        # which silently mis-labelled a blended sum). Fall back to the
        # earliest VO / daywork / final-account currency only when the
        # project carries no currency of its own.
        currency = base_code or (
            await self.vo_repo.first_currency(project_id)
            or await self.daywork_repo.first_currency(project_id)
            or (fa.currency if fa else "")
        )

        return {
            "project_id": project_id,
            "notices_total": n_total,
            "notices_open": notices_open,
            "requests_total": vr_total,
            "requests_pending": vr_pending,
            "requests_approved": vr_approved,
            "requests_rejected": vr_rejected,
            "variation_orders_total": vo_total,
            "variation_orders_active": vo_active,
            "variation_orders_completed": vo_completed,
            "cost_impact_total": cost_total,
            "schedule_impact_days": schedule_total,
            "daywork_sheets_total": dw_total,
            "daywork_sheets_signed": dw_signed,
            "daywork_value_signed": dw_value,
            "disruption_claims_open": disruption_open,
            "eot_claims_open": eot_open,
            "final_account_status": fa_status,
            "currency": currency,
            # Additive multi-currency disclosure (optional response fields).
            "cost_impact_by_currency": _money_str_map(cost_by_cur),
            "cost_impact_unconverted_by_currency": _money_str_map(cost_unconverted),
            "daywork_value_by_currency": _money_str_map(dw_by_cur),
            "daywork_value_unconverted_by_currency": _money_str_map(dw_unconverted),
            "multi_currency": multi_currency,
        }
