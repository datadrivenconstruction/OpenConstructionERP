# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Variations data access layer (one repository class per entity)."""

from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

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

T = TypeVar("T")

# Trailing digits of a daywork sheet number, e.g. the "0042" of "DW-0042".
_SHEET_NUMBER_RE = re.compile(r"(\d+)\s*$")


def _to_decimal(value: object) -> Decimal:
    """Coerce a stored money value (Decimal / str / None) to exact Decimal.

    Routes via ``str()`` so a stray legacy float doesn't poison the
    rollup with 0.1 -> 0.10000000000000000555... imprecision. Bad input
    silently degrades to ``Decimal('0')`` so a single malformed row
    doesn't blow up a project-wide dashboard endpoint. Mirrors
    ``changeorders/repository.py::_to_decimal``.
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _project_fx_map(project: object | None) -> dict[str, Decimal]:
    """Project ``Project.fx_rates`` into ``{CODE: rate}`` as exact Decimals.

    Mirrors ``changeorders/repository.py::_project_fx_map`` and
    ``boq/service.py::_project_fx_map`` (shape
    ``[{"code": "USD", "rate": "1.08", "label": "US Dollar"}]`` where
    ``rate`` is BASE units per 1 unit of the foreign currency). Defensive
    against missing attribute / malformed entries -- a bad row is skipped
    rather than blowing up the dashboard endpoint.
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


