"""4D module services (Section 6).

This module hosts the four service classes the spec carves out for the 4D
slice: EAC link management, snapshot resolution, progress recording and
dashboard aggregation. Each class is a thin orchestration shell on top of
the existing schedule repository and the EAC engine's public API — the
heavy lifting (predicate evaluation) lives in :mod:`app.modules.eac.engine`
and is reached through :class:`EacPredicateResolver` so tests can stub it.

Design notes
------------
* Predicate evaluation is intentionally indirected via a protocol so unit
  tests don't need a populated BIM model. The default implementation lazy
  loads BIM elements for the requested model_version_id and walks them
  through the executor.
* Status derivation follows §6.2 / FR-6.5: ``not_started`` /
  ``in_progress`` / ``completed`` / ``delayed`` / ``ahead_of_schedule``.
* SPI/CPI use the standard EVM identities: SPI = EV / PV; CPI = EV / AC.
  When the schedule is not cost-loaded (no PV / AC) we return ``None``
  rather than 0 so the dashboard can render "not available" deterministically.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule.models import (
    EAC_LINK_MODES,
    Activity,
    EacScheduleLink,
    Schedule,
    ScheduleProgressEntry,
)

logger = logging.getLogger(__name__)


# ── Status constants (FR-6.5) ───────────────────────────────────────────
STATUS_NOT_STARTED = "not_started"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_DELAYED = "delayed"
STATUS_AHEAD = "ahead_of_schedule"

VALID_STATUSES: tuple[str, ...] = (
    STATUS_NOT_STARTED,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_DELAYED,
    STATUS_AHEAD,
)


# ── Predicate resolver protocol ─────────────────────────────────────────


class EacPredicateResolver(Protocol):
    """Resolves an EAC predicate / rule to a list of canonical element IDs.

    Production code passes :class:`DefaultEacResolver` which calls into the
    real EAC engine. Tests may inject a stub that returns deterministic IDs
    without needing a populated BIM model.
    """

    async def resolve(
        self,
        *,
        rule_id: uuid.UUID | None,
        predicate_json: dict | None,
        model_version_id: uuid.UUID | None,
    ) -> list[str]:
        """Return the list of element IDs matching the selector."""
        ...


class DefaultEacResolver:
    """Default resolver that delegates to the EAC engine.

    Element loading is delegated to a callback so the resolver remains
    decoupled from any specific BIM data source. If the callback returns an
    empty list (or raises) we fall back to a no-match outcome — the link is
    flagged as orphaned at the service layer (EC-6.1).
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID | None = None,
        element_loader: ElementLoader | None = None,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._element_loader = element_loader or _default_element_loader

    async def resolve(
        self,
        *,
        rule_id: uuid.UUID | None,
        predicate_json: dict | None,
        model_version_id: uuid.UUID | None,
    ) -> list[str]:
        """Load elements + execute the rule via the EAC engine."""
        try:
            elements = await self._element_loader(
                self._session, model_version_id=model_version_id
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "Element loader failed for model_version_id=%s", model_version_id
            )
            return []

        if not elements:
            return []

        # Resolve to a rule definition body — either the saved rule's
        # definition_json or the inline predicate_json.
        definition: dict
        if predicate_json is not None:
            definition = predicate_json
        elif rule_id is not None:
            from app.modules.eac.models import EacRule  # lazy import — avoid cycles

            rule = await self._session.get(EacRule, rule_id)
            if rule is None:
                return []
            definition = rule.definition_json or {}
        else:  # pragma: no cover - guarded at the model layer
            return []

        # Wrap any naked predicate in a minimal rule definition envelope.
        if "selector" not in definition and "predicate" not in definition:
            definition = {"output_mode": "boolean", "predicate": definition}

        try:
            from app.modules.eac.engine.runner import dry_run_rule

            result = await dry_run_rule(definition, elements, session=None)
        except Exception as exc:  # pragma: no cover - logged for ops
            logger.warning("EAC dry_run_rule failed: %s", exc)
            return []

        # ``ExecutionResult.elements`` is a list of ElementResult; matched
        # rows are ``passed=True``. ``element_id`` is the canonical id we
        # stored in ``elements[i]['stable_id']``.
        matched: list[str] = []
        for elem in getattr(result, "elements", []):
            if getattr(elem, "passed", False):
                eid = getattr(elem, "element_id", None)
                if eid:
                    matched.append(str(eid))
        return matched


