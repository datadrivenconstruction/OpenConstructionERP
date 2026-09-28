# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Field Time service - business logic for the foreman's field timesheet.

Stateless service layer over the pure engine
(:mod:`app.modules.field_time.field_time_math`). Responsibilities:

* Timesheet + line CRUD while the timesheet is still a draft.
* The lifecycle ``draft -> submitted -> approved``, with validation gating each
  forward step (a submit / approve is blocked when any ERROR-severity rule
  fails). Once approved a timesheet is immutable; the only correction is a
  reversing timesheet (the original flips to ``reversed`` and a new timesheet
  with ``reverses_id`` set nets it out - see :meth:`reverse_timesheet`).
* On approval, mirroring each daywork line onto a signed daywork sheet via the
  variations service, and publishing the hours / cost rollup so payroll and the
  cost / EVM model can reconcile against real booked time.

All money is ``Decimal`` and all cross-module reads are best-effort: a missing
optional collaborator degrades gracefully rather than failing the transition.
The service never commits - it flushes and lets the request-scoped session
commit, matching every peer module.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.json_merge import merge_metadata
from app.core.validation.engine import ValidationReport, validation_engine

# The offline idempotency ledger is shared field infrastructure, not the diary's
# private business: the diary declares it as "offline-replayed field writes" and
# keys it on nothing but the op id. Field time records its entries in the same
# table so one worker's replayed ops read as one list, which is why
# ``oe_field_diary`` is a declared dependency in this module's manifest.
from app.modules.field_diary.models import FieldSyncLedger
from app.modules.field_diary.repository import FieldSyncLedgerRepository
from app.modules.field_time import field_time_math as ft
from app.modules.field_time import working_time as wt
from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
from app.modules.field_time.repository import FieldTimeRepository
from app.modules.field_time.schemas import (
    OUTCOME_CREATED,
    OUTCOME_REPLAYED,
    OUTCOME_UPDATED,
    OUTCOME_WITHDRAWN,
    CostCodeSuggestionOut,
    FieldTimesheetCreate,
    FieldTimesheetLineCreate,
    FieldTimesheetLineUpdate,
    FieldTimesheetUpdate,
    OfflineEntrySubmission,
    OfflineEntryWithdraw,
)

if TYPE_CHECKING:
    from app.modules.field_time.schemas import ReverseTimesheetRequest

logger = logging.getLogger(__name__)

# The rule set the validation engine runs for a field timesheet.
_RULE_SET = "field_time"
# Variation-order statuses that count as "open" (still accepting daywork cost).
_OPEN_VARIATION_STATUSES = ("issued", "in_progress")
# Lifecycle statuses.
_DRAFT = "draft"
_SUBMITTED = "submitted"
_APPROVED = "approved"
_REVERSED = "reversed"

# How an offline field-time entry is filed in the shared field sync ledger. The
# op kind groups a worker's replayed ops beside the diary's; the result types
# say whether the key produced a timesheet or was withdrawn. A withdrawal keeps
# its row: it is the only thing that can stop a create which overtook it from
# resurrecting a day the foreman deleted.
_LEDGER_OP_KIND = "field.time.timesheet"
_LEDGER_RESULT_TIMESHEET = "field_timesheet"
_LEDGER_RESULT_WITHDRAWN = "field_timesheet_withdrawn"

# Why a pair of clock times cannot produce a duration, said in the words of the
# person who typed them. Keyed by the reason codes the pure engine returns.
_INTERVAL_MESSAGES: dict[str, str] = {
    ft.INTERVAL_TIMES_REQUIRED: (
        "A line records both clock times or neither. Add the missing one, or clear the one that is set "
        "and book the hours by hand."
    ),
    ft.INTERVAL_TIMEZONE_MISMATCH: (
        "The start and the end of this line are on different clocks: one carries a time zone and the "
        "other does not. Send both the same way."
    ),
    ft.INTERVAL_END_BEFORE_START: "This line ends before it starts. Check the two times.",
    ft.INTERVAL_ZERO_LENGTH: (
        "This line starts and ends at the same moment, so there is no working time to record. Give it an "
        "end, or remove the line."
    ),
    ft.INTERVAL_OVER_24H: (
        "One continuous shift longer than 24 hours is a data-entry error. Split it into the days it "
        "was actually worked on."
    ),
    ft.INTERVAL_BREAK_NEGATIVE: "A break cannot be a negative number of minutes.",
    ft.INTERVAL_BREAK_EXCEEDS_SHIFT: (
        "The break is as long as the shift, or longer, so nothing is left to record as working time. "
        "Check the break and the two times."
    ),
}
_INTERVAL_FALLBACK = "The start time, the end time and the break on this line do not make a working period."


def _offline_scope_error() -> HTTPException:
    """The refusal for an entry key that is not this project's to touch.

    404 rather than 403, matching every other read in this module: a caller who
    may not see the entry must not learn from the answer that it exists.
    """
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No offline entry with that key on this project.",
    )


@dataclass(frozen=True)
class OfflineOpOutcome:
    """What one offline op did, for the router to render.

    Attributes:
        timesheet: The entry as it now stands, or None once withdrawn.
        outcome: One of the ``OUTCOME_*`` tokens. The client renders its own
            localized sentence from this and never parses ``detail``.
        submitted: True when the entry has moved past draft, so the office can
            see it. False with a stored draft means it still needs a correction.
        detail: English technical note for a log, or None.
    """

    timesheet: FieldTimesheet | None
    outcome: str
    submitted: bool = False
    detail: str | None = None


def _utcnow() -> datetime:
    """Return a timezone-aware UTC now."""
    return datetime.now(UTC)


def _instant_key(value: object) -> str:
    """A comparable spelling of an instant, empty when there is none.

    Normalised to UTC first. A device an hour east sends the same moment as
    ``09:00+02:00`` that the column reads back as ``07:00+00:00``, and comparing
    the two spellings would call a redelivery an edit.
    """
    if not isinstance(value, datetime):
        return ""
    return (value.astimezone(UTC) if value.tzinfo is not None else value).isoformat()


