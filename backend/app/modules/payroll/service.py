# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Payroll service - draft batch generation from field labour.

Deterministic, human-confirmed: generation aggregates already-recorded
labour hours (it never invents data) into a *draft* batch a manager then
reviews. Hours x cost_rate is evaluated in each source row's native
currency, then converted to the project base via the shared cost-model FX
helper so a batch never blends currencies.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.repository import BudgetLineRepository, _amount_in_base
from app.modules.fieldreports.models import FieldReport, SiteWorkforceLog
from app.modules.payroll.events import (
    EVENT_PAYROLL_BATCH_FINALIZED,
    EVENT_PAYROLL_BATCH_POSTED,
    EVENT_PAYROLL_BATCH_SUBMITTED,
    safe_publish,
)
from app.modules.payroll.models import PayrollBatch, PayrollDeduction, PayrollEntry
from app.modules.payroll.repository import (
    PayrollBatchRepository,
    PayrollDeductionRepository,
    PayrollEntryRepository,
)

logger = logging.getLogger(__name__)

# Posting source family for labour-batch actuals. The cost spine is idempotent
# on (source_kind, source_ref); approve uses the batch id as the stable ref so
# re-approving the same batch never double-posts its labour cost.
_PAYROLL_SOURCE_KIND = "payroll_batch"
# Cost category every labour-batch actual lands under in the cost spine.
_PAYROLL_COST_CATEGORY = "labor"
# Batch lifecycle (FSM). draft -> submitted -> approved -> posted.
_STATUS_DRAFT = "draft"
_STATUS_SUBMITTED = "submitted"
_STATUS_APPROVED = "approved"
_STATUS_POSTED = "posted"
# GL account codes the posted batch debits/credits. Labour expense (debit)
# against accrued-wages payable (credit) - a standard payroll accrual entry.
_GL_LABOUR_EXPENSE_ACCOUNT = "5000"
_GL_WAGES_PAYABLE_ACCOUNT = "2100"
# Money quantum - two decimal places, the platform-wide money convention.
_MONEY_Q = Decimal("0.01")
# Allowed deduction buckets (display/grouping only - never a tax rule) and the
# two value modes. Mirrors the schema's Literal types; the service is the
# authority that resolves a line to a concrete amount.
_DEDUCTION_TYPES = ("tax", "social", "pension", "other")
_DEDUCTION_MODES = ("fixed", "percentage")


def _utcnow() -> datetime:
    """Return a timezone-aware UTC now (column is timezone=True)."""
    return datetime.now(UTC)


def _coerce_user_id(user_id: str | None) -> uuid.UUID | None:
    """Best-effort coerce a user-id string to a UUID, else None."""
    if not user_id:
        return None
    try:
        return uuid.UUID(str(user_id))
    except (ValueError, AttributeError, TypeError):
        return None


def _coerce_date(value: str | None) -> date | None:
    """Parse an ISO ``YYYY-MM-DD`` string into a ``date``, else None.

    The field-report ``report_date`` is a DATE column, so a date bound must be a
    real ``date`` object - PostgreSQL has no ``date >= varchar`` operator and
    asyncpg will not bind a string to a date parameter.
    """
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _finalize_idempotency_key(batch_id: uuid.UUID) -> str:
    """Deterministic SHA-256 idempotency key for finalizing *batch_id*.

    Stable across retries/replays (same batch -> same key) and collision-safe,
    so a double-finalize is recognised by the cost spine as the same posting.
    """
    return hashlib.sha256(str(batch_id).encode("utf-8")).hexdigest()


def _to_decimal(value: object) -> Decimal:
    """Coerce *value* to a non-negative finite Decimal, else 0."""
    if value is None:
        return Decimal("0")
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")
    if not d.is_finite() or d < 0:
        return Decimal("0")
    return d


class _AggRow:
    """A mutable per-(worker, date) accumulator used during generation."""

    __slots__ = ("worker", "work_date", "resource_id", "rate", "currency", "hours", "source")

    def __init__(
        self,
        *,
        worker: str,
        work_date: str | None,
        resource_id: str | None,
        rate: Decimal,
        currency: str,
        source: str,
    ) -> None:
        self.worker = worker
        self.work_date = work_date
        self.resource_id = resource_id
        self.rate = rate
        self.currency = currency
        self.hours = Decimal("0")
        self.source = source