class ElementLoader(Protocol):
    """Callback that supplies the list of canonical elements to evaluate."""

    async def __call__(
        self, session: AsyncSession, *, model_version_id: uuid.UUID | None
    ) -> list[dict]: ...


async def _default_element_loader(
    session: AsyncSession, *, model_version_id: uuid.UUID | None
) -> list[dict]:
    """Production element loader — pulls BIMElements for ``model_version_id``.

    The current bim_hub schema treats ``BIMModel.id`` as the model-version
    handle (one row per import). This loader queries every BIMElement that
    belongs to that model and projects it through ``bim_element_to_canonical``.

    If the bim_hub module isn't installed we return ``[]`` so the 4D slice
    works on test deployments without BIM data.
    """
    if model_version_id is None:
        return []
    try:
        from app.modules.bim_hub.models import BIMElement
        from app.modules.eac.engine.runner import bim_element_to_canonical
    except ImportError:
        return []

    stmt = select(BIMElement).where(BIMElement.model_id == model_version_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [bim_element_to_canonical(row) for row in rows]


# ── EAC link service ────────────────────────────────────────────────────


@dataclass
class DryRunResult:
    """Outcome of a link dry-run."""

    matched_element_ids: list[str]
    matched_count: int


class EacScheduleLinkService:
    """Orchestrates :class:`EacScheduleLink` lifecycle plus dry-run."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        resolver: EacPredicateResolver | None = None,
    ) -> None:
        self.session = session
        # Note: we resolve the resolver lazily so callers can inject a
        # different one per call (handy for tests). If none is given at
        # construction time we build the default lazily.
        self._resolver = resolver

    def _get_resolver(self) -> EacPredicateResolver:
        if self._resolver is None:
            self._resolver = DefaultEacResolver(self.session)
        return self._resolver

    async def dry_run(
        self,
        link: EacScheduleLink,
        model_version_id: uuid.UUID | None,
        *,
        resolver: EacPredicateResolver | None = None,
    ) -> DryRunResult:
        """Evaluate the link's selector and return matched element IDs."""
        active = resolver or self._get_resolver()
        ids = await active.resolve(
            rule_id=link.rule_id,
            predicate_json=link.predicate_json,
            model_version_id=model_version_id,
        )
        return DryRunResult(matched_element_ids=ids, matched_count=len(ids))

    async def create(
        self,
        *,
        task_id: uuid.UUID,
        rule_id: uuid.UUID | None,
        predicate_json: dict | None,
        mode: str = "partial_match",
        updated_by_user_id: uuid.UUID | None = None,
        model_version_id: uuid.UUID | None = None,
        resolver: EacPredicateResolver | None = None,
    ) -> tuple[EacScheduleLink, DryRunResult]:
        """Create a link, run a dry-run, persist the cached match count."""
        if mode not in EAC_LINK_MODES:
            raise ValueError(
                f"mode must be one of {EAC_LINK_MODES}, got {mode!r}"
            )
        if rule_id is None and predicate_json is None:
            raise ValueError(
                "either rule_id or predicate_json must be provided"
            )

        link = EacScheduleLink(
            task_id=task_id,
            rule_id=rule_id,
            predicate_json=predicate_json,
            mode=mode,
            updated_by_user_id=updated_by_user_id,
        )
        self.session.add(link)
        await self.session.flush()  # populate link.id

        outcome = await self.dry_run(link, model_version_id, resolver=resolver)
        link.matched_element_count = outcome.matched_count
        link.last_resolved_at = datetime.now(UTC)
        await self.session.flush()
        return link, outcome

    async def list_for_task(self, task_id: uuid.UUID) -> list[EacScheduleLink]:
        stmt = select(EacScheduleLink).where(EacScheduleLink.task_id == task_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, link_id: uuid.UUID) -> EacScheduleLink | None:
        return await self.session.get(EacScheduleLink, link_id)

    async def delete(self, link_id: uuid.UUID) -> None:
        link = await self.get(link_id)
        if link is not None:
            await self.session.delete(link)
            await self.session.flush()


# ── Snapshot service ────────────────────────────────────────────────────


def _parse_iso(value: str | None) -> date | None:
    """Parse an ISO ``YYYY-MM-DD`` (or full ISO datetime) string into a date."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _coerce_progress(activity: Activity) -> float:
    raw = activity.progress_pct or "0"
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _derive_task_status(
    activity: Activity,
    as_of: date,
) -> str:
    """Derive a 4D status for ``activity`` at ``as_of`` from dates + progress.

    Rules (FR-6.5):

    * ``progress_pct >= 100``: completed (or ``ahead_of_schedule`` if the task
      reached 100% earlier than its planned ``end_date``).
    * ``as_of < start_date``: ``not_started``.
    * ``as_of >= end_date`` and ``progress_pct < 100``: ``delayed``.
    * Otherwise: ``in_progress``.
    """
    progress = _coerce_progress(activity)
    start = _parse_iso(activity.start_date)
    end = _parse_iso(activity.end_date)

    # Completed already? Decide between completed vs ahead_of_schedule.
    if progress >= 100.0:
        # If the task hit 100% before the planned ``end_date`` (i.e. the
        # snapshot is taken before end_date), surface "ahead_of_schedule".
        if end is not None and as_of < end:
            return STATUS_AHEAD
        return STATUS_COMPLETED

    if start is None or end is None:
        # Defensive — without dates, base purely on progress.
        if progress > 0:
            return STATUS_IN_PROGRESS
        return STATUS_NOT_STARTED

    if as_of < start:
        return STATUS_NOT_STARTED
    if as_of >= end:
        # Past planned end with incomplete progress -> delayed.
        return STATUS_DELAYED
    return STATUS_IN_PROGRESS


class ScheduleSnapshotService:
    """Builds {element_id -> status} maps for a given as_of_date."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        resolver: EacPredicateResolver | None = None,
    ) -> None:
        self.session = session
        self._resolver = resolver

    def _get_resolver(self) -> EacPredicateResolver:
        if self._resolver is None:
            self._resolver = DefaultEacResolver(self.session)
        return self._resolver

    async def snapshot(
        self,
        schedule_id: uuid.UUID,
        as_of_date: date,
        model_version_id: uuid.UUID | None,
        *,
        resolver: EacPredicateResolver | None = None,
    ) -> dict[str, str]:
        """Return ``{element_id: status}`` for every linked element.

        When the same element is linked to multiple tasks (EC-6.2), the
        "worst" status wins (delayed > in_progress > not_started >
        ahead_of_schedule > completed). We pick this priority so the user is
        always alerted when ANY task touching the element is delayed.
        """
        active = resolver or self._get_resolver()

        # Load all activities for the schedule.
        stmt = select(Activity).where(Activity.schedule_id == schedule_id)
        activities = list((await self.session.execute(stmt)).scalars().all())
        if not activities:
            return {}

        activity_ids = [a.id for a in activities]
        activity_map = {a.id: a for a in activities}

        # Load all links for these tasks.
        link_stmt = select(EacScheduleLink).where(
            EacScheduleLink.task_id.in_(activity_ids)
        )
        links = list((await self.session.execute(link_stmt)).scalars().all())

        # Resolve each link once. We could cache by (rule_id, predicate_hash)
        # but the MVP doesn't need it.
        result: dict[str, str] = {}
        for link in links:
            if link.mode == "excluded":
                # Manual override — skip.
                continue
            activity = activity_map.get(link.task_id)
            if activity is None:
                continue
            status = _derive_task_status(activity, as_of_date)
            ids = await active.resolve(
                rule_id=link.rule_id,
                predicate_json=link.predicate_json,
                model_version_id=model_version_id,
            )
            for element_id in ids:
                existing = result.get(element_id)
                if existing is None or _status_priority(status) > _status_priority(
                    existing
                ):
                    result[element_id] = status
        return result


