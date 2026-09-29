# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Change Order data access layer.

All database queries for change orders live here.
No business logic - pure data access.
"""

import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.core.orm_write import apply_update
from app.modules.changeorders.models import ChangeOrder, ChangeOrderItem


def _to_decimal(value: object) -> Decimal:
    """Coerce a stored money value (Decimal / str / None) to exact Decimal.

    Routes via ``str()`` so a stray legacy float doesn't poison the
    rollup with 0.1 → 0.10000000000000000555… imprecision. Bad input
    silently degrades to ``Decimal('0')`` so a single malformed row
    doesn't blow up a project-wide summary endpoint.
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

    Mirrors ``boq/service.py::_project_fx_map`` (shape
    ``[{"code": "USD", "rate": "1.08", "label": "US Dollar"}]`` where
    ``rate`` is BASE units per 1 unit of the foreign currency). Defensive
    against missing attribute / malformed entries - a bad row is skipped
    rather than blowing up the summary endpoint.
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


class ChangeOrderRepository:
    """Data access for ChangeOrder and ChangeOrderItem models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── ChangeOrder ──────────────────────────────────────────────────────

    async def get_by_id(self, order_id: uuid.UUID) -> ChangeOrder | None:
        """Get change order by ID (includes items via selectin)."""
        return await self.session.get(ChangeOrder, order_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[ChangeOrder], int]:
        """List change orders for a project with pagination."""
        base = select(ChangeOrder).where(ChangeOrder.project_id == project_id)
        if status is not None:
            base = base.where(ChangeOrder.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Eager-load items so the response builder's ``len(order.items)`` and
        # per-item rendering don't trigger one extra round-trip per row. Was
        # ~50 extra queries on a default page (limit=50).
        stmt = (
            base.order_by(ChangeOrder.created_at.desc())
            .options(selectinload(ChangeOrder.items))
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        orders = list(result.scalars().all())

        return orders, total

    async def list_for_owner(
        self,
        owner_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[ChangeOrder], int]:
        """List change orders across every project the user can access.

        Used when the API caller omits ``project_id``: we scope to the
        caller's own projects rather than 422-ing. "Accessible" means the
        user OWNS the project OR is a TeamMembership member - matching
        ``verify_project_access`` (the per-project list path), so the two
        list routes agree instead of silently returning zero rows to a
        non-owner team member.
        """
        from sqlalchemy import or_

        from app.modules.projects.models import Project
        from app.modules.teams.access import member_project_ids_subquery

        base = (
            select(ChangeOrder)
            .join(Project, Project.id == ChangeOrder.project_id)
            .where(
                or_(
                    Project.owner_id == owner_id,
                    Project.id.in_(member_project_ids_subquery(owner_id)),
                ),
                # Change orders of a deleted (archived) project are not
                # listed; the per-project route 404s on that project too.
                Project.status != "archived",
            )
        )
        if status is not None:
            base = base.where(ChangeOrder.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            base.order_by(ChangeOrder.created_at.desc())
            .options(selectinload(ChangeOrder.items))
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, order: ChangeOrder) -> ChangeOrder:
        """Insert a new change order."""
        self.session.add(order)
        await self.session.flush()
        return order

    async def update_fields(self, order_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a change order."""
        stmt = update(ChangeOrder).where(ChangeOrder.id == order_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(ChangeOrder, order_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, order_id: uuid.UUID) -> None:
        """Hard delete a change order and its items."""
        order = await self.get_by_id(order_id)
        if order is not None:
            await self.session.delete(order)
            await self.session.flush()

    async def count_for_project(self, project_id: uuid.UUID) -> int:
        """Count change orders for a project (used for code generation)."""
        stmt = select(func.count()).select_from(
            select(ChangeOrder).where(ChangeOrder.project_id == project_id).subquery()
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def get_summary(self, project_id: uuid.UUID) -> dict[str, object]:
        """Aggregate change order stats for a project."""
        from app.modules.projects.models import Project

        base = select(ChangeOrder).where(ChangeOrder.project_id == project_id)
        result = await self.session.execute(base)
        orders = list(result.scalars().all())

        draft_count = 0
        submitted_count = 0
        approved_count = 0
        rejected_count = 0
        # Money rollups stay in Decimal end-to-end: a CO summary feeds
        # both KPI dashboards and procurement reports, where a single
        # float-arithmetic drift becomes a contract dispute.
        total_cost_impact: Decimal = Decimal("0")
        total_approved_amount: Decimal = Decimal("0")
        total_schedule_impact_days = 0
        total_time_impact_days = 0
        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}
        # The summary total is always expressed in the project's BASE
        # currency. Foreign-currency change orders are converted via the
        # project's ``fx_rates`` table before being summed - NEVER blended
        # raw (money rule). A CO whose currency is foreign AND has no FX
        # rate is excluded from the scalar total and surfaced separately
        # under ``unconverted_by_currency`` so the figure is honest rather
        # than silently mis-stamped with whichever currency was seen last.
        project = (await self.session.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        base_currency = (getattr(project, "currency", "") if project is not None else "") or ""
        base_code = base_currency.strip().upper()
        fx_map = _project_fx_map(project)
        # Approved foreign amounts with no FX rate, grouped by their own
        # currency so the UI can show "+ 5,000.00 USD (no rate)" alongside
        # the base-currency total.
        unconverted: dict[str, Decimal] = {}

        for order in orders:
            # by_status aggregation
            by_status[order.status] = by_status.get(order.status, 0) + 1

            # by_type aggregation (reason_category)
            rcat = order.reason_category or "other"
            by_type[rcat] = by_type.get(rcat, 0) + 1

            if order.status == "draft":
                draft_count += 1
            elif order.status == "submitted":
                submitted_count += 1
            elif order.status == "approved":
                approved_count += 1
                # Only approved orders count toward total cost/schedule impact.
                # Decimal - never ``float`` - because a CO summary is the
                # signed-off scope-change KPI that flows into the project
                # budget and downstream reporting; a binary-float drift
                # (e.g. 0.1 + 0.2 → 0.30000000000000004) here becomes a
                # KPI/UI mismatch a project manager can't reconcile.
                raw_delta = _to_decimal(order.cost_impact)
                co_code = (order.currency or "").strip().upper()
                if not co_code or co_code == base_code:
                    # Already in the project base currency.
                    total_cost_impact += raw_delta
                    total_approved_amount += raw_delta
                else:
                    fx = fx_map.get(co_code)
                    if fx is not None:
                        converted = raw_delta * fx
                        total_cost_impact += converted
                        total_approved_amount += converted
                    else:
                        # Foreign currency with no FX rate - never fold it
                        # into the base total. Keep it visible per-currency
                        # so the user knows to add the rate in Project
                        # Settings rather than seeing a silently wrong sum.
                        unconverted[co_code] = unconverted.get(co_code, Decimal("0")) + raw_delta
                total_schedule_impact_days += order.schedule_impact_days or 0
                # ``time_impact_days`` is the dedicated variation column;
                # it was previously (incorrectly) summing
                # ``schedule_impact_days`` into the time total. Prefer the
                # variation field, falling back to the schedule impact when
                # the variation workflow isn't used so the figure is never
                # silently zero for plain change orders.
                time_days = getattr(order, "time_impact_days", None)
                if time_days is None:
                    time_days = order.schedule_impact_days
                total_time_impact_days += time_days or 0
            elif order.status == "rejected":
                rejected_count += 1

        # The summary currency is the project BASE currency - not the last
        # CO seen. This is the only currency the scalar total is expressed in.
        currency = base_currency

        # Money values stay as exact Decimals - the schema layer formats
        # them as canonical decimal strings ("100.35"). Quantising to 2dp
        # at the persist/expose boundary mirrors finance / procurement
        # conventions and keeps the wire format stable.
        from decimal import ROUND_HALF_UP

        _CENTS = Decimal("0.01")
        # Foreign approved amounts that couldn't be converted (no FX rate),
        # quantised + grouped by their own ISO code so the UI can show them
        # alongside - never inside - the base-currency total.
        unconverted_by_currency = {
            code: format(amount.quantize(_CENTS, rounding=ROUND_HALF_UP), "f")
            for code, amount in sorted(unconverted.items())
        }
        return {
            "total": len(orders),
            "total_orders": len(orders),
            "by_status": by_status,
            "by_type": by_type,
            "draft_count": draft_count,
            "submitted_count": submitted_count,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "total_approved_amount": total_approved_amount.quantize(_CENTS, rounding=ROUND_HALF_UP),
            "total_cost_impact": total_cost_impact.quantize(_CENTS, rounding=ROUND_HALF_UP),
            "total_time_impact_days": total_time_impact_days,
            "total_schedule_impact_days": total_schedule_impact_days,
            "currency": currency,
            "unconverted_by_currency": unconverted_by_currency,
        }

    # ── ChangeOrderItem ──────────────────────────────────────────────────

    async def get_item_by_id(self, item_id: uuid.UUID) -> ChangeOrderItem | None:
        """Get a change order item by ID."""
        return await self.session.get(ChangeOrderItem, item_id)

    async def create_item(self, item: ChangeOrderItem) -> ChangeOrderItem:
        """Insert a new change order item."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_item_fields(self, item_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a change order item."""
        await apply_update(self.session, ChangeOrderItem, item_id, **fields)

    async def delete_item(self, item_id: uuid.UUID) -> None:
        """Hard delete a change order item."""
        item = await self.get_item_by_id(item_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()

    async def list_items_for_order(self, order_id: uuid.UUID) -> list[ChangeOrderItem]:
        """List all items for a change order."""
        stmt = (
            select(ChangeOrderItem)
            .where(ChangeOrderItem.change_order_id == order_id)
            .order_by(ChangeOrderItem.sort_order)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