class PayrollService:
    """Business logic for payroll batches and entries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.batch_repo = PayrollBatchRepository(session)
        self.entry_repo = PayrollEntryRepository(session)
        self.deduction_repo = PayrollDeductionRepository(session)
        self.budget_repo = BudgetLineRepository(session)

    # ── Rate resolution ─────────────────────────────────────────────────────

    async def _resource_rate(self, resource_id: str) -> tuple[Decimal, str]:
        """Return ``(default_cost_rate, currency)`` for a resource, or (0, "")."""
        try:
            rid = uuid.UUID(str(resource_id))
        except (ValueError, AttributeError, TypeError):
            return Decimal("0"), ""
        try:
            from app.modules.resources.repository import ResourceRepository

            resource = await ResourceRepository(self.session).get_by_id(rid)
        except Exception:
            return Decimal("0"), ""
        if resource is None:
            return Decimal("0"), ""
        rate = resource.default_cost_rate if resource.default_cost_rate is not None else Decimal("0")
        return _to_decimal(rate), (resource.currency or "").strip().upper()

    # ── Source collection ───────────────────────────────────────────────────

    async def _collect_workforce_logs(
        self,
        project_id: uuid.UUID,
        *,
        date_from: str | None,
        date_to: str | None,
    ) -> list[dict]:
        """Collect SiteWorkforceLog rows joined to their report date/project.

        Returns a list of normalised dicts: ``worker_type``, ``work_date``,
        ``hours`` (regular + overtime), ``resource_id`` / ``cost_rate`` /
        ``currency`` (from the log metadata when present).
        """
        stmt = (
            select(SiteWorkforceLog, FieldReport.report_date)
            .join(FieldReport, SiteWorkforceLog.field_report_id == FieldReport.id)
            .where(FieldReport.project_id == project_id)
        )
        # ``report_date`` is a DATE column; the bounds arrive as ISO strings, so
        # parse them to ``date`` for the comparison (PostgreSQL has no
        # ``date >= varchar`` operator).
        df = _coerce_date(date_from)
        dt = _coerce_date(date_to)
        if df is not None:
            stmt = stmt.where(FieldReport.report_date >= df)
        if dt is not None:
            stmt = stmt.where(FieldReport.report_date <= dt)

        result = await self.session.execute(stmt)
        rows: list[dict] = []
        for log, report_date in result.all():
            md = log.metadata_ if isinstance(log.metadata_, dict) else {}
            hours = _to_decimal(log.hours_worked) + _to_decimal(log.overtime_hours)
            if hours <= 0:
                continue
            row: dict = {
                "worker_type": log.worker_type or "labour",
                "work_date": str(report_date) if report_date is not None else None,
                "hours": hours,
                "headcount": int(log.headcount or 0),
                "source": "fieldreport",
            }
            if md.get("resource_id"):
                row["resource_id"] = str(md["resource_id"])
            if md.get("cost_rate") is not None:
                row["cost_rate"] = str(md["cost_rate"])
            if md.get("currency"):
                row["currency"] = str(md["currency"]).strip().upper()
            rows.append(row)
        return rows

    async def _collect_diary_hours(
        self,
        project_id: uuid.UUID,
        *,
        date_from: str | None,
        date_to: str | None,
    ) -> list[dict]:
        """Collect field-diary work hours for the project (best-effort).

        The diary module is an optional dependency; if its models are not
        loaded we simply skip this source rather than failing generation.
        """
        try:
            from app.modules.field_diary.models import DiaryActivity, DiaryEntry
        except Exception:
            return []

        stmt = (
            select(
                DiaryActivity.hours,
                DiaryActivity.activity_type,
                DiaryActivity.metadata_,
                DiaryEntry.entry_date,
            )
            .join(DiaryEntry, DiaryActivity.entry_id == DiaryEntry.id)
            .where(DiaryEntry.project_id == project_id)
        )
        if date_from:
            stmt = stmt.where(DiaryEntry.entry_date >= date_from)
        if date_to:
            stmt = stmt.where(DiaryEntry.entry_date <= date_to)

        try:
            result = await self.session.execute(stmt)
        except Exception:
            logger.debug("Field-diary hours unavailable for project=%s", project_id)
            return []

        rows: list[dict] = []
        for hours_raw, activity_type, md_raw, entry_date in result.all():
            if activity_type not in ("work", "inspection"):
                continue
            hours = _to_decimal(hours_raw)
            if hours <= 0:
                continue
            md = md_raw if isinstance(md_raw, dict) else {}
            row: dict = {
                "worker_type": str(activity_type),
                "work_date": str(entry_date) if entry_date is not None else None,
                "hours": hours,
                "headcount": 1,
                "source": "field_diary",
            }
            if md.get("resource_id"):
                row["resource_id"] = str(md["resource_id"])
            if md.get("cost_rate") is not None:
                row["cost_rate"] = str(md["cost_rate"])
            if md.get("currency"):
                row["currency"] = str(md["currency"]).strip().upper()
            rows.append(row)
        return rows

    async def _collect_field_timesheet_hours(
        self,
        project_id: uuid.UUID,
        *,
        date_from: str | None,
        date_to: str | None,
    ) -> list[dict]:
        """Collect approved field-timesheet labour hours for the project.

        An approved field timesheet (see the field_time module) is the
        authoritative record of who worked and for how long, coded to the BOQ.
        Only labour lines (those carrying a ``resource_id``) feed payroll; plant
        lines are equipment cost, not wages. Reversals are excluded and a
        reversed original flips to status ``reversed`` (so no longer
        ``approved``), which nets a reversed pair to zero here without any
        negative-hour handling.

        Best-effort: if the field_time module is not loaded (or the table is
        missing) this returns an empty list, so payroll behaves exactly as
        before on a project that has no field timesheets.
        """
        try:
            from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
            from app.modules.resources.models import Resource
        except Exception:
            return []

        stmt = (
            select(
                FieldTimesheetLine.resource_id,
                FieldTimesheetLine.hours,
                FieldTimesheet.date,
                Resource.name,
            )
            .select_from(FieldTimesheetLine)
            .join(FieldTimesheet, FieldTimesheetLine.timesheet_id == FieldTimesheet.id)
            .join(Resource, FieldTimesheetLine.resource_id == Resource.id, isouter=True)
            .where(
                FieldTimesheet.project_id == project_id,
                FieldTimesheet.status == _STATUS_APPROVED,
                FieldTimesheet.reverses_id.is_(None),
                FieldTimesheetLine.resource_id.isnot(None),
            )
        )
        df = _coerce_date(date_from)
        dt = _coerce_date(date_to)
        if df is not None:
            stmt = stmt.where(FieldTimesheet.date >= df)
        if dt is not None:
            stmt = stmt.where(FieldTimesheet.date <= dt)

        try:
            result = await self.session.execute(stmt)
        except Exception:
            logger.debug("Field-timesheet hours unavailable for project=%s", project_id)
            return []

        rows: list[dict] = []
        for resource_id, hours, work_date, resource_name in result.all():
            worked = _to_decimal(hours)
            if worked <= 0:
                continue
            rows.append(
                {
                    "worker_type": (resource_name or "labour"),
                    "work_date": str(work_date) if work_date is not None else None,
                    "hours": worked,
                    "headcount": 1,
                    "resource_id": str(resource_id),
                    "source": "field_timesheet",
                }
            )
        return rows

    async def _collect_all_labour_sources(
        self,
        project_id: uuid.UUID,
        *,
        date_from: str | None,
        date_to: str | None,
    ) -> list[dict]:
        """Collect every field-labour source, preferring approved timesheets.

        Field reports and the field diary are the historic sources; approved
        field timesheets are authoritative where present. To avoid double
        counting the same person-day, any field-report / diary row whose
        ``(resource_id, date)`` is already covered by an approved timesheet is
        dropped in favour of the timesheet row. Rows without a ``resource_id``
        (headcount-only labour) are a different granularity and are always kept.

        When there are no field timesheets the result is byte-for-byte identical
        to the previous ``workforce + diary`` collection (order preserved).
        """
        workforce = await self._collect_workforce_logs(project_id, date_from=date_from, date_to=date_to)
        diary = await self._collect_diary_hours(project_id, date_from=date_from, date_to=date_to)
        timesheets = await self._collect_field_timesheet_hours(project_id, date_from=date_from, date_to=date_to)
        if not timesheets:
            return workforce + diary

        covered = {(row["resource_id"], row.get("work_date")) for row in timesheets if row.get("resource_id")}
        kept: list[dict] = []
        for row in workforce + diary:
            resource_id = row.get("resource_id")
            if resource_id and (str(resource_id), row.get("work_date")) in covered:
                continue
            kept.append(row)
        return kept + timesheets

    # ── Aggregation core ────────────────────────────────────────────────────

    async def _aggregate(
        self,
        project_id: uuid.UUID,
        source_rows: list[dict],
    ) -> tuple[list[_AggRow], str, dict[str, str]]:
        """Aggregate source rows per (worker-key, date), resolving rates.

        Returns ``(agg_rows, base_currency, fx_map)``. The worker key is the
        ``resource_id`` when present (so multiple logs for the same person on
        the same day merge), else the ``worker_type`` label.
        """
        base, fx = await self.budget_repo._project_fx_context(project_id)
        buckets: dict[tuple[str, str | None], _AggRow] = {}

        for row in source_rows:
            hours = _to_decimal(row.get("hours"))
            if hours <= 0:
                continue

            resource_id = row.get("resource_id")
            rate = _to_decimal(row.get("cost_rate"))
            currency = str(row.get("currency") or "").strip().upper()
            if rate <= 0 and resource_id:
                rate, res_ccy = await self._resource_rate(str(resource_id))
                if not currency:
                    currency = res_ccy

            worker_key = str(resource_id) if resource_id else str(row.get("worker_type") or "labour")
            work_date = row.get("work_date")
            key = (worker_key, work_date)

            agg = buckets.get(key)
            if agg is None:
                agg = _AggRow(
                    worker=str(row.get("worker_type") or worker_key),
                    work_date=work_date,
                    resource_id=str(resource_id) if resource_id else None,
                    rate=rate,
                    currency=currency,
                    source=str(row.get("source") or "fieldreport"),
                )
                buckets[key] = agg
            else:
                # Keep the first non-zero rate/currency seen for the worker/day.
                if agg.rate <= 0 and rate > 0:
                    agg.rate = rate
                if not agg.currency and currency:
                    agg.currency = currency
            agg.hours += hours

        return list(buckets.values()), base, fx

    # ── Generation ──────────────────────────────────────────────────────────

    async def generate_batch(
        self,
        project_id: uuid.UUID,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        period_label: str | None = None,
        notes: str = "",
        user_id: str | None = None,
    ) -> tuple[PayrollBatch, list[PayrollEntry]]:
        """Generate a DRAFT payroll batch from field labour for a project.

        Raises 404 when there is no labour to aggregate so the caller gets a
        clear signal rather than an empty zero-total batch.
        """
        source_rows = await self._collect_all_labour_sources(project_id, date_from=date_from, date_to=date_to)

        agg_rows, base, fx = await self._aggregate(project_id, source_rows)
        if not agg_rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No field labour found to generate a payroll batch",
            )

        created_by: uuid.UUID | None = None
        if user_id:
            try:
                created_by = uuid.UUID(str(user_id))
            except (ValueError, AttributeError, TypeError):
                created_by = None

        dates = sorted(a.work_date for a in agg_rows if a.work_date)
        span_start = dates[0] if dates else date_from
        span_end = dates[-1] if dates else date_to
        label = period_label or (f"{span_start} - {span_end}" if span_start and span_end else "Field labour")

        batch = PayrollBatch(
            project_id=project_id,
            period_label=label[:120],
            period_start=span_start,
            period_end=span_end,
            status="draft",
            currency=base,
            notes=notes,
            created_by=created_by,
        )
        batch = await self.batch_repo.create(batch)

        entries: list[PayrollEntry] = []
        total_hours = Decimal("0")
        total_amount = Decimal("0")
        for agg in agg_rows:
            # amount = hours x rate in native currency, converted to base.
            amount_native = agg.hours * agg.rate
            amount_base = _amount_in_base(str(amount_native), agg.currency, base, fx)
            total_hours += agg.hours
            total_amount += amount_base
            entry_resource_id: uuid.UUID | None = None
            if agg.resource_id:
                try:
                    entry_resource_id = uuid.UUID(str(agg.resource_id))
                except (ValueError, AttributeError, TypeError):
                    entry_resource_id = None
            amount_q = amount_base.quantize(_MONEY_Q)
            entries.append(
                PayrollEntry(
                    batch_id=batch.id,
                    resource_id=entry_resource_id,
                    worker=agg.worker[:255],
                    work_date=agg.work_date,
                    hours=str(agg.hours.quantize(_MONEY_Q)),
                    rate=str(agg.rate.quantize(Decimal("0.0001"))),
                    amount=str(amount_q),
                    # Fresh entries carry no deductions, so net starts equal to
                    # gross (backfill-safe). Adding a deduction recomputes it.
                    net_amount=str(amount_q),
                    currency=base,
                    source=agg.source,
                )
            )

        await self.entry_repo.bulk_create(entries)

        total_amount_q = total_amount.quantize(_MONEY_Q)
        await self.batch_repo.update_fields(
            batch.id,
            total_hours=str(total_hours.quantize(_MONEY_Q)),
            total_amount=str(total_amount_q),
            # No deductions at generation: net == gross.
            total_deductions="0.00",
            total_net=str(total_amount_q),
            entry_count=len(entries),
        )
        await self.session.refresh(batch)

        logger.info(
            "Payroll batch generated: project=%s entries=%d hours=%s amount=%s %s",
            project_id,
            len(entries),
            total_hours,
            total_amount,
            base,
        )
        return batch, entries

    # ── Read ─────────────────────────────────────────────────────────────────

    async def list_batches(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[PayrollBatch], int]:
        return await self.batch_repo.list_for_project(project_id, offset=offset, limit=limit)

    async def get_batch(self, batch_id: uuid.UUID) -> PayrollBatch:
        batch = await self.batch_repo.get_by_id(batch_id)
        if batch is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payroll batch not found",
            )
        return batch

    async def list_entries(self, batch_id: uuid.UUID) -> list[PayrollEntry]:
        return await self.entry_repo.list_for_batch(batch_id)

    async def list_deductions_by_entry(self, batch_id: uuid.UUID) -> dict[uuid.UUID, list[PayrollDeduction]]:
        """Bulk-load every payslip's deductions for a batch, grouped by entry id.

        One query for the whole batch (no N+1) so the detail router can attach
        deductions to each entry response.
        """
        entries = await self.entry_repo.list_for_batch(batch_id)
        return await self.deduction_repo.list_for_entries([e.id for e in entries])

    async def list_deductions_for_entry(self, entry_id: uuid.UUID) -> list[PayrollDeduction]:
        return await self.deduction_repo.list_for_entry(entry_id)

    # ── Deductions & net pay ──────────────────────────────────────────────────

    @staticmethod
    def _resolve_deduction_amount(
        *,
        mode: str,
        value: Decimal,
        base: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Resolve a deduction to ``(amount, base_used)`` in batch currency.

        * ``fixed``      -> the value itself is the amount; base is not used (0).
        * ``percentage`` -> ``base * value / 100`` (value is a percent), clamped
          so a percentage never exceeds 100% of the base. Pure Decimal math; the
          result is quantized to the money quantum by the caller.

        The platform never injects a rate here - ``value`` is whatever the user
        entered. This only does the arithmetic.
        """
        if mode == "percentage":
            pct = value
            if pct > Decimal("100"):
                pct = Decimal("100")
            amount = (base * pct) / Decimal("100")
            return amount, base
        # fixed
        return value, Decimal("0")

    async def _recompute_entry_net(self, entry: PayrollEntry) -> Decimal:
        """Recompute and persist ``net_amount`` for one entry; return its net.

        net = gross - sum(deduction amounts), floored at 0 so a payslip can
        never go negative (an over-deduction is clamped rather than producing a
        nonsensical negative net). All Decimal, quantized to the money quantum.
        """
        gross = _to_decimal(entry.amount).quantize(_MONEY_Q)
        deductions = await self.deduction_repo.list_for_entry(entry.id)
        total_ded = Decimal("0")
        for ded in deductions:
            total_ded += _to_decimal(ded.amount)
        total_ded = total_ded.quantize(_MONEY_Q)
        net = gross - total_ded
        if net < 0:
            net = Decimal("0")
        net = net.quantize(_MONEY_Q)
        await self.entry_repo.update_fields(entry.id, net_amount=str(net))
        return net

    async def _recompute_batch_totals(self, batch_id: uuid.UUID) -> None:
        """Recompute the batch deduction/net rollups from its live entries.

        ``total_amount`` (gross) is NOT touched here - it is owned by generation
        and reflects labour cost. Only ``total_deductions`` / ``total_net`` are
        refreshed: total_deductions = gross - net summed over entries (so a
        clamped negative net is reflected consistently), total_net = sum(net).
        """
        entries = await self.entry_repo.list_for_batch(batch_id)
        total_gross = Decimal("0")
        total_net = Decimal("0")
        for entry in entries:
            total_gross += _to_decimal(entry.amount)
            total_net += _to_decimal(entry.net_amount)
        total_gross = total_gross.quantize(_MONEY_Q)
        total_net = total_net.quantize(_MONEY_Q)
        total_ded = (total_gross - total_net).quantize(_MONEY_Q)
        if total_ded < 0:
            total_ded = Decimal("0")
        await self.batch_repo.update_fields(
            batch_id,
            total_deductions=str(total_ded),
            total_net=str(total_net),
        )

    async def _get_entry_in_batch(self, batch_id: uuid.UUID, entry_id: uuid.UUID) -> PayrollEntry:
        """Fetch an entry and assert it belongs to ``batch_id`` (404 otherwise)."""
        entry = await self.entry_repo.get_by_id(entry_id)
        if entry is None or entry.batch_id != batch_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payslip entry not found in this batch",
            )
        return entry

    async def add_deduction(
        self,
        batch_id: uuid.UUID,
        entry_id: uuid.UUID,
        *,
        label: str,
        deduction_type: str = "other",
        mode: str = "fixed",
        value: str = "0",
        base_amount: str | None = None,
    ) -> PayrollEntry:
        """Add a withholding line to a payslip and recompute net + batch totals.

        Editing money on a batch already approved/posted is refused - those have
        moved cost to the budget/GL, so the payslip is frozen. Returns the
        refreshed parent entry (net recomputed).
        """
        batch = await self.get_batch(batch_id)
        if batch.status in (_STATUS_APPROVED, _STATUS_POSTED):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot edit deductions on a '{batch.status}' batch.",
            )
        entry = await self._get_entry_in_batch(batch_id, entry_id)

        dtype = deduction_type if deduction_type in _DEDUCTION_TYPES else "other"
        dmode = mode if mode in _DEDUCTION_MODES else "fixed"
        val = _to_decimal(value)

        gross = _to_decimal(entry.amount)
        # Percentage base: explicit when given, else the entry gross.
        base = _to_decimal(base_amount) if base_amount not in (None, "") else gross
        amount, base_used = self._resolve_deduction_amount(mode=dmode, value=val, base=base)
        amount = amount.quantize(_MONEY_Q)

        next_ordinal = await self.deduction_repo.max_ordinal_for_entry(entry_id) + 1
        deduction = PayrollDeduction(
            entry_id=entry_id,
            label=label.strip()[:160] or "Deduction",
            deduction_type=dtype,
            mode=dmode,
            value=str(val),
            base_amount=str(base_used.quantize(_MONEY_Q)) if dmode == "percentage" else "0",
            amount=str(amount),
            currency=(entry.currency or batch.currency or "").strip().upper(),
            ordinal=next_ordinal,
        )
        await self.deduction_repo.create(deduction)

        await self._recompute_entry_net(entry)
        await self._recompute_batch_totals(batch_id)
        await self.session.refresh(entry)
        logger.info(
            "Payroll deduction added: batch=%s entry=%s type=%s mode=%s amount=%s",
            batch_id,
            entry_id,
            dtype,
            dmode,
            amount,
        )
        return entry

    async def remove_deduction(
        self,
        batch_id: uuid.UUID,
        entry_id: uuid.UUID,
        deduction_id: uuid.UUID,
    ) -> PayrollEntry:
        """Remove a withholding line and recompute net + batch totals.

        Refused on an approved/posted batch (frozen). 404 if the deduction does
        not belong to the given entry/batch. Returns the refreshed parent entry.
        """
        batch = await self.get_batch(batch_id)
        if batch.status in (_STATUS_APPROVED, _STATUS_POSTED):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot edit deductions on a '{batch.status}' batch.",
            )
        entry = await self._get_entry_in_batch(batch_id, entry_id)
        deduction = await self.deduction_repo.get_by_id(deduction_id)
        if deduction is None or deduction.entry_id != entry_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deduction not found on this payslip",
            )
        await self.deduction_repo.delete(deduction)

        await self._recompute_entry_net(entry)
        await self._recompute_batch_totals(batch_id)
        await self.session.refresh(entry)
        logger.info(
            "Payroll deduction removed: batch=%s entry=%s deduction=%s",
            batch_id,
            entry_id,
            deduction_id,
        )
        return entry

    # ── Helpers shared by the lifecycle transitions ──────────────────────────

    async def _batch_total(self, batch: PayrollBatch) -> Decimal:
        """Sum live entry amounts (project base), falling back to the stored total.

        Entries are persisted in the batch currency (project base) by the
        generator, so this is a plain Decimal sum with no FX. Summing live
        entries over the denormalised total reflects any hand-edit.
        """
        entries = await self.entry_repo.list_for_batch(batch.id)
        if not entries:
            return _to_decimal(batch.total_amount).quantize(Decimal("0.01"))
        total = Decimal("0")
        for entry in entries:
            total += _to_decimal(entry.amount)
        return total.quantize(Decimal("0.01"))

    # ── FSM: submit (draft -> submitted) ─────────────────────────────────────

    async def submit_batch(self, batch_id: uuid.UUID, *, user_id: str | None = None) -> PayrollBatch:
        """Submit a draft batch for approval (no money moved).

        Idempotent: an already-submitted batch is returned unchanged. Only a
        ``draft`` batch can be submitted; any other status is a 400.
        """
        batch = await self.get_batch(batch_id)
        if batch.status == _STATUS_SUBMITTED:
            return batch
        if batch.status != _STATUS_DRAFT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot submit a batch in status '{batch.status}' (must be 'draft').",
            )
        await self.batch_repo.update_fields(
            batch.id,
            status=_STATUS_SUBMITTED,
            submitted_at=_utcnow(),
            submitted_by=_coerce_user_id(user_id),
        )
        await self.session.refresh(batch)
        await safe_publish(
            EVENT_PAYROLL_BATCH_SUBMITTED,
            {"project_id": str(batch.project_id), "batch_id": str(batch.id)},
        )
        return batch

    # ── FSM: approve (submitted/draft -> approved, post labour cost) ─────────

    async def finalize_batch(self, batch_id: uuid.UUID, *, user_id: str | None = None) -> PayrollBatch:
        """Approve a batch and post its labour cost to the cost spine.

        Accepts a ``draft`` (single-step approve) OR a ``submitted`` batch so the
        two-step submit/approve flow and the direct approve both work. Idempotent
        and safe to retry:
            * 404 when the batch does not exist.
            * Already ``approved`` / ``posted`` -> returned unchanged (no re-post).
            * Any other status -> 400.
            * Otherwise: sums the batch entries (already in project base
              currency), posts the labour actual onto the project's cost-spine
              labour budget line via the shared
              :meth:`CostSpineService.post_actual_to_budget_line` (idempotent on
              ``(source_kind="payroll_batch", source_ref=str(batch.id))``),
              flips ``status`` to ``approved`` and emits
              ``payroll.batch.finalized``.

        The posting amount never re-applies FX (the generator already converted
        to base), so a rate change after generation cannot retroactively move an
        approved amount. A zero-total batch still transitions to approved but
        posts nothing (skipped to avoid a noisy 0.00 posting trail entry).
        """
        batch = await self.get_batch(batch_id)

        if batch.status in (_STATUS_APPROVED, _STATUS_POSTED):
            return batch

        if batch.status not in (_STATUS_DRAFT, _STATUS_SUBMITTED):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot approve a batch in status '{batch.status}' (must be 'draft' or 'submitted').",
            )

        total = await self._batch_total(batch)
        currency = (batch.currency or "").strip().upper()
        budget_line_id: uuid.UUID | None = None

        if total > 0:
            if not currency:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Batch has no currency - cannot post labour cost to the budget.",
                )
            from app.modules.costmodel.service import CostSpineService

            spine_service = CostSpineService(self.session)
            line = await spine_service.post_actual_to_budget_line(
                project_id=batch.project_id,
                cost_line_id=None,
                cost_category=_PAYROLL_COST_CATEGORY,
                amount_base=str(total),
                currency=currency,
                source_kind=_PAYROLL_SOURCE_KIND,
                source_ref=str(batch.id),
                idempotency_key=_finalize_idempotency_key(batch.id),
            )
            budget_line_id = line.id

            # The batch was built from the same field records that were costed
            # as they were logged. Its posting replaces that estimate for the
            # days it pays, otherwise each covered day reads as paid twice.
            from app.modules.costmodel.service import LabourActualsService

            entries = await self.entry_repo.list_for_batch(batch.id)
            await LabourActualsService(self.session).supersede_with_payroll(
                project_id=batch.project_id,
                batch_id=str(batch.id),
                entries=[
                    {
                        "resource_id": str(entry.resource_id) if entry.resource_id else "",
                        "work_date": entry.work_date or "",
                        "hours": entry.hours,
                    }
                    for entry in entries
                ],
            )

        # Flip status only after a successful post (post raises on failure, so a
        # failed posting leaves the batch unchanged for a safe retry).
        await self.batch_repo.update_fields(
            batch.id,
            status=_STATUS_APPROVED,
            approved_at=_utcnow(),
            approved_by=_coerce_user_id(user_id),
        )
        await self.session.refresh(batch)

        await safe_publish(
            EVENT_PAYROLL_BATCH_FINALIZED,
            {
                "project_id": str(batch.project_id),
                "batch_id": str(batch.id),
                "amount": str(total),
                "currency": currency,
                "budget_line_id": str(budget_line_id) if budget_line_id else None,
            },
        )

        logger.info(
            "Payroll batch approved: project=%s batch=%s amount=%s %s budget_line=%s",
            batch.project_id,
            batch.id,
            total,
            currency,
            budget_line_id,
        )
        return batch

    # ── FSM: post (approved -> posted, hand to the finance GL) ───────────────

    async def post_batch(self, batch_id: uuid.UUID, *, user_id: str | None = None) -> PayrollBatch:
        """Post an approved batch to the finance general ledger.

        Writes a balanced double-entry payroll accrual (debit labour expense,
        credit wages payable) via the shared finance ledger service, then flips
        the batch to the terminal ``posted`` status. Idempotent: an already
        ``posted`` batch is returned unchanged (and we never write a second
        journal - the stored ``gl_transaction_ref`` is the guard). Only an
        ``approved`` batch can be posted.
        """
        batch = await self.get_batch(batch_id)
        if batch.status == _STATUS_POSTED:
            return batch
        if batch.status != _STATUS_APPROVED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot post a batch in status '{batch.status}' (must be 'approved').",
            )

        total = await self._batch_total(batch)
        currency = (batch.currency or "").strip().upper()
        # Stable, collision-safe ledger ref derived from the batch id.
        gl_ref = f"PAYROLL-{batch.id}"

        if total > 0:
            if not currency:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Batch has no currency - cannot post to the ledger.",
                )
            from app.modules.finance.models import LedgerEntry
            from app.modules.finance.schemas import LedgerEntryCreate
            from app.modules.finance.service import FinanceService

            # Guard against a double journal if the status flip failed after a
            # prior ledger write: skip the write when a row already carries the ref.
            existing = await self.session.execute(
                select(LedgerEntry.id).where(LedgerEntry.transaction_ref == gl_ref).limit(1)
            )
            already = existing.first() is not None
            if not already:
                finance = FinanceService(self.session)
                await finance.create_ledger_transaction(
                    LedgerEntryCreate(
                        project_id=batch.project_id,
                        transaction_ref=gl_ref,
                        debit_account=_GL_LABOUR_EXPENSE_ACCOUNT,
                        credit_account=_GL_WAGES_PAYABLE_ACCOUNT,
                        debit_amount=str(total),
                        credit_amount=str(total),
                        description=f"Payroll batch {batch.period_label}",
                        currency_code=currency,
                        source_type=_PAYROLL_SOURCE_KIND,
                        source_id=str(batch.id),
                        created_by=user_id,
                    )
                )

        await self.batch_repo.update_fields(
            batch.id,
            status=_STATUS_POSTED,
            posted_at=_utcnow(),
            posted_by=_coerce_user_id(user_id),
            gl_transaction_ref=gl_ref,
        )
        await self.session.refresh(batch)

        await safe_publish(
            EVENT_PAYROLL_BATCH_POSTED,
            {
                "project_id": str(batch.project_id),
                "batch_id": str(batch.id),
                "amount": str(total),
                "currency": currency,
                "gl_transaction_ref": gl_ref,
            },
        )
        logger.info(
            "Payroll batch posted to GL: project=%s batch=%s ref=%s amount=%s %s",
            batch.project_id,
            batch.id,
            gl_ref,
            total,
            currency,
        )
        return batch

    # ── Reconciliation (batch hours vs live field hours) ─────────────────────

    async def reconcile_batch(self, batch_id: uuid.UUID) -> dict:
        """Reconcile a batch against the live field-labour sources.

        Re-collects field-report + diary hours for the batch's project over its
        period, aggregates them per (worker-key, date), and compares against the
        batch's own entries. Returns a per-row delta plus a balanced flag. This
        is a read-only diagnostic - it never mutates the batch.
        """
        batch = await self.get_batch(batch_id)

        # Live source hours, keyed the same way the generator keys entries:
        # resource_id when present, else worker_type label, paired with date.
        source_rows = await self._collect_all_labour_sources(
            batch.project_id, date_from=batch.period_start, date_to=batch.period_end
        )
        agg_rows, _base, _fx = await self._aggregate(batch.project_id, source_rows)

        source_by_key: dict[tuple[str, str | None], Decimal] = {}
        for agg in agg_rows:
            key = (str(agg.resource_id) if agg.resource_id else agg.worker, agg.work_date)
            source_by_key[key] = source_by_key.get(key, Decimal("0")) + agg.hours

        entries = await self.entry_repo.list_for_batch(batch_id)
        batch_by_key: dict[tuple[str, str | None], tuple[Decimal, uuid.UUID | None, str]] = {}
        for e in entries:
            key = (str(e.resource_id) if e.resource_id else e.worker, e.work_date)
            prev_hours, _rid, _w = batch_by_key.get(key, (Decimal("0"), e.resource_id, e.worker))
            batch_by_key[key] = (prev_hours + _to_decimal(e.hours), e.resource_id, e.worker)

        rows: list[dict] = []
        batch_total = Decimal("0")
        source_total = Decimal("0")
        all_keys = set(batch_by_key) | set(source_by_key)
        for key in sorted(all_keys, key=lambda k: (k[1] or "", k[0])):
            b_hours, rid, worker = batch_by_key.get(key, (Decimal("0"), None, key[0]))
            s_hours = source_by_key.get(key, Decimal("0"))
            delta = (b_hours - s_hours).quantize(Decimal("0.01"))
            batch_total += b_hours
            source_total += s_hours
            rows.append(
                {
                    "worker_key": worker,
                    "work_date": key[1],
                    "resource_id": rid,
                    "batch_hours": str(b_hours.quantize(Decimal("0.01"))),
                    "source_hours": str(s_hours.quantize(Decimal("0.01"))),
                    "delta_hours": str(delta),
                    "matched": delta == 0,
                }
            )

        delta_total = (batch_total - source_total).quantize(Decimal("0.01"))
        return {
            "batch_id": batch.id,
            "project_id": batch.project_id,
            "batch_total_hours": str(batch_total.quantize(Decimal("0.01"))),
            "source_total_hours": str(source_total.quantize(Decimal("0.01"))),
            "delta_total_hours": str(delta_total),
            "balanced": delta_total == 0,
            "rows": rows,
        }

    # ── Export (ERP handoff) ─────────────────────────────────────────────────

    async def export_rows(self, batch_id: uuid.UUID) -> tuple[PayrollBatch, list[dict]]:
        """Return the batch plus its export rows (used by JSON and CSV export).

        Each row carries gross ``amount``, the summed ``deductions`` and the
        resulting ``net_amount`` so the payroll-provider handoff includes what
        each worker is actually paid, not only gross.
        """
        batch = await self.get_batch(batch_id)
        entries = await self.entry_repo.list_for_batch(batch_id)
        by_entry = await self.deduction_repo.list_for_entries([e.id for e in entries])
        rows = []
        for e in entries:
            ded_total = Decimal("0")
            for ded in by_entry.get(e.id, []):
                ded_total += _to_decimal(ded.amount)
            rows.append(
                {
                    "worker": e.worker,
                    "resource_id": str(e.resource_id) if e.resource_id else "",
                    "work_date": e.work_date or "",
                    "hours": e.hours,
                    "rate": e.rate,
                    "amount": e.amount,
                    "deductions": str(ded_total.quantize(_MONEY_Q)),
                    "net_amount": e.net_amount,
                    "currency": e.currency,
                    "source": e.source,
                }
            )
        return batch, rows

    # ── Labour cost rollup (for surfacing alongside the cost model) ──────────

    async def labour_cost(
        self,
        project_id: uuid.UUID,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> tuple[Decimal, Decimal, str]:
        """Return ``(labour_cost_base, total_hours, base_currency)`` live.

        A read-only mirror of the generation math - lets the UI show a
        "Labour cost" figure without persisting a batch.
        """
        source_rows = await self._collect_all_labour_sources(project_id, date_from=date_from, date_to=date_to)
        agg_rows, base, fx = await self._aggregate(project_id, source_rows)

        total_hours = Decimal("0")
        total_amount = Decimal("0")
        for agg in agg_rows:
            amount_native = agg.hours * agg.rate
            total_amount += _amount_in_base(str(amount_native), agg.currency, base, fx)
            total_hours += agg.hours
        return total_amount.quantize(Decimal("0.01")), total_hours.quantize(Decimal("0.01")), base