class _BaseRepo:
    """Shared CRUD helpers - concrete repos bind ``model`` and ``project_field``."""

    model: Any
    # Column NAME (str), not the mapped attribute. Storing the
    # InstrumentedAttribute (e.g. ``Notice.project_id``) as a class
    # attribute turns it into a descriptor: accessing ``self.project_field``
    # then invokes SQLAlchemy's ``__get__`` with the *repository* instance
    # and raises ``UnmappedInstanceError``. Resolve the real column lazily
    # via ``getattr(self.model, self.project_field)`` instead.
    project_field: str | None = None

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, row_id: uuid.UUID) -> Any | None:
        return await self.session.get(self.model, row_id)

    async def create(self, row: Any) -> Any:
        self.session.add(row)
        await self.session.flush()
        return row

    async def update_fields(self, row_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(self.model).where(self.model.id == row_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(self.model, row_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, row_id: uuid.UUID) -> None:
        row = await self.get_by_id(row_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        if self.project_field is None:  # pragma: no cover -- defensive
            return [], 0
        col = getattr(self.model, self.project_field)
        base = select(self.model).where(col == project_id)
        if status is not None:
            base = base.where(self.model.status == status)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = base.order_by(self.model.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def status_counts(self, project_id: uuid.UUID) -> dict[str, int]:
        """``{status: count}`` for the project - one ``GROUP BY`` query.

        Used by the dashboard so it does not pull every row into Python
        just to bucket by status (N+1 / O(rows) memory).
        """
        if self.project_field is None:  # pragma: no cover -- defensive
            return {}
        col = getattr(self.model, self.project_field)
        stmt = select(self.model.status, func.count()).where(col == project_id).group_by(self.model.status)
        rows = (await self.session.execute(stmt)).all()
        return {str(s): int(c) for s, c in rows}


class NoticeRepository(_BaseRepo):
    model = Notice
    project_field = "project_id"

    async def next_code(self, project_id: uuid.UUID) -> str:
        stmt = select(func.count()).select_from(Notice).where(Notice.project_id == project_id)
        count = (await self.session.execute(stmt)).scalar_one()
        return f"NOT-{count + 1:04d}"


class VariationRequestRepository(_BaseRepo):
    model = VariationRequest
    project_field = "project_id"

    async def next_code(self, project_id: uuid.UUID) -> str:
        stmt = select(func.count()).select_from(VariationRequest).where(VariationRequest.project_id == project_id)
        count = (await self.session.execute(stmt)).scalar_one()
        return f"VR-{count + 1:04d}"

    async def list_open(self, project_id: uuid.UUID) -> list[VariationRequest]:
        stmt = select(VariationRequest).where(
            VariationRequest.project_id == project_id,
            VariationRequest.status.in_(["draft", "submitted", "under_review"]),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class VariationBOQTraceRepository(_BaseRepo):
    """Provenance rows for the lines of a variation request's own bill."""

    model = VariationBOQTrace
    project_field = None

    async def bulk_create(self, rows: list[VariationBOQTrace]) -> list[VariationBOQTrace]:
        """Insert a batch of trace rows in one flush."""
        if not rows:
            return []
        self.session.add_all(rows)
        await self.session.flush()
        return rows

    async def get_for_position(self, position_id: uuid.UUID) -> VariationBOQTrace | None:
        """The one trace row about a line, or ``None`` if it has none.

        At most one can exist - ``uq_oe_variations_boq_trace_position`` says
        so - which is why setting a line's provenance is an update of this row
        when it is there and an insert when it is not.
        """
        stmt = select(VariationBOQTrace).where(VariationBOQTrace.position_id == position_id)
        return (await self.session.execute(stmt)).scalars().one_or_none()

    async def list_for_request(self, variation_request_id: uuid.UUID) -> list[VariationBOQTrace]:
        """Every trace row of a request, oldest first."""
        stmt = (
            select(VariationBOQTrace)
            .where(VariationBOQTrace.variation_request_id == variation_request_id)
            .order_by(VariationBOQTrace.created_at, VariationBOQTrace.id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_boq(self, boq_id: uuid.UUID) -> list[VariationBOQTrace]:
        """Every trace row belonging to one bill, oldest first."""
        stmt = (
            select(VariationBOQTrace)
            .where(VariationBOQTrace.boq_id == boq_id)
            .order_by(VariationBOQTrace.created_at, VariationBOQTrace.id)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class VariationOrderRepository(_BaseRepo):
    model = VariationOrder
    project_field = "project_id"

    async def next_code(self, project_id: uuid.UUID) -> str:
        stmt = select(func.count()).select_from(VariationOrder).where(VariationOrder.project_id == project_id)
        count = (await self.session.execute(stmt)).scalar_one()
        return f"VO-{count + 1:04d}"

    async def list_open_variations(self, project_id: uuid.UUID) -> list[VariationOrder]:
        stmt = select(VariationOrder).where(
            VariationOrder.project_id == project_id,
            VariationOrder.status.in_(["issued", "in_progress"]),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all_for_project(self, project_id: uuid.UUID) -> list[VariationOrder]:
        stmt = select(VariationOrder).where(VariationOrder.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_valued_for_project(
        self,
        project_id: uuid.UUID,
    ) -> list[VariationOrder]:
        """VOs that count toward the contract sum (everything but voided).

        A voided VO carries no commercial value - including it in the
        final-account / dashboard roll-up overstates the revised contract
        sum.
        """
        stmt = select(VariationOrder).where(
            VariationOrder.project_id == project_id,
            VariationOrder.status != "voided",
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def first_currency(self, project_id: uuid.UUID) -> str:
        """First non-empty VO currency for the project (dashboard label)."""
        stmt = (
            select(VariationOrder.currency)
            .where(
                VariationOrder.project_id == project_id,
                VariationOrder.currency != "",
            )
            .order_by(VariationOrder.created_at.asc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first() or ""

    async def cost_impact_sum(self, project_id: uuid.UUID) -> Decimal:
        """SQL ``SUM(final_cost_impact)`` over non-voided VOs (no N+1)."""
        stmt = select(func.coalesce(func.sum(VariationOrder.final_cost_impact), 0)).where(
            VariationOrder.project_id == project_id,
            VariationOrder.status != "voided",
        )
        val = (await self.session.execute(stmt)).scalar_one()
        return Decimal(str(val or 0))

    async def cost_impact_by_currency(self, project_id: uuid.UUID) -> dict[str, Decimal]:
        """``{currency_code: SUM(final_cost_impact)}`` over non-voided VOs.

        Currency bug fix: the scalar ``cost_impact_sum`` blends VOs of
        different ISO currencies into one number, which is meaningless
        across currencies. Grouping by the per-row ``currency`` keeps each
        currency's total separate so the dashboard can FX-convert to the
        project base currency (when a rate exists) or surface the buckets
        honestly. Rows with a blank currency are keyed under ``""`` (the
        caller treats blank as "already in the project base currency").
        """
        stmt = (
            select(
                VariationOrder.currency,
                func.coalesce(func.sum(VariationOrder.final_cost_impact), 0),
            )
            .where(
                VariationOrder.project_id == project_id,
                VariationOrder.status != "voided",
            )
            .group_by(VariationOrder.currency)
        )
        rows = (await self.session.execute(stmt)).all()
        return {str(code or ""): _to_decimal(total) for code, total in rows}

    async def schedule_days_sum(self, project_id: uuid.UUID) -> int:
        """SQL ``SUM(final_schedule_days)`` over non-voided VOs (no N+1)."""
        stmt = select(func.coalesce(func.sum(VariationOrder.final_schedule_days), 0)).where(
            VariationOrder.project_id == project_id,
            VariationOrder.status != "voided",
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)


class VariationCostImpactRepository(_BaseRepo):
    model = VariationCostImpact

    async def list_for_order(self, vo_id: uuid.UUID) -> list[VariationCostImpact]:
        stmt = select(VariationCostImpact).where(VariationCostImpact.variation_order_id == vo_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class VariationScheduleImpactRepository(_BaseRepo):
    model = VariationScheduleImpact

    async def list_for_order(self, vo_id: uuid.UUID) -> list[VariationScheduleImpact]:
        stmt = select(VariationScheduleImpact).where(VariationScheduleImpact.variation_order_id == vo_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class SiteMeasurementRepository(_BaseRepo):
    model = SiteMeasurement
    project_field = "project_id"


class DayworkSheetRepository(_BaseRepo):
    model = DayworkSheet
    project_field = "project_id"

    async def next_sheet_number(self, project_id: uuid.UUID) -> str:
        """Return the next per-project sheet number, e.g. ``DW-0042``.

        Derived from the highest numeric suffix already used in the project, not
        from the row count. A count only produces a free number while the
        existing numbers run 1..n with no gaps, and they do not have to: a
        deleted sheet, or a sheet numbered by anything other than this method,
        leaves a count that points at a number already taken. The
        ``(project_id, sheet_number)`` unique constraint then rejects the
        insert, which on PostgreSQL takes the caller's whole transaction down
        with it.
        """
        stmt = select(DayworkSheet.sheet_number).where(DayworkSheet.project_id == project_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        highest = 0
        for number in rows:
            match = _SHEET_NUMBER_RE.search(number or "")
            if match:
                highest = max(highest, int(match.group(1)))
        return f"DW-{highest + 1:04d}"

    async def list_signed(self, project_id: uuid.UUID) -> list[DayworkSheet]:
        stmt = select(DayworkSheet).where(
            DayworkSheet.project_id == project_id,
            DayworkSheet.status.in_(["signed", "billed"]),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def signed_value(self, project_id: uuid.UUID) -> Decimal:
        """SQL ``SUM(total_amount)`` over signed/billed sheets (no N+1)."""
        stmt = select(func.coalesce(func.sum(DayworkSheet.total_amount), 0)).where(
            DayworkSheet.project_id == project_id,
            DayworkSheet.status.in_(["signed", "billed"]),
        )
        val = (await self.session.execute(stmt)).scalar_one()
        return Decimal(str(val or 0))

    async def signed_value_by_currency(self, project_id: uuid.UUID) -> dict[str, Decimal]:
        """``{currency_code: SUM(total_amount)}`` over signed/billed sheets.

        Currency bug fix: the scalar ``signed_value`` blends daywork
        sheets of different ISO currencies into one number. Grouping by
        the per-row ``currency`` keeps each currency separate so the
        dashboard can FX-convert to the project base currency (when a rate
        exists) or surface the buckets honestly. Blank currency keys under
        ``""``.
        """
        stmt = (
            select(
                DayworkSheet.currency,
                func.coalesce(func.sum(DayworkSheet.total_amount), 0),
            )
            .where(
                DayworkSheet.project_id == project_id,
                DayworkSheet.status.in_(["signed", "billed"]),
            )
            .group_by(DayworkSheet.currency)
        )
        rows = (await self.session.execute(stmt)).all()
        return {str(code or ""): _to_decimal(total) for code, total in rows}

    async def first_currency(self, project_id: uuid.UUID) -> str:
        """First non-empty daywork currency for the project."""
        stmt = (
            select(DayworkSheet.currency)
            .where(
                DayworkSheet.project_id == project_id,
                DayworkSheet.currency != "",
            )
            .order_by(DayworkSheet.created_at.asc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first() or ""


class DayworkSheetLineRepository(_BaseRepo):
    model = DayworkSheetLine

    async def list_for_sheet(self, sheet_id: uuid.UUID) -> list[DayworkSheetLine]:
        stmt = select(DayworkSheetLine).where(DayworkSheetLine.sheet_id == sheet_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class DisruptionClaimRepository(_BaseRepo):
    model = DisruptionClaim
    project_field = "project_id"

    async def pending_claims(self, project_id: uuid.UUID) -> list[DisruptionClaim]:
        stmt = select(DisruptionClaim).where(
            DisruptionClaim.project_id == project_id,
            DisruptionClaim.status.in_(["submitted", "under_review"]),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def pending_count(self, project_id: uuid.UUID) -> int:
        """R5 audit: ``COUNT(*)`` over pending claims - dashboard-friendly.

        Replaces ``len(await pending_claims(...))`` which materialises the
        full result set just to discard the rows.
        """
        stmt = (
            select(func.count())
            .select_from(DisruptionClaim)
            .where(
                DisruptionClaim.project_id == project_id,
                DisruptionClaim.status.in_(["submitted", "under_review"]),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)


class ExtensionOfTimeClaimRepository(_BaseRepo):
    model = ExtensionOfTimeClaim
    project_field = "project_id"

    async def pending_claims(self, project_id: uuid.UUID) -> list[ExtensionOfTimeClaim]:
        stmt = select(ExtensionOfTimeClaim).where(
            ExtensionOfTimeClaim.project_id == project_id,
            ExtensionOfTimeClaim.status.in_(["submitted", "under_review"]),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def pending_count(self, project_id: uuid.UUID) -> int:
        """R5 audit: ``COUNT(*)`` over pending EOT claims. See DisruptionClaim."""
        stmt = (
            select(func.count())
            .select_from(ExtensionOfTimeClaim)
            .where(
                ExtensionOfTimeClaim.project_id == project_id,
                ExtensionOfTimeClaim.status.in_(["submitted", "under_review"]),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)


class FinalAccountRepository(_BaseRepo):
    model = FinalAccount
    project_field = "project_id"

    async def for_project(self, project_id: uuid.UUID) -> FinalAccount | None:
        stmt = select(FinalAccount).where(FinalAccount.project_id == project_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()