def _as_uuid(value: object) -> uuid.UUID | None:
    """Best-effort coerce to UUID, else None."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


class FieldTimeService:
    """Business logic for field timesheets."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = FieldTimeRepository(session)

    # ── Create ───────────────────────────────────────────────────────────────

    async def create_timesheet(
        self,
        data: FieldTimesheetCreate,
        user_id: str | None = None,
    ) -> FieldTimesheet:
        """Create a new draft timesheet, optionally with its lines."""
        for line in data.lines:
            self._assert_line_xor(line.resource_id, line.equipment_id)

        reference = await self.repo.next_reference(data.project_id)
        # Record who drafted the timesheet in metadata (the model tracks the
        # submitter / approver as columns, but not the original drafter).
        metadata = dict(data.metadata or {})
        if user_id:
            metadata.setdefault("created_by", str(user_id))
        timesheet = FieldTimesheet(
            project_id=data.project_id,
            reference=reference,
            date=data.date,
            status=_DRAFT,
            note=data.note,
            working_time_regime=data.working_time_regime,
            metadata_=metadata,
        )
        timesheet = await self.repo.create(timesheet)
        for line in data.lines:
            await self.repo.add_line(self._line_from_create(timesheet.id, line))

        await self.session.refresh(timesheet)
        logger.info(
            "Field timesheet created: %s (%s) for project %s with %d line(s)",
            reference,
            timesheet.date,
            data.project_id,
            len(data.lines),
        )
        return timesheet

    # ── Read ─────────────────────────────────────────────────────────────────

    async def get_timesheet(self, timesheet_id: uuid.UUID) -> FieldTimesheet:
        """Get a timesheet by id (404 if missing)."""
        timesheet = await self.repo.get_by_id(timesheet_id)
        if timesheet is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This field timesheet does not exist or has been removed. Refresh the list and try again.",
            )
        return timesheet

    async def list_timesheets(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        date_from: date | None = None,
        date_to: date | None = None,
        status_filter: str | None = None,
    ) -> tuple[list[FieldTimesheet], int]:
        """List timesheets for a project."""
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            date_from=date_from,
            date_to=date_to,
            status=status_filter,
        )

    async def get_summary(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Project rollup: counts by status plus labour / plant / overtime hours.

        The hour totals count only live approved timesheets (an approved sheet
        that has not been reversed). Each timesheet's own timekeeping rules from
        its metadata are honoured: hours are rounded to the project step if one
        is set, and overtime is the sum, per worker per day, of hours above the
        project's daily threshold (zero when no threshold is configured).
        """
        counts = await self.repo.status_counts(project_id)
        # Hours over live (approved, non-reversal) timesheets - the authoritative
        # actuals a manager cares about at a glance.
        timesheets, _total = await self.repo.list_for_project(project_id, limit=100000)
        labour = Decimal("0")
        plant = Decimal("0")
        overtime = Decimal("0")
        for ts in timesheets:
            if ts.status != _APPROVED or ts.reverses_id is not None:
                continue
            config = ft.read_hours_config(getattr(ts, "metadata_", None))
            lines = self._line_dicts(ts)
            roll = ft.rollup(lines, rounding_increment=config.rounding_increment)
            labour += roll.labour_hours
            plant += roll.plant_hours
            if config.overtime_daily_threshold is not None:
                overtime += ft.daily_overtime(lines, daily_threshold=config.overtime_daily_threshold)
        return {
            "total": sum(counts.values()),
            "by_status": counts,
            "labour_hours": ft.quantize_hours(labour),
            "plant_hours": ft.quantize_hours(plant),
            "overtime_hours": ft.quantize_hours(overtime),
        }

    # ── Statutory working-time record ────────────────────────────────────────

    async def working_time_record(
        self,
        project_id: uuid.UUID,
        *,
        date_from: date,
        date_to: date,
        regime_code: str | None = None,
        today: date | None = None,
    ) -> dict[str, Any]:
        """The working-time record for a project over a period, as an audit asks for it.

        A customs inspection asks one question: for this site, over these dates,
        which people worked, and when did each of them start and stop on each
        day. That is a worker-day, so this folds the period's timesheet lines
        into worker-days: earliest start, latest end, total unpaid break, total
        hours, and how many of the bookings behind them carry no clock times at
        all. Plant is left out; a machine has no working time to record.

        Reversed timesheets and the reversals that netted them out are left out
        of the fold, so a corrected day is not counted twice, and counted in
        ``excluded_corrections`` so nobody has to guess why the total moved.

        The regime is the one asked for, or failing that the first one the
        period's own timesheets carry. With no regime anywhere, the record is
        still produced - it simply says nothing about deadlines or retention,
        because no rule was chosen to say it under.

        Args:
            project_id: The project the record is for.
            date_from: First day of the period, inclusive.
            date_to: Last day of the period, inclusive.
            regime_code: Force a regime rather than reading it off the data.
            today: The day the retention window is judged on (defaults to now).

        Returns:
            A dict the router renders as a :class:`WorkingTimeRecordOut`.
        """
        timesheets, _total = await self.repo.list_for_project(
            project_id,
            limit=100000,
            date_from=date_from,
            date_to=date_to,
        )
        live: list[FieldTimesheet] = []
        excluded = 0
        for sheet in timesheets:
            if sheet.status == _REVERSED or sheet.reverses_id is not None:
                excluded += 1
                continue
            live.append(sheet)

        spec = wt.regime_for(regime_code)
        if spec is None:
            for sheet in sorted(live, key=lambda s: s.date):
                spec = wt.regime_for(sheet.working_time_regime)
                if spec is not None:
                    break

        entries: list[dict[str, Any]] = []
        for sheet in live:
            for line in sheet.lines:
                if line.resource_id is None:
                    continue
                entries.append(
                    {
                        "work_date": sheet.date,
                        "resource_id": str(line.resource_id),
                        "employer_kind": line.employer_kind or "",
                        "employer_subcontractor_id": (
                            str(line.employer_subcontractor_id) if line.employer_subcontractor_id else None
                        ),
                        "started_at": line.started_at,
                        "ended_at": line.ended_at,
                        "break_minutes": line.break_minutes,
                        # The hours as stored, which for a timed line are the
                        # hours its times produced. Deliberately not put through
                        # the project's rounding step the way the timesheet
                        # header rollup is: a duration rounded to a quarter hour
                        # no longer equals end minus start minus break, and this
                        # is the one place where it has to.
                        "hours": line.hours,
                        "reference": sheet.reference or "",
                        "status": sheet.status,
                        "recorded_at": sheet.created_at,
                    },
                )

        days = wt.worker_day_records(entries)
        worker_names = await self._worker_names({d.resource_id for d in days})
        employer_names = await self._employer_names({d.employer_id for d in days if d.employer_id})
        as_of = today or _utcnow().date()

        rows: list[dict[str, Any]] = []
        total_hours = Decimal("0")
        late_days = 0
        missing_times = 0
        for day in days:
            stamp = wt.timeliness(day.work_date, day.recorded_at, spec) if spec is not None else None
            total_hours += day.duration_hours
            if stamp is not None and stamp.late:
                late_days += 1
            if day.segments_without_times:
                missing_times += 1
            rows.append(
                {
                    "date": day.work_date,
                    "resource_id": _as_uuid(day.resource_id),
                    "worker": worker_names.get(day.resource_id, "") or day.resource_id,
                    "employer_kind": day.employer_kind,
                    "employer_subcontractor_id": _as_uuid(day.employer_id) if day.employer_id else None,
                    "employer": (employer_names.get(day.employer_id, "") or day.employer_id or "")
                    if day.employer_id
                    else "",
                    "started_at": day.started_at,
                    "ended_at": day.ended_at,
                    "break_minutes": day.break_minutes,
                    "duration_hours": format(day.duration_hours, "f"),
                    "segments": day.segments,
                    "segments_without_times": day.segments_without_times,
                    "references": list(day.references),
                    "status": day.status,
                    "recorded_at": day.recorded_at,
                    "days_taken": stamp.days_taken if stamp is not None else None,
                    "late": bool(stamp is not None and stamp.late),
                    "deadline": stamp.deadline if stamp is not None else None,
                    "retain_until": stamp.retain_until if stamp is not None else None,
                    "within_retention": (wt.within_retention(day.work_date, spec, as_of) if spec is not None else True),
                },
            )

        return {
            "project_id": project_id,
            "date_from": date_from,
            "date_to": date_to,
            "regime": spec.code if spec is not None else None,
            "provision": spec.provision if spec is not None else "",
            "generated_at": _utcnow(),
            "days": rows,
            "workers": len({row["resource_id"] for row in rows}),
            "total_hours": format(ft.quantize_hours(total_hours), "f"),
            "late_days": late_days,
            "days_missing_times": missing_times,
            "excluded_corrections": excluded,
        }

    async def _worker_names(self, resource_ids: set[str]) -> dict[str, str]:
        """Best-effort ``{resource_id: name}`` from the resources register."""
        ids = [i for i in (_as_uuid(r) for r in resource_ids) if i is not None]
        if not ids:
            return {}
        try:
            from sqlalchemy import select

            from app.modules.resources.models import Resource

            rows = (await self.session.execute(select(Resource.id, Resource.name).where(Resource.id.in_(ids)))).all()
        except Exception:
            logger.debug("Worker-name lookup unavailable")
            return {}
        return {str(rid): str(name or "") for rid, name in rows}

    async def _employer_names(self, subcontractor_ids: set[str]) -> dict[str, str]:
        """Best-effort ``{subcontractor_id: legal name}`` from the subcontractor register.

        The legal name, not the trading one: a record kept for an inspection has
        to name the firm that owes the wage. An id that no longer resolves is
        left to the caller to print as an id, which is a gap somebody can see
        rather than an empty cell that reads like "own staff".
        """
        ids = [i for i in (_as_uuid(s) for s in subcontractor_ids) if i is not None]
        if not ids:
            return {}
        try:
            from sqlalchemy import select

            from app.modules.subcontractors.models import Subcontractor

            rows = (
                await self.session.execute(
                    select(Subcontractor.id, Subcontractor.legal_name).where(Subcontractor.id.in_(ids)),
                )
            ).all()
        except Exception:
            logger.debug("Employer-name lookup unavailable")
            return {}
        return {str(sid): str(name or "") for sid, name in rows}

    # ── Update (draft only) ──────────────────────────────────────────────────

    async def update_timesheet(
        self,
        timesheet_id: uuid.UUID,
        data: FieldTimesheetUpdate,
    ) -> FieldTimesheet:
        """Update a draft timesheet's header fields."""
        timesheet = await self.get_timesheet(timesheet_id)
        self._assert_draft(timesheet, "edit")

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(timesheet, "metadata_", None), incoming)
                if isinstance(incoming, dict)
                else incoming
            )
        if not fields:
            return timesheet

        await self.repo.update_fields(timesheet_id, **fields)
        await self.session.refresh(timesheet)
        return timesheet

    async def add_line(
        self,
        timesheet_id: uuid.UUID,
        data: FieldTimesheetLineCreate,
    ) -> FieldTimesheet:
        """Add a line to a draft timesheet."""
        timesheet = await self.get_timesheet(timesheet_id)
        self._assert_draft(timesheet, "add a line to")
        self._assert_line_xor(data.resource_id, data.equipment_id)
        await self.repo.add_line(self._line_from_create(timesheet_id, data))
        await self.session.refresh(timesheet)
        return timesheet

    async def update_line(
        self,
        timesheet_id: uuid.UUID,
        line_id: uuid.UUID,
        data: FieldTimesheetLineUpdate,
    ) -> FieldTimesheet:
        """Update a single line on a draft timesheet."""
        timesheet = await self.get_timesheet(timesheet_id)
        self._assert_draft(timesheet, "edit a line of")
        line = await self.repo.get_line(line_id)
        if line is None or line.timesheet_id != timesheet_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="That line is not part of this timesheet. Reload the timesheet and try again.",
            )

        fields = data.model_dump(exclude_unset=True)
        # Resolve the post-update identifiers to enforce labour XOR plant.
        new_resource = fields.get("resource_id", line.resource_id)
        new_equipment = fields.get("equipment_id", line.equipment_id)
        self._assert_line_xor(new_resource, new_equipment)
        if not fields:
            return timesheet

        # Re-derive the hours from the line as it will stand, so a patch that
        # moves a clock time moves the duration with it and a patch that types a
        # number over a timed line is overruled by the times rather than stored
        # beside them. Untouched on a patch that mentions neither.
        if {"started_at", "ended_at", "break_minutes", "hours"} & set(fields):
            fields["hours"] = self._derive_hours(
                fields.get("started_at", line.started_at),
                fields.get("ended_at", line.ended_at),
                fields.get("break_minutes", line.break_minutes),
                fields.get("hours", line.hours),
            )

        await self.repo.update_line_fields(line_id, **fields)
        await self.session.refresh(timesheet)
        return timesheet

    async def delete_line(self, timesheet_id: uuid.UUID, line_id: uuid.UUID) -> FieldTimesheet:
        """Delete a line from a draft timesheet."""
        timesheet = await self.get_timesheet(timesheet_id)
        self._assert_draft(timesheet, "remove a line from")
        line = await self.repo.get_line(line_id)
        if line is None or line.timesheet_id != timesheet_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="That line is not part of this timesheet. Reload the timesheet and try again.",
            )
        await self.repo.delete_line(line_id)
        await self.session.refresh(timesheet)
        return timesheet

    # ── Delete (draft only) ──────────────────────────────────────────────────

    async def delete_timesheet(self, timesheet_id: uuid.UUID) -> None:
        """Delete a draft timesheet. Submitted / approved sheets cannot be deleted."""
        timesheet = await self.get_timesheet(timesheet_id)
        self._assert_draft(timesheet, "delete")
        await self.repo.delete(timesheet_id)
        logger.info("Field timesheet deleted: %s", timesheet_id)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def submit_timesheet(self, timesheet_id: uuid.UUID, user_id: str | None) -> FieldTimesheet:
        """Submit a draft timesheet for approval (draft -> submitted).

        Blocked (HTTP 422) when any ERROR-severity validation rule fails.
        """
        timesheet = await self.get_timesheet(timesheet_id)
        if timesheet.status != _DRAFT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"This timesheet is already '{timesheet.status}', so it cannot be submitted again. "
                    "Only a draft can be sent for approval."
                ),
            )
        if not timesheet.lines:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Add at least one hours line before submitting. An empty timesheet cannot be sent for approval.",
            )
        await self._validate_or_raise(timesheet, operation="submit")

        await self.repo.update_fields(
            timesheet_id,
            status=_SUBMITTED,
            submitted_by=_as_uuid(user_id),
            submitted_at=_utcnow(),
        )
        await self.session.refresh(timesheet)
        self._publish_submitted(timesheet, user_id)
        logger.info("Field timesheet submitted: %s", timesheet_id)
        return timesheet

    async def approve_timesheet(self, timesheet_id: uuid.UUID, user_id: str | None) -> FieldTimesheet:
        """Approve a submitted timesheet (submitted -> approved).

        On approval the hours become authoritative actuals: the cost rollup is
        computed, each daywork line is mirrored onto a signed daywork sheet,
        ``field_time.timesheet_approved`` is published for payroll, and the
        labour rows go to the cost model as ``fieldreports.labour.logged`` -
        the same pipe the field diary uses, so a day recorded both on a phone
        and here reaches the budget once.
        """
        timesheet = await self.get_timesheet(timesheet_id)
        if timesheet.status != _SUBMITTED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"This timesheet is '{timesheet.status}'. Only a submitted timesheet can be approved. "
                    "Submit it for approval first."
                ),
            )
        await self._validate_or_raise(timesheet, operation="approve")

        line_dicts = self._line_dicts(timesheet)
        labour_rates = await self._labour_rates(line_dicts)
        plant_rates = await self._plant_rates(line_dicts, timesheet.project_id)
        currency = await self._project_base_currency(timesheet.project_id)

        # Mirror daywork lines onto signed daywork sheets (best-effort - the
        # hours actuals must post even if the daywork write-through hiccups).
        await self._write_through_daywork(timesheet, labour_rates, plant_rates, currency, user_id)

        await self.repo.update_fields(
            timesheet_id,
            status=_APPROVED,
            approved_by=_as_uuid(user_id),
            approved_at=_utcnow(),
        )
        await self.session.refresh(timesheet)
        await self._audit(timesheet, prior=_SUBMITTED, new=_APPROVED, user_id=user_id)

        roll = ft.rollup(line_dicts, labour_rates=labour_rates, plant_rates=plant_rates)
        self._publish_approved(timesheet, roll, currency, user_id)
        self._publish_labour_actuals(timesheet, line_dicts, labour_rates, currency, user_id)
        logger.info("Field timesheet approved: %s by %s", timesheet_id, user_id)
        return timesheet

    async def reverse_timesheet(
        self,
        timesheet_id: uuid.UUID,
        data: ReverseTimesheetRequest,
        user_id: str | None,
    ) -> FieldTimesheet:
        """Reverse an approved timesheet with a mirrored, netting timesheet.

        Approved timesheets are immutable. To correct them a reversing timesheet
        is created (its hours net the original to zero for cost / payroll) and the
        original flips to ``reversed``. Returns the new reversal timesheet.
        """
        original = await self.get_timesheet(timesheet_id)
        if original.status != _APPROVED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Only an approved timesheet can be reversed. This one is '{original.status}', "
                    "so there are no approved hours to undo."
                ),
            )

        mirrored = ft.reverse_lines(self._line_dicts(original))
        reference = await self.repo.next_reference(original.project_id)
        now = _utcnow()
        actor = _as_uuid(user_id)
        reversal = FieldTimesheet(
            project_id=original.project_id,
            reference=reference,
            date=original.date,
            status=_APPROVED,
            reverses_id=original.id,
            note=data.note,
            submitted_by=actor,
            submitted_at=now,
            approved_by=actor,
            approved_at=now,
            metadata_={"reverses": str(original.id), "reverses_reference": original.reference},
        )
        reversal = await self.repo.create(reversal)
        for line in mirrored:
            await self.repo.add_line(
                FieldTimesheetLine(
                    timesheet_id=reversal.id,
                    resource_id=_as_uuid(line.get("resource_id")),
                    equipment_id=_as_uuid(line.get("equipment_id")),
                    hours=ft.to_decimal(line.get("hours")),
                    cost_code=str(line.get("cost_code") or ""),
                    wbs=line.get("wbs"),
                    # Carried onto the reversal deliberately, so the mirror
                    # is a faithful negative of what it corrects on this axis
                    # too. Consumers net a corrected day in one of two ways:
                    # by dropping both sheets (which is what
                    # ``costmodel.position_actuals`` does), or by summing
                    # signed contributions the way ``ft.net_hours`` does. The
                    # second one needs the position on BOTH halves or the
                    # credit lands nowhere and the original hours stand against
                    # the position for ever.
                    boq_position_id=_as_uuid(line.get("boq_position_id")),
                    is_daywork=bool(line.get("is_daywork")),
                    variation_id=_as_uuid(line.get("variation_id")),
                    note=line.get("note"),
                ),
            )

        await self.repo.update_fields(timesheet_id, status=_REVERSED)
        await self.session.refresh(reversal)
        await self._audit(original, prior=_APPROVED, new=_REVERSED, user_id=user_id)

        roll = ft.rollup(self._line_dicts(reversal))
        self._publish_reversed(reversal, original, roll, user_id)
        # Rates only matter to a cost model that has no record of what the
        # approval posted; when it has one it credits that figure instead.
        labour_rates = await self._labour_rates(mirrored)
        currency = await self._project_base_currency(original.project_id)
        self._publish_labour_credit(reversal, original, mirrored, labour_rates, currency, user_id)
        logger.info("Field timesheet %s reversed by %s (reversal=%s)", timesheet_id, user_id, reversal.id)
        return reversal

    # ── Offline capture and replay ───────────────────────────────────────────

    async def record_offline_entry(
        self,
        data: OfflineEntrySubmission,
        user_id: str | None,
    ) -> OfflineOpOutcome:
        """Apply one day recorded offline, exactly once however often it arrives.

        The device queues the day and replays it when there is signal again. That
        replay is at-least-once - a reconnect that fires twice, or a request that
        reached the server but whose response was lost, both re-send it - so the
        entry key is looked up first and a known key returns what it produced the
        first time instead of writing a second timesheet.

        The op carries the entry's whole state, not a diff. Re-applying a whole
        state is idempotent by construction, which is why a replayed update needs
        no revision counter to be safe: applying the same content twice leaves
        the same content.

        Replay cannot move money or claim a worker-day, because this path only
        ever produces a draft or a submitted timesheet. Approval is what posts
        labour actuals and takes the ``(project, day, worker)`` claim, and
        approval stays a deliberate desk action - nothing subscribes to
        ``field_time.timesheet_submitted`` and does anything durable. Anyone
        adding a submit-time subscriber that posts cost breaks that guarantee and
        has to re-read this method.

        Args:
            data: The entry's full state, keyed by ``entry_key``.
            user_id: The authenticated caller, recorded against the ledger row.

        Returns:
            An :class:`OfflineOpOutcome` naming what happened and the entry.

        Raises:
            HTTPException: 409 when the entry was withdrawn (a create that
                overtook its own withdrawal must not resurrect the day), when an
                edit arrives for a day that is no longer a draft, or when the key
                is already spent on another module's op; 404 when the key belongs
                to a different project.
        """
        for line in data.lines:
            self._assert_line_xor(line.resource_id, line.equipment_id)

        ledger_repo = FieldSyncLedgerRepository(self.session)
        ledger = await ledger_repo.get_by_client_op_id(data.entry_key)
        if ledger is not None:
            self._assert_offline_key_is_ours(data.entry_key, ledger, data.project_id)

        if ledger is not None and ledger.result_type == _LEDGER_RESULT_WITHDRAWN:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This day was withdrawn on the device, so it was not recorded again. "
                    "Enter it as a new day if the hours were real."
                ),
            )

        existing: FieldTimesheet | None = None
        if ledger is not None and ledger.result_id is not None:
            existing = await self.repo.get_by_id(ledger.result_id)

        if existing is not None:
            if existing.project_id != data.project_id:
                # The ledger row and the timesheet are two separate records.
                # That they agreed when they were written is not proof they
                # agree now, and this one rewrites lines, so check the row it
                # actually resolved rather than trusting the key that found it.
                raise _offline_scope_error()
            return await self._apply_offline_revision(existing, data, user_id)

        # No entry behind this key yet. Either it is genuinely new, or a previous
        # attempt claimed the key and never got as far as writing the timesheet
        # (it crashed, or its transaction rolled back). Both want the same thing:
        # write the day and point the key at it. Self-healing on purpose - a key
        # that could be poisoned by one failed attempt would lose the day for
        # good, since the device will only ever send that same key.
        timesheet = await self.create_timesheet(
            FieldTimesheetCreate(
                project_id=data.project_id,
                date=data.date,
                note=data.note,
                metadata={**dict(data.metadata or {}), ft.OFFLINE_METADATA_KEY: self._offline_record(data)},
                lines=list(data.lines),
            ),
            user_id=user_id,
        )
        await self._record_offline_key(
            data.entry_key,
            project_id=data.project_id,
            user_id=user_id,
            timesheet_id=timesheet.id,
            existing=ledger,
        )
        timesheet, submitted, detail = await self._offline_submit(timesheet, data, user_id)
        logger.info(
            "Field timesheet %s recorded from an offline entry (key=%s)",
            timesheet.id,
            data.entry_key,
        )
        return OfflineOpOutcome(timesheet, OUTCOME_CREATED, submitted=submitted, detail=detail)

    async def withdraw_offline_entry(
        self,
        data: OfflineEntryWithdraw,
        user_id: str | None,
    ) -> OfflineOpOutcome:
        """Withdraw a day recorded offline, by the key the device gave it.

        Remembering the withdrawal is the whole point. A device that queued a
        create and then a withdrawal can deliver them in either order once the
        two requests are in flight, and a withdrawal that arrives first must stop
        the create behind it - otherwise the day the foreman deleted comes back
        and nobody can tell it was ever meant to be gone. So an unknown key is
        recorded as withdrawn rather than answered with "no such entry".

        Only a draft can be withdrawn. Refusing everything else is what keeps a
        worker-day claim from being stranded: approving a timesheet posts labour
        actuals and claims each ``(project, day, worker)``, the claim is released
        by reversing the timesheet, and there is no foreign key tying the claim
        to the row. Deleting an approved timesheet here would leave a claim that
        nothing can ever release, so that day could never be costed again - not
        by a corrected sheet and not by the phone.

        Args:
            data: The entry key and its project.
            user_id: The authenticated caller, recorded against the ledger row.

        Returns:
            An :class:`OfflineOpOutcome` with ``OUTCOME_WITHDRAWN`` and no
            timesheet.

        Raises:
            HTTPException: 409 when the entry has already been sent on for
                approval or approved, or when the key is already spent on
                another module's op; 404 when the key belongs to a different
                project.
        """
        ledger_repo = FieldSyncLedgerRepository(self.session)
        ledger = await ledger_repo.get_by_client_op_id(data.entry_key)
        if ledger is not None:
            self._assert_offline_key_is_ours(data.entry_key, ledger, data.project_id)

        if ledger is not None and ledger.result_type == _LEDGER_RESULT_WITHDRAWN:
            return OfflineOpOutcome(None, OUTCOME_WITHDRAWN, detail="Already withdrawn.")

        timesheet: FieldTimesheet | None = None
        if ledger is not None and ledger.result_id is not None:
            timesheet = await self.repo.get_by_id(ledger.result_id)

        if timesheet is not None:
            if timesheet.project_id != data.project_id:
                raise _offline_scope_error()
            if timesheet.status != _DRAFT:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"This day is already '{timesheet.status}' in the office, so the device cannot "
                        "withdraw it. An approved timesheet is corrected by reversing it."
                    ),
                )
            await self.repo.delete(timesheet.id)

        await self._record_offline_key(
            data.entry_key,
            project_id=data.project_id,
            user_id=user_id,
            timesheet_id=None,
            existing=ledger,
            withdrawn=True,
        )
        logger.info("Offline field-time entry withdrawn (key=%s)", data.entry_key)
        return OfflineOpOutcome(None, OUTCOME_WITHDRAWN)

    async def _apply_offline_revision(
        self,
        timesheet: FieldTimesheet,
        data: OfflineEntrySubmission,
        user_id: str | None,
    ) -> OfflineOpOutcome:
        """Reconcile an offline op against the entry that key already produced."""
        matches = self._offline_entry_matches(timesheet, data)
        past_draft = timesheet.status != _DRAFT

        if matches:
            # The same content arriving again: a redelivery, not an edit. Say so
            # and touch nothing, whatever state the office has moved it to.
            return OfflineOpOutcome(timesheet, OUTCOME_REPLAYED, submitted=past_draft)

        if past_draft:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"This day is already '{timesheet.status}' in the office, so the correction made on "
                    "the device was not applied. An approved timesheet is corrected by reversing it."
                ),
            )

        # A newer full state for a day still in draft: replace it wholesale.
        for line in list(timesheet.lines):
            await self.repo.delete_line(line.id)
        for line in data.lines:
            await self.repo.add_line(self._line_from_create(timesheet.id, line))
        await self.repo.update_fields(
            timesheet.id,
            date=data.date,
            note=data.note,
            metadata_=merge_metadata(
                getattr(timesheet, "metadata_", None),
                {**dict(data.metadata or {}), ft.OFFLINE_METADATA_KEY: self._offline_record(data)},
            ),
        )
        await self.session.refresh(timesheet)
        timesheet, submitted, detail = await self._offline_submit(timesheet, data, user_id)
        return OfflineOpOutcome(timesheet, OUTCOME_UPDATED, submitted=submitted, detail=detail)

    async def _offline_submit(
        self,
        timesheet: FieldTimesheet,
        data: OfflineEntrySubmission,
        user_id: str | None,
    ) -> tuple[FieldTimesheet, bool, str | None]:
        """Send the entry on for approval when the op asked for it.

        A validation failure keeps the draft instead of losing the day. The whole
        reason this path exists is that the hours were recorded where nobody
        could check them; refusing to store them because they need a correction
        would throw away the only record of the shift. The caller reports the
        entry as stored-but-not-submitted and the foreman fixes it on the screen.

        Safe to swallow the refusal: validation reads and never writes, so
        nothing is half-applied when it raises.
        """
        if not data.submit or timesheet.status != _DRAFT:
            return timesheet, timesheet.status != _DRAFT, None
        try:
            submitted = await self.submit_timesheet(timesheet.id, user_id)
        except HTTPException as exc:
            if exc.status_code not in (
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            ):
                raise
            logger.info(
                "Offline entry %s stored as a draft: it cannot be submitted yet (%s)",
                timesheet.id,
                exc.status_code,
            )
            return timesheet, False, "Stored as a draft: validation must pass before it can be submitted."
        return submitted, True, None

    @staticmethod
    def _offline_record(data: OfflineEntrySubmission) -> dict[str, Any]:
        """Build the ``offline`` metadata block recorded on the timesheet.

        ``synced_at`` is the server's own clock. The device's ``captured_at`` is
        kept beside it but never trusted to order anything, which is why a wrong
        phone clock is a warning here and not a refusal.
        """
        return {
            "entry_key": data.entry_key,
            "captured_at": data.captured_at.isoformat() if data.captured_at else None,
            "synced_at": _utcnow().isoformat(),
            "device": (data.device or "").strip(),
        }

    @staticmethod
    def _offline_entry_matches(timesheet: FieldTimesheet, data: OfflineEntrySubmission) -> bool:
        """True when the stored entry already says exactly what the op says.

        Compares the day, the note and the set of lines. Metadata is left out on
        purpose: the server stamps its own arrival time into it, so comparing it
        would make every redelivery look like an edit.

        Hours are compared on their value, not their spelling. The column is
        ``Numeric(18, 4)``, so eight hours reads back as ``8.0000`` while the
        device sends ``8``; comparing the two as text would call every single
        redelivery an edit and quietly rewrite the day on each one.

        A line with clock times is compared on the hours those times produce,
        for the same reason: the server derives them on the way in, so comparing
        the stored duration against the number the device happened to put in the
        ``hours`` field would make every redelivery of a timed day look like an
        edit.
        """

        def line_key(
            resource: object,
            equipment: object,
            hours: object,
            cost_code: object,
            wbs: object,
            is_daywork: object,
            variation: object,
            note: object,
            started_at: object = None,
            ended_at: object = None,
            break_minutes: object = None,
            employer_kind: object = None,
            employer_subcontractor_id: object = None,
        ) -> tuple[str, ...]:
            return (
                str(resource or ""),
                str(equipment or ""),
                format(ft.to_decimal(hours).normalize(), "f"),
                str(cost_code or ""),
                str(wbs or ""),
                "1" if is_daywork else "0",
                str(variation or ""),
                str(note or ""),
                _instant_key(started_at),
                _instant_key(ended_at),
                str(int(break_minutes)) if break_minutes else "",
                str(employer_kind or ""),
                str(employer_subcontractor_id or ""),
            )

        if timesheet.date != data.date:
            return False
        if (timesheet.note or "") != (data.note or ""):
            return False
        stored = sorted(
            line_key(
                line.resource_id,
                line.equipment_id,
                line.hours,
                line.cost_code,
                line.wbs,
                line.is_daywork,
                line.variation_id,
                line.note,
                line.started_at,
                line.ended_at,
                line.break_minutes,
                line.employer_kind,
                line.employer_subcontractor_id,
            )
            for line in timesheet.lines
        )
        incoming = sorted(
            line_key(
                line.resource_id,
                line.equipment_id,
                ft.derive_line_hours(
                    line.started_at,
                    line.ended_at,
                    line.break_minutes,
                    booked_hours=line.hours,
                ).hours,
                line.cost_code,
                line.wbs,
                line.is_daywork,
                line.variation_id,
                line.note,
                line.started_at,
                line.ended_at,
                line.break_minutes,
                line.employer_kind,
                line.employer_subcontractor_id,
            )
            for line in data.lines
        )
        return stored == incoming

    @staticmethod
    def _assert_offline_key_is_ours(
        entry_key: str,
        ledger: FieldSyncLedger,
        project_id: uuid.UUID,
    ) -> None:
        """Refuse an entry key that already belongs to someone else.

        Neither check can be done by the router. The router verifies that the
        caller may reach the project named in the *payload*, but it is the key,
        not the payload, that selects the row this path goes on to rewrite.

        A key held by another module. The ledger is shared with the field diary
        and its uniqueness is on ``client_op_id`` alone, so a key already spent
        on a diary op resolves to a row this module does not own. The result id
        on such a row points into another table, so it reads back as "no
        timesheet yet" and this path would write one and then repoint the diary's
        row at it. That destroys the diary's own replay guard, and the next
        redelivery of the diary op - which the guard existed to absorb - lands a
        second time as a duplicate activity with duplicate hours. Refused rather
        than worked around: the key is spent and the device must mint a new one.

        A key held by another project. Nothing in the key says which project it
        belongs to, so a stale key replayed after the active project changed
        would otherwise reach the other project's day and rewrite or delete it.

        Args:
            entry_key: The device's key, for the log line.
            ledger: The row that key resolved to.
            project_id: The project the caller was authorised against.

        Raises:
            HTTPException: 409 when another module holds the key, 404 when
                another project does.
        """
        if ledger.op_kind != _LEDGER_OP_KIND:
            logger.warning(
                "Offline entry key %s is already held by op kind %s; refused",
                entry_key,
                ledger.op_kind,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This entry key is already in use by another field record. "
                    "Record the day again so the device gives it a new key."
                ),
            )
        if ledger.project_id != project_id:
            logger.warning("Offline entry key %s belongs to another project; refused", entry_key)
            raise _offline_scope_error()

    async def _record_offline_key(
        self,
        entry_key: str,
        *,
        project_id: uuid.UUID,
        user_id: str | None,
        timesheet_id: uuid.UUID | None,
        existing: FieldSyncLedger | None,
        withdrawn: bool = False,
    ) -> None:
        """Point the entry key at what it produced, in the shared field ledger.

        The ledger is the durable half of the promise the device's queue makes:
        the in-browser dedup only survives one tab, this survives the server.

        A fresh insert is wrapped in a SAVEPOINT so that two drains racing on the
        same key lose only the duplicate insert. A bare rollback would discard
        the timesheet this very request just wrote - the same trap the diary
        documents at its own ledger write.
        """
        from sqlalchemy.exc import IntegrityError

        result_type = _LEDGER_RESULT_WITHDRAWN if withdrawn else _LEDGER_RESULT_TIMESHEET
        actor = _as_uuid(user_id)
        if existing is not None:
            existing.result_type = result_type
            existing.result_id = None if withdrawn else timesheet_id
            await self.session.flush()
            return
        if actor is None:
            # The ledger is scoped to a real user (a NOT NULL foreign key). A
            # caller with no identity is a service-level call, not a device, so
            # there is nothing to replay and nothing to record.
            logger.debug("Offline entry key %s not recorded: no authenticated user", entry_key)
            return
        try:
            async with self.session.begin_nested():
                self.session.add(
                    FieldSyncLedger(
                        client_op_id=entry_key,
                        project_id=project_id,
                        user_id=actor,
                        op_kind=_LEDGER_OP_KIND,
                        result_type=result_type,
                        result_id=None if withdrawn else timesheet_id,
                    ),
                )
                await self.session.flush()
        except IntegrityError:
            # A racing drain recorded the key first. Its row is the canonical
            # one; the SAVEPOINT rolled back only this insert.
            logger.info("Offline entry key %s was recorded by a concurrent replay", entry_key)

    # ── Validation ───────────────────────────────────────────────────────────

    async def validate_timesheet(self, timesheet_id: uuid.UUID) -> dict[str, Any]:
        """Run the field-time rule set and return the report (read-only)."""
        timesheet = await self.get_timesheet(timesheet_id)
        report = await self._validate(timesheet, operation="read")
        return self._report_to_dict(report)

    async def _validate(self, timesheet: FieldTimesheet, *, operation: str) -> ValidationReport:
        """Build the validation payload and run the ``field_time`` rule set."""
        valid_cost_codes, valid_wbs = await self._resolve_cost_codes(timesheet.project_id)
        open_variation_ids = await self._open_variation_ids(timesheet.project_id)
        # The per-worker daily cap is a project setting (defaults to 24 hours):
        # forward it so the rule checks hours against the configured ceiling
        # rather than a single hard-coded value.
        config = ft.read_hours_config(getattr(timesheet, "metadata_", None))
        payload = {
            "id": str(timesheet.id),
            "project_id": str(timesheet.project_id),
            "date": str(timesheet.date),
            "status": timesheet.status,
            "lines": self._line_dicts(timesheet),
            # The timesheet's own metadata, so the offline rules can read how the
            # day travelled from the phone. An ordinary desk-entered timesheet
            # carries no offline block and those rules simply return nothing.
            "metadata": dict(getattr(timesheet, "metadata_", None) or {}),
        }
        metadata: dict[str, Any] = {
            "locale": get_locale(),
            "operation": operation,
            "valid_cost_codes": (list(valid_cost_codes) if valid_cost_codes is not None else None),
            "valid_wbs": (list(valid_wbs) if valid_wbs is not None else None),
            "open_variation_ids": (list(open_variation_ids) if open_variation_ids is not None else None),
            "max_hours_per_day": str(config.max_hours_per_day),
        }
        return await validation_engine.validate(
            data=payload,
            rule_sets=[_RULE_SET],
            target_type="field_timesheet",
            target_id=str(timesheet.id),
            project_id=str(timesheet.project_id),
            metadata=metadata,
        )

    async def _validate_or_raise(self, timesheet: FieldTimesheet, *, operation: str) -> ValidationReport:
        """Run validation and raise HTTP 422 when any ERROR-severity rule fails."""
        report = await self._validate(timesheet, operation=operation)
        if report.has_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "message": (
                        f"This timesheet has problems that must be fixed before you can {operation} it. "
                        "See the errors listed below, correct each line, then try again."
                    ),
                    "report": report.summary(),
                    "errors": [
                        {
                            "rule_id": r.rule_id,
                            "message": r.message,
                            "element_ref": r.element_ref,
                        }
                        for r in report.errors
                    ],
                },
            )
        return report

    # ── Cost-code suggestions (AI-augmented, human-confirmed) ────────────────

    async def suggest_cost_codes(
        self,
        project_id: uuid.UUID,
        text: str,
        *,
        limit: int = 5,
    ) -> list[CostCodeSuggestionOut]:
        """Rank BOQ cost codes by similarity to ``text`` (never auto-applied)."""
        candidates = await self._cost_code_candidates(project_id)
        suggestions = ft.suggest_cost_codes(text, candidates, limit=limit)
        return [CostCodeSuggestionOut(code=s.code, label=s.label, confidence=s.confidence) for s in suggestions]

    # ── Helpers: line construction ───────────────────────────────────────────

    @staticmethod
    def _assert_line_xor(resource_id: object, equipment_id: object) -> None:
        """Enforce labour XOR plant on a line (exactly one identifier set)."""
        has_resource = resource_id is not None
        has_equipment = equipment_id is not None
        if has_resource == has_equipment:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Each line records either a worker (labour) or a machine (plant), not both and "
                    "not neither. Pick one for this line and save again."
                ),
            )

    @staticmethod
    def _line_from_create(timesheet_id: uuid.UUID, data: FieldTimesheetLineCreate) -> FieldTimesheetLine:
        """Build a line ORM object from a create schema.

        A line that carries clock times gets its hours from them; a line without
        them keeps the hours as sent, which is every line this module has ever
        written and every line whoever does not need the times will write.
        """
        return FieldTimesheetLine(
            timesheet_id=timesheet_id,
            resource_id=data.resource_id,
            equipment_id=data.equipment_id,
            hours=FieldTimeService._derive_hours(
                data.started_at,
                data.ended_at,
                data.break_minutes,
                data.hours,
            ),
            cost_code=data.cost_code or "",
            wbs=data.wbs,
            boq_position_id=data.boq_position_id,
            is_daywork=data.is_daywork,
            variation_id=data.variation_id,
            note=data.note,
            started_at=data.started_at,
            ended_at=data.ended_at,
            break_minutes=data.break_minutes,
            employer_kind=data.employer_kind,
            employer_subcontractor_id=data.employer_subcontractor_id,
        )

    @staticmethod
    def _derive_hours(
        started_at: datetime | None,
        ended_at: datetime | None,
        break_minutes: int | None,
        booked_hours: object,
    ) -> Decimal:
        """The hours a line will carry, refusing clock times that cannot make one.

        There is no state in which a line holds both a pair of times and an
        independent number of hours: with times, the times decide. A pair that
        cannot produce a duration is refused rather than quietly falling back to
        the typed figure, because the record would then say one thing and its
        own evidence another.
        """
        derived = ft.derive_line_hours(started_at, ended_at, break_minutes, booked_hours=booked_hours)
        if derived.reason:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=_INTERVAL_MESSAGES.get(derived.reason, _INTERVAL_FALLBACK),
            )
        return derived.hours

    @staticmethod
    def _line_dicts(timesheet: FieldTimesheet) -> list[dict[str, Any]]:
        """Render a timesheet's lines as plain dicts for the pure engine."""
        out: list[dict[str, Any]] = []
        for line in timesheet.lines:
            out.append(
                {
                    "id": str(line.id),
                    "resource_id": str(line.resource_id) if line.resource_id else None,
                    "equipment_id": str(line.equipment_id) if line.equipment_id else None,
                    "hours": line.hours if line.hours is not None else Decimal("0"),
                    "cost_code": line.cost_code or "",
                    "wbs": line.wbs,
                    "boq_position_id": str(line.boq_position_id) if line.boq_position_id else None,
                    "is_daywork": bool(line.is_daywork),
                    "variation_id": str(line.variation_id) if line.variation_id else None,
                    "note": line.note or "",
                    # The clock times under the names the pure engine reads them
                    # by. They are what wakes up the double-booking check: two
                    # lines that put the same worker in two places at once are
                    # only detectable once the lines say when. A line without
                    # times is skipped by that check exactly as before.
                    "start": line.started_at,
                    "end": line.ended_at,
                },
            )
        return out

    # ── Helpers: cross-module resolution (all best-effort) ───────────────────

    async def _resolve_cost_codes(
        self,
        project_id: uuid.UUID,
    ) -> tuple[set[str] | None, set[str] | None]:
        """Return ``(valid_cost_codes, valid_wbs)`` for a project's BOQ, or None.

        None means "could not resolve" (BOQ module absent, query failed, or the
        project has no positions yet) so the cost-code rule skips rather than
        flagging every line - a project without a BOQ is not a data error.
        """
        try:
            from sqlalchemy import select

            from app.modules.boq.models import BOQ, Position

            stmt = (
                select(Position.reference_code, Position.ordinal, Position.wbs_id, Position.cost_code_id)
                .join(BOQ, Position.boq_id == BOQ.id)
                .where(BOQ.project_id == project_id)
            )
            rows = (await self.session.execute(stmt)).all()
        except Exception:
            logger.debug("Cost-code resolution unavailable for project=%s", project_id)
            return None, None

        cost_codes: set[str] = set()
        wbs: set[str] = set()
        for reference_code, ordinal, wbs_id, cost_code_id in rows:
            for code in (reference_code, ordinal, cost_code_id):
                if code:
                    cost_codes.add(str(code).strip())
            if wbs_id:
                wbs.add(str(wbs_id).strip())
        return (cost_codes or None), (wbs or None)

    async def _cost_code_candidates(self, project_id: uuid.UUID) -> list[dict[str, str]]:
        """Return ``[{"code", "label"}]`` cost-code candidates from the BOQ."""
        try:
            from sqlalchemy import select

            from app.modules.boq.models import BOQ, Position

            stmt = (
                select(Position.reference_code, Position.ordinal, Position.description)
                .join(BOQ, Position.boq_id == BOQ.id)
                .where(BOQ.project_id == project_id)
            )
            rows = (await self.session.execute(stmt)).all()
        except Exception:
            logger.debug("Cost-code candidates unavailable for project=%s", project_id)
            return []

        candidates: list[dict[str, str]] = []
        seen: set[str] = set()
        for reference_code, ordinal, description in rows:
            code = str(reference_code or ordinal or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            candidates.append({"code": code, "label": str(description or "").strip()})
        return candidates

    async def _open_variation_ids(self, project_id: uuid.UUID) -> set[str] | None:
        """Return the set of open variation-order ids, or None if unavailable."""
        try:
            from sqlalchemy import select

            from app.modules.variations.models import VariationOrder

            stmt = select(VariationOrder.id).where(
                VariationOrder.project_id == project_id,
                VariationOrder.status.in_(_OPEN_VARIATION_STATUSES),
            )
            rows = (await self.session.execute(stmt)).scalars().all()
        except Exception:
            logger.debug("Open-variation lookup unavailable for project=%s", project_id)
            return None
        return {str(r) for r in rows}

    async def _labour_rates(self, line_dicts: list[dict[str, Any]]) -> dict[str, Decimal]:
        """Resolve ``{resource_id: hourly_rate}`` from the resources module."""
        ids = [_as_uuid(line.get("resource_id")) for line in line_dicts]
        ids = [i for i in ids if i is not None]
        if not ids:
            return {}
        try:
            from sqlalchemy import select

            from app.modules.resources.models import Resource

            stmt = select(Resource.id, Resource.default_cost_rate).where(Resource.id.in_(ids))
            rows = (await self.session.execute(stmt)).all()
        except Exception:
            logger.debug("Labour-rate lookup unavailable")
            return {}
        return {str(rid): ft.to_decimal(rate) for rid, rate in rows}

    async def _plant_rates(
        self,
        line_dicts: list[dict[str, Any]],
        project_id: uuid.UUID,
    ) -> dict[str, Decimal]:
        """Resolve ``{equipment_id: hourly_rate}`` from the project's rentals.

        Uses the highest ``internal_rate_per_hour`` recorded for the equipment on
        this project. Missing rate -> the equipment is absent from the map and the
        pure rollup treats it as zero cost (hours still counted).
        """
        ids = [_as_uuid(line.get("equipment_id")) for line in line_dicts]
        ids = [i for i in ids if i is not None]
        if not ids:
            return {}
        try:
            from sqlalchemy import select

            from app.modules.equipment.models import EquipmentRental

            stmt = select(EquipmentRental.equipment_id, EquipmentRental.internal_rate_per_hour).where(
                EquipmentRental.equipment_id.in_(ids),
                EquipmentRental.project_id == project_id,
            )
            rows = (await self.session.execute(stmt)).all()
        except Exception:
            logger.debug("Plant-rate lookup unavailable for project=%s", project_id)
            return {}
        rates: dict[str, Decimal] = {}
        for equipment_id, rate in rows:
            key = str(equipment_id)
            value = ft.to_decimal(rate)
            if value > rates.get(key, Decimal("0")):
                rates[key] = value
        return rates

    async def _project_base_currency(self, project_id: uuid.UUID) -> str:
        """Best-effort read of the project's base currency (empty when unknown)."""
        try:
            from app.modules.costmodel.repository import BudgetLineRepository

            base, _fx = await BudgetLineRepository(self.session)._project_fx_context(project_id)
            return str(base or "").strip().upper()
        except Exception:
            logger.debug("Base-currency lookup unavailable for project=%s", project_id)
            return ""

    # ── Helpers: daywork write-through ───────────────────────────────────────

    async def _write_through_daywork(
        self,
        timesheet: FieldTimesheet,
        labour_rates: dict[str, Decimal],
        plant_rates: dict[str, Decimal],
        currency: str,
        user_id: str | None,
    ) -> None:
        """Mirror daywork lines onto signed daywork sheets (one per variation).

        Best-effort: any failure is logged and swallowed so the approval (and the
        hours actuals it posts) is never held hostage by the daywork write-through.

        The whole write-through runs inside a SAVEPOINT, which is what makes
        "swallowed" true on PostgreSQL. Catching the exception is not enough
        there: a failed statement puts the surrounding transaction into an
        aborted state, so every later statement - including the status update
        that posts the hours - fails with ``PendingRollbackError``. The savepoint
        confines the damage to the daywork writes, exactly as the docstring
        promises.
        """
        daywork_lines = [line for line in self._line_dicts(timesheet) if line.get("is_daywork")]
        if not daywork_lines:
            return
        try:
            async with self.session.begin_nested():
                from sqlalchemy import select

                from app.modules.variations.models import VariationOrder
                from app.modules.variations.schemas import DayworkSheetCreate, DayworkSheetLineCreate
                from app.modules.variations.service import VariationsService

                variations = VariationsService(self.session)
                # Group daywork lines by the variation they were performed under so
                # each signed sheet stays scoped to a single variation.
                by_variation: dict[str, list[dict[str, Any]]] = {}
                for line in daywork_lines:
                    by_variation.setdefault(str(line.get("variation_id") or ""), []).append(line)

                for variation_id, group in by_variation.items():
                    # The sheet is what a reviewer reads in the variations
                    # register, so it must name the work and the variation's
                    # human code - not a raw UUID, which is what this string
                    # carried before.
                    variation_code: str | None = None
                    if variation_id:
                        try:
                            variation_code = (
                                await self.session.execute(
                                    select(VariationOrder.code).where(VariationOrder.id == uuid.UUID(variation_id))
                                )
                            ).scalar_one_or_none()
                        except (ValueError, TypeError):
                            variation_code = None
                    drafts = ft.daywork_line_drafts(group, labour_rates=labour_rates, plant_rates=plant_rates)
                    work_summary = next((d.description for d in drafts if d.description), None)
                    description = work_summary or "Instructed daywork recorded on site"
                    if variation_code:
                        description += f" - variation {variation_code}"
                    description += f" (timesheet {timesheet.reference})"
                    sheet = await variations.create_daywork_sheet(
                        DayworkSheetCreate(
                            project_id=timesheet.project_id,
                            work_date=str(timesheet.date),
                            description=description,
                            currency=currency,
                            status="draft",
                        ),
                        user_id,
                    )
                    for draft in drafts:
                        await variations.add_daywork_line(
                            DayworkSheetLineCreate(
                                sheet_id=sheet.id,
                                line_type=draft.line_type,
                                description=draft.description,
                                quantity=draft.quantity,
                                unit=draft.unit,
                                unit_rate=draft.unit_rate,
                                worker_name=draft.worker_name,
                                equipment_code=draft.equipment_code,
                            ),
                        )
                    # Stamp the resulting sheet id back onto the source lines.
                    for line in group:
                        line_uuid = _as_uuid(line.get("id"))
                        if line_uuid is not None:
                            await self.repo.update_line_fields(line_uuid, daywork_sheet_id=sheet.id)
            await self.session.refresh(timesheet)
        except Exception:
            logger.exception(
                "Daywork write-through failed for timesheet=%s - approval unaffected",
                timesheet.id,
            )

    # ── Helpers: events + audit ──────────────────────────────────────────────

    def _publish_submitted(self, timesheet: FieldTimesheet, user_id: str | None) -> None:
        roll = ft.rollup(self._line_dicts(timesheet))
        from app.modules.field_time.events import publish_timesheet_submitted

        publish_timesheet_submitted(
            timesheet_id=str(timesheet.id),
            project_id=str(timesheet.project_id),
            work_date=str(timesheet.date),
            labour_hours=str(roll.labour_hours),
            plant_hours=str(roll.plant_hours),
            actor_id=user_id,
        )

    def _publish_approved(
        self,
        timesheet: FieldTimesheet,
        roll: ft.CostRollup,
        currency: str,
        user_id: str | None,
    ) -> None:
        from app.modules.field_time.events import publish_timesheet_approved

        publish_timesheet_approved(
            timesheet_id=str(timesheet.id),
            project_id=str(timesheet.project_id),
            work_date=str(timesheet.date),
            labour_hours=str(roll.labour_hours),
            plant_hours=str(roll.plant_hours),
            labour_cost=str(roll.labour_cost),
            plant_cost=str(roll.plant_cost),
            currency=currency,
            actor_id=user_id,
        )

    def _publish_labour_actuals(
        self,
        timesheet: FieldTimesheet,
        line_dicts: list[dict[str, Any]],
        labour_rates: dict[str, Decimal],
        currency: str,
        user_id: str | None,
    ) -> None:
        """Send the approved labour hours to the cost model.

        ``field_time.timesheet_approved`` carries only a rollup, and nothing
        subscribes to it, so approving a timesheet used to move no money at all
        while its own docstring said the hours had become authoritative
        actuals. The hours a foreman captures on a phone have reached the
        budget through ``fieldreports.labour.logged`` since the diary shipped;
        this sends the desktop timesheet's hours down the same pipe rather than
        inventing a second one.

        Per worker, not in aggregate. The cost model needs each row's own
        ``resource_id`` to tell that a day already costed from the phone is the
        same day, and an aggregate cannot say who it is made of.

        Plant is not here. Machine hours are not labour and do not belong on
        the labour budget line; they keep flowing through the rollup event.
        """
        rows: list[dict[str, Any]] = []
        for line in line_dicts:
            resource_id = str(line.get("resource_id") or "").strip()
            if not resource_id:
                continue  # plant, handled by the rollup event
            hours = ft.to_decimal(line.get("hours"))
            if hours <= 0:
                continue
            rows.append(
                {
                    "worker_type": "labour",
                    "hours": float(hours),
                    "headcount": 1,
                    "resource_id": resource_id,
                    "cost_rate": str(labour_rates.get(resource_id, Decimal("0"))),
                    "currency": currency,
                },
            )
        if not rows:
            return

        try:
            from app.modules.fieldreports.events import publish_labour_logged

            publish_labour_logged(
                report_id=str(timesheet.id),
                project_id=str(timesheet.project_id),
                report_date=str(timesheet.date),
                status="approved",
                rows=rows,
                actor_id=user_id,
                source="field_time",
            )
        except Exception:
            # A cost rollup must never undo an approval a manager has made.
            logger.exception(
                "Labour actuals publish failed for timesheet=%s - approval unaffected",
                timesheet.id,
            )

    def _publish_labour_credit(
        self,
        reversal: FieldTimesheet,
        original: FieldTimesheet,
        mirrored: list[dict[str, Any]],
        labour_rates: dict[str, Decimal],
        currency: str,
        user_id: str | None,
    ) -> None:
        """Take the reversed timesheet's labour actuals back off the budget.

        Approval posts money and claims each worker-day. Undoing only the money
        would leave the claim held, so the corrected sheet could never cost that
        day and neither could the phone: a reversal would strand the worker's
        day rather than free it. This releases both together.

        The rows are the reversal's own mirrored lines, hours positive. The sign
        is in the event name because the cost calculator skips non-positive
        hours - a negative payload would be ignored, not subtracted.
        """
        rows: list[dict[str, Any]] = []
        for line in mirrored:
            resource_id = str(line.get("resource_id") or "").strip()
            if not resource_id:
                continue  # plant, never posted to the labour line
            hours = ft.to_decimal(line.get("hours"))
            if hours <= 0:
                continue
            rows.append(
                {
                    "worker_type": "labour",
                    "hours": float(hours),
                    "headcount": 1,
                    "resource_id": resource_id,
                    "cost_rate": str(labour_rates.get(resource_id, Decimal("0"))),
                    "currency": currency,
                },
            )
        if not rows:
            return

        try:
            from app.modules.fieldreports.events import publish_labour_reversed

            publish_labour_reversed(
                report_id=str(reversal.id),
                reverses_id=str(original.id),
                project_id=str(reversal.project_id),
                report_date=str(reversal.date),
                rows=rows,
                actor_id=user_id,
                source="field_time",
            )
        except Exception:
            # A cost credit must never undo a reversal a manager has made.
            logger.exception(
                "Labour credit publish failed for reversal=%s - the reversal is unaffected",
                reversal.id,
            )

    def _publish_reversed(
        self,
        reversal: FieldTimesheet,
        original: FieldTimesheet,
        roll: ft.CostRollup,
        user_id: str | None,
    ) -> None:
        from app.modules.field_time.events import publish_timesheet_reversed

        publish_timesheet_reversed(
            timesheet_id=str(reversal.id),
            reverses_id=str(original.id),
            project_id=str(reversal.project_id),
            work_date=str(reversal.date),
            labour_hours=str(roll.labour_hours),
            plant_hours=str(roll.plant_hours),
            actor_id=user_id,
        )

    async def _audit(
        self,
        timesheet: FieldTimesheet,
        *,
        prior: str,
        new: str,
        user_id: str | None,
    ) -> None:
        """Write a universal audit-trail entry for a status change (best-effort)."""
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=user_id,
                entity_type="field_timesheet",
                entity_id=str(timesheet.id),
                action="status_changed",
                from_status=prior,
                to_status=new,
                reason=f"Field timesheet {new}",
                module="field_time",
                parent_entity_type="project",
                parent_entity_id=str(timesheet.project_id),
                before_state={"status": prior},
                after_state={"status": new},
            )
        except Exception:
            logger.debug("Audit-log write skipped for timesheet=%s", timesheet.id)

    # ── Helpers: assertions + report ─────────────────────────────────────────

    @staticmethod
    def _assert_draft(timesheet: FieldTimesheet, action: str) -> None:
        """Raise 400 unless the timesheet is still a draft."""
        if timesheet.status != _DRAFT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"You can only {action} a draft timesheet. This one is '{timesheet.status}' and is now locked. "
                    "To change an approved timesheet, reverse it and enter a new one."
                ),
            )

    @staticmethod
    def _report_to_dict(report: ValidationReport) -> dict[str, Any]:
        """Flatten a ValidationReport into the API response shape."""
        summary = report.summary()
        return {
            "status": summary["status"],
            "score": summary["score"],
            "counts": summary["counts"],
            "results": [
                {
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "severity": r.severity.value,
                    "category": r.category.value,
                    "passed": r.passed,
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "suggestion": r.suggestion,
                }
                for r in report.results
            ],
        }