def _status_priority(status: str) -> int:
    """Higher number = "worse" / more urgent (FR-6.5 colour grade)."""
    return {
        STATUS_COMPLETED: 0,
        STATUS_AHEAD: 1,
        STATUS_NOT_STARTED: 2,
        STATUS_IN_PROGRESS: 3,
        STATUS_DELAYED: 4,
    }.get(status, 0)


# ── Progress service ────────────────────────────────────────────────────


class ScheduleProgressService:
    """Records progress entries and rolls them up onto the parent activity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        task_id: uuid.UUID,
        progress_percent: float,
        notes: str | None = None,
        photo_attachment_ids: list[str] | None = None,
        geolocation: dict | None = None,
        device: str = "desktop",
        recorded_by_user_id: uuid.UUID | None = None,
        actual_start_date: str | None = None,
        actual_finish_date: str | None = None,
    ) -> ScheduleProgressEntry:
        """Append a progress entry and update the parent activity's progress.

        Rolls forward (last-write-wins) — if a later entry has a *lower*
        progress percent the activity is still updated, so the user sees the
        most recent reading. The append-only entry log preserves the full
        history for audit / dashboard charts.
        """
        if progress_percent < 0.0 or progress_percent > 100.0:
            raise ValueError(
                f"progress_percent must be 0..100, got {progress_percent!r}"
            )

        activity = await self.session.get(Activity, task_id)
        if activity is None:
            raise LookupError(f"Activity {task_id} not found")

        entry = ScheduleProgressEntry(
            task_id=task_id,
            progress_percent=Decimal(str(progress_percent)),
            notes=notes,
            photo_attachment_ids=list(photo_attachment_ids or []),
            geolocation=geolocation,
            device=device,
            recorded_by_user_id=recorded_by_user_id,
            actual_start_date=actual_start_date,
            actual_finish_date=actual_finish_date,
        )
        self.session.add(entry)

        # Roll forward onto the activity.
        activity.progress_pct = str(progress_percent)
        if progress_percent >= 100.0:
            activity.status = STATUS_COMPLETED
        elif progress_percent > 0.0:
            activity.status = STATUS_IN_PROGRESS
        else:
            activity.status = STATUS_NOT_STARTED

        await self.session.flush()
        return entry

    async def history(self, task_id: uuid.UUID) -> list[ScheduleProgressEntry]:
        stmt = (
            select(ScheduleProgressEntry)
            .where(ScheduleProgressEntry.task_id == task_id)
            .order_by(ScheduleProgressEntry.recorded_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())


# ── Dashboard service ───────────────────────────────────────────────────


@dataclass
class SCurvePoint:
    """One point on the planned-vs-earned-vs-actual S-curve."""

    date: str
    planned_value: float
    earned_value: float
    actual_cost: float


@dataclass
class WBSBucket:
    """Aggregate progress + cost per WBS top-level bucket."""

    wbs_code: str
    activity_count: int = 0
    progress_percent: float = 0.0
    planned_value: float = 0.0
    earned_value: float = 0.0
    actual_cost: float = 0.0


@dataclass
class DashboardResult:
    """Container returned by :meth:`ScheduleDashboardService.dashboard`."""

    schedule_id: str
    as_of_date: str
    overall_progress_percent: float
    spi: float | None
    cpi: float | None
    s_curve_data: list[dict]
    by_wbs: dict[str, dict]
    activity_count: int
    has_cost_data: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "as_of_date": self.as_of_date,
            "overall_progress_percent": self.overall_progress_percent,
            "spi": self.spi,
            "cpi": self.cpi,
            "s_curve_data": list(self.s_curve_data),
            "by_wbs": dict(self.by_wbs),
            "activity_count": self.activity_count,
            "has_cost_data": self.has_cost_data,
        }


class ScheduleDashboardService:
    """Computes overall progress, SPI/CPI and an S-curve for a schedule."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def dashboard(
        self,
        schedule_id: uuid.UUID,
        as_of_date: date,
    ) -> DashboardResult:
        stmt = select(Activity).where(Activity.schedule_id == schedule_id)
        activities = list((await self.session.execute(stmt)).scalars().all())

        if not activities:
            return DashboardResult(
                schedule_id=str(schedule_id),
                as_of_date=as_of_date.isoformat(),
                overall_progress_percent=0.0,
                spi=None,
                cpi=None,
                s_curve_data=[],
                by_wbs={},
                activity_count=0,
                has_cost_data=False,
            )

        # ── Overall progress (duration-weighted average) ───────────────
        total_weight = 0.0
        weighted_progress = 0.0
        for a in activities:
            weight = max(int(a.duration_days or 0), 1)
            total_weight += weight
            weighted_progress += weight * _coerce_progress(a)
        overall = weighted_progress / total_weight if total_weight else 0.0

        # ── EVM totals ────────────────────────────────────────────────
        total_pv = 0.0
        total_ev = 0.0
        total_ac = 0.0
        any_cost = False
        for a in activities:
            pv = _decimal_to_float(a.cost_planned)
            ac = _decimal_to_float(a.cost_actual)
            if a.cost_planned is not None or a.cost_actual is not None:
                any_cost = True
            ev = pv * (_coerce_progress(a) / 100.0) if pv else 0.0
            total_pv += pv
            total_ev += ev
            total_ac += ac

        spi: float | None = None
        cpi: float | None = None
        if any_cost:
            spi = (total_ev / total_pv) if total_pv > 0 else None
            cpi = (total_ev / total_ac) if total_ac > 0 else None

        # ── S-curve (daily samples between project start and as_of) ───
        s_curve = self._build_s_curve(activities, as_of_date)

        # ── WBS breakdown (top-level wbs_code prefix) ─────────────────
        by_wbs: dict[str, WBSBucket] = {}
        for a in activities:
            bucket_key = (a.wbs_code or "").split(".")[0] or "_root"
            bucket = by_wbs.setdefault(bucket_key, WBSBucket(wbs_code=bucket_key))
            bucket.activity_count += 1
            bucket.planned_value += _decimal_to_float(a.cost_planned)
            bucket.actual_cost += _decimal_to_float(a.cost_actual)
            bucket.earned_value += _decimal_to_float(a.cost_planned) * (
                _coerce_progress(a) / 100.0
            )

        # Roll up progress per WBS as duration-weighted mean.
        wbs_weights: dict[str, float] = {}
        for a in activities:
            key = (a.wbs_code or "").split(".")[0] or "_root"
            weight = max(int(a.duration_days or 0), 1)
            wbs_weights[key] = wbs_weights.get(key, 0.0) + weight
        wbs_weighted_progress: dict[str, float] = {}
        for a in activities:
            key = (a.wbs_code or "").split(".")[0] or "_root"
            weight = max(int(a.duration_days or 0), 1)
            wbs_weighted_progress[key] = (
                wbs_weighted_progress.get(key, 0.0)
                + weight * _coerce_progress(a)
            )
        for key, bucket in by_wbs.items():
            w = wbs_weights.get(key, 0.0)
            bucket.progress_percent = (
                wbs_weighted_progress.get(key, 0.0) / w if w else 0.0
            )

        by_wbs_json = {
            k: {
                "wbs_code": v.wbs_code,
                "activity_count": v.activity_count,
                "progress_percent": v.progress_percent,
                "planned_value": v.planned_value,
                "earned_value": v.earned_value,
                "actual_cost": v.actual_cost,
            }
            for k, v in by_wbs.items()
        }

        return DashboardResult(
            schedule_id=str(schedule_id),
            as_of_date=as_of_date.isoformat(),
            overall_progress_percent=round(overall, 4),
            spi=round(spi, 4) if spi is not None else None,
            cpi=round(cpi, 4) if cpi is not None else None,
            s_curve_data=[
                {
                    "date": p.date,
                    "planned_value": p.planned_value,
                    "earned_value": p.earned_value,
                    "actual_cost": p.actual_cost,
                }
                for p in s_curve
            ],
            by_wbs=by_wbs_json,
            activity_count=len(activities),
            has_cost_data=any_cost,
        )

    def _build_s_curve(
        self, activities: list[Activity], as_of_date: date
    ) -> list[SCurvePoint]:
        """Build a daily-sampled S-curve from project start to ``as_of_date``.

        For each day we compute:

        * PV: cumulative planned value of every activity whose ``end_date``
          is on or before that day (i.e. should have been earned by then).
        * EV: cumulative earned value at that day, prorated linearly between
          start_date and end_date by current progress.
        * AC: assume actual cost accrues uniformly over [start, end] for the
          activity at its current progress percent (best the MVP can do
          without daily ``cost_actual`` history).

        At most ~93 points are emitted (3 month cap) so the response stays
        small. Granularity collapses to weekly when the span exceeds 90 days.
        """
        starts = [_parse_iso(a.start_date) for a in activities]
        ends = [_parse_iso(a.end_date) for a in activities]
        starts_real = [d for d in starts if d is not None]
        ends_real = [d for d in ends if d is not None]
        if not starts_real or not ends_real:
            return []
        project_start = min(starts_real)
        project_end = max(ends_real)
        end_for_curve = min(project_end, as_of_date)
        if end_for_curve < project_start:
            return []

        span_days = (end_for_curve - project_start).days
        # Choose a step so we emit at most ~90 points.
        step_days = 1
        if span_days > 90:
            step_days = max(span_days // 90, 1)

        points: list[SCurvePoint] = []
        cursor = project_start
        while cursor <= end_for_curve:
            pv = 0.0
            ev = 0.0
            ac = 0.0
            for a in activities:
                a_start = _parse_iso(a.start_date)
                a_end = _parse_iso(a.end_date)
                a_pv = _decimal_to_float(a.cost_planned)
                a_ac = _decimal_to_float(a.cost_actual)
                a_progress = _coerce_progress(a) / 100.0
                if a_start is None or a_end is None or a_pv == 0.0:
                    continue
                if cursor >= a_end:
                    pv += a_pv
                elif cursor >= a_start:
                    duration = max((a_end - a_start).days, 1)
                    elapsed = (cursor - a_start).days
                    pv += a_pv * (elapsed / duration)
                # EV / AC reflect the current progress reading prorated by
                # how far through the activity the cursor is. This is a
                # straight-line approximation (good enough for the MVP).
                if cursor >= a_start:
                    duration = max((a_end - a_start).days, 1)
                    elapsed = min((cursor - a_start).days, duration)
                    fraction = elapsed / duration
                    ev_now = a_pv * a_progress
                    ev += ev_now * fraction
                    ac += a_ac * fraction
            points.append(
                SCurvePoint(
                    date=cursor.isoformat(),
                    planned_value=round(pv, 4),
                    earned_value=round(ev, 4),
                    actual_cost=round(ac, 4),
                )
            )
            cursor += timedelta(days=step_days)
        return points


def _decimal_to_float(value: Decimal | None) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return 0.0


# ── CSV importer (FR-6.1 minimal slice) ─────────────────────────────────


@dataclass
class CsvImportResult:
    """Outcome of a CSV schedule import."""

    activities_created: int = 0
    activities_failed: int = 0
    warnings: list[str] = field(default_factory=list)
    activity_ids_by_wbs: dict[str, str] = field(default_factory=dict)


REQUIRED_CSV_COLUMNS = ("wbs_code", "name", "start", "end")


async def import_schedule_csv(
    session: AsyncSession,
    *,
    schedule_id: uuid.UUID,
    csv_text: str,
) -> CsvImportResult:
    """Parse ``csv_text`` and append :class:`Activity` rows to ``schedule_id``.

    The accepted shape is the universal one called out in §6.1: ``wbs_code,
    name, start, end, duration, predecessors, progress``. ``duration`` and
    ``progress`` are optional; when ``duration`` is missing it is computed
    from ``start..end``. ``predecessors`` is a semicolon-separated list of
    WBS codes; we resolve them to activity UUIDs after the first pass and
    materialise the dependency list as JSON on the activity.

    Returns a :class:`CsvImportResult` with counts + warnings instead of
    raising on partial failure — a single bad row should not abort the whole
    import (FR-6.1 / EC-6.3).
    """
    result = CsvImportResult()

    schedule = await session.get(Schedule, schedule_id)
    if schedule is None:
        raise LookupError(f"Schedule {schedule_id} not found")

    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise ValueError("CSV is empty or missing a header row")

    headers = [h.strip().lower() for h in reader.fieldnames]
    missing = [c for c in REQUIRED_CSV_COLUMNS if c not in headers]
    if missing:
        raise ValueError(
            f"CSV is missing required columns: {', '.join(missing)}"
        )

    # Two passes: first create activities, then resolve predecessor refs.
    pending_predecessors: list[tuple[uuid.UUID, str]] = []
    sort_order = 0
    for row_idx, raw_row in enumerate(reader, start=2):  # header is line 1
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw_row.items()}
        wbs = row.get("wbs_code", "")
        name = row.get("name", "")
        start = row.get("start", "")
        end = row.get("end", "")
        if not wbs or not name or not start or not end:
            result.activities_failed += 1
            result.warnings.append(
                f"row {row_idx}: missing required field — skipped"
            )
            continue
        try:
            start_d = _parse_iso(start)
            end_d = _parse_iso(end)
        except Exception:
            start_d = end_d = None
        if start_d is None or end_d is None:
            result.activities_failed += 1
            result.warnings.append(
                f"row {row_idx}: invalid ISO date — skipped"
            )
            continue
        duration_raw = row.get("duration") or row.get("duration_days") or ""
        try:
            duration = (
                int(duration_raw) if duration_raw else (end_d - start_d).days
            )
        except ValueError:
            duration = (end_d - start_d).days
        progress_raw = (
            row.get("progress")
            or row.get("progress_percent")
            or row.get("progress_pct")
            or "0"
        )
        try:
            progress = float(progress_raw)
        except ValueError:
            progress = 0.0
            result.warnings.append(
                f"row {row_idx}: invalid progress {progress_raw!r} — defaulted to 0"
            )

        activity = Activity(
            schedule_id=schedule_id,
            wbs_code=wbs,
            name=name[:255],
            description="",
            start_date=start_d.isoformat(),
            end_date=end_d.isoformat(),
            duration_days=max(duration, 0),
            progress_pct=str(progress),
            status=(
                STATUS_COMPLETED
                if progress >= 100
                else STATUS_IN_PROGRESS
                if progress > 0
                else STATUS_NOT_STARTED
            ),
            sort_order=sort_order,
        )
        sort_order += 1
        session.add(activity)
        await session.flush()
        result.activities_created += 1
        result.activity_ids_by_wbs[wbs] = str(activity.id)

        preds_raw = row.get("predecessors") or ""
        if preds_raw:
            for p in preds_raw.split(";"):
                p = p.strip()
                if p:
                    pending_predecessors.append((activity.id, p))

    # Resolve predecessors via WBS code → activity id map.
    if pending_predecessors:
        for activity_id, pred_wbs in pending_predecessors:
            pred_id = result.activity_ids_by_wbs.get(pred_wbs)
            if pred_id is None:
                result.warnings.append(
                    f"unknown predecessor wbs_code {pred_wbs!r}"
                )
                continue
            activity = await session.get(Activity, activity_id)
            if activity is None:  # pragma: no cover - defensive
                continue
            deps = list(activity.dependencies or [])
            deps.append(
                {"activity_id": pred_id, "type": "FS", "lag_days": 0}
            )
            activity.dependencies = deps

    await session.flush()
    return result


__all__ = [
    "STATUS_AHEAD",
    "STATUS_COMPLETED",
    "STATUS_DELAYED",
    "STATUS_IN_PROGRESS",
    "STATUS_NOT_STARTED",
    "VALID_STATUSES",
    "CsvImportResult",
    "DashboardResult",
    "DefaultEacResolver",
    "DryRunResult",
    "EacPredicateResolver",
    "EacScheduleLinkService",
    "ScheduleDashboardService",
    "ScheduleProgressService",
    "ScheduleSnapshotService",
    "import_schedule_csv",
]
