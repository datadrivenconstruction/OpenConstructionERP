"""Change Order service — business logic for change order management.

Stateless service layer. Handles:
- Change order CRUD with auto-generated codes
- Item management with cost_delta calculation
- Status transitions (draft -> submitted -> approved/rejected)
- Cost impact recalculation from items
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.changeorders.models import ChangeOrder, ChangeOrderItem
from app.modules.changeorders.repository import ChangeOrderRepository
from app.modules.changeorders.schemas import (
    ChangeOrderCreate,
    ChangeOrderItemCreate,
    ChangeOrderItemUpdate,
    ChangeOrderUpdate,
)

logger = logging.getLogger(__name__)


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    """Fire-and-forget event publish. Swallows errors so a transient event
    bus outage never breaks the main transaction."""
    try:
        await event_bus.publish(name, data, source_module=source_module)
    except Exception:
        logger.debug("Event publish skipped: %s", name)


# Valid status transitions
VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["submitted"],
    "submitted": ["approved", "rejected", "draft"],
    "approved": [],
    "rejected": ["draft"],
}


class ChangeOrderService:
    """Business logic for change order operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ChangeOrderRepository(session)

    # ── Create ────────────────────────────────────────────────────────────

    async def create_order(self, data: ChangeOrderCreate) -> ChangeOrder:
        """Create a new change order with auto-generated code.

        BUG-354 race condition: ``count + 1`` is not atomic — two concurrent
        creates could both read ``count=4`` and both emit ``CO-005``. We
        retry on integrity-error (unique-constraint violation) by re-reading
        the current max ordinal from the DB and bumping from there. After
        ``_MAX_RETRIES`` collisions we surface the error rather than looping
        forever.
        """
        from sqlalchemy.exc import IntegrityError

        _MAX_RETRIES = 5

        # BUG-385 follow-up: ``cost_impact`` was silently dropped at create
        # time because it wasn't threaded into the ORM constructor here.
        # The schema now accepts it (added alongside Phase 1); this picks
        # it up so manual-entry COs persist their headline amount. When
        # line items are added later ``add_item`` recomputes the total via
        # ``_recalculate_cost_impact``, so a line-based CO still ends up
        # with the correct sum.
        from decimal import Decimal, InvalidOperation

        try:
            initial_cost_impact = (
                Decimal(str(data.cost_impact)) if data.cost_impact else Decimal("0")
            )
        except (InvalidOperation, ValueError, TypeError):
            initial_cost_impact = Decimal("0")

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            count = await self.repo.count_for_project(data.project_id)
            code = f"CO-{count + 1 + attempt:03d}"

            order = ChangeOrder(
                project_id=data.project_id,
                code=code,
                title=data.title,
                description=data.description,
                reason_category=data.reason_category,
                schedule_impact_days=data.schedule_impact_days,
                currency=data.currency,
                cost_impact=initial_cost_impact,
                metadata_=data.metadata,
            )
            try:
                order = await self.repo.create(order)
                logger.info(
                    "Change order created: %s for project %s (attempt %d)",
                    code,
                    data.project_id,
                    attempt + 1,
                )
                return order
            except IntegrityError as exc:
                # Another transaction picked the same code. Roll back and
                # retry with a bumped ordinal.
                last_exc = exc
                await self.session.rollback()
                continue

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Could not generate a unique change-order code after "
                f"{_MAX_RETRIES} attempts (concurrent contention). Please retry."
            ),
        ) from last_exc

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_order(self, order_id: uuid.UUID) -> ChangeOrder:
        """Get change order by ID. Raises 404 if not found."""
        order = await self.repo.get_by_id(order_id)
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Change order not found",
            )
        return order

    async def list_orders(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
    ) -> tuple[list[ChangeOrder], int]:
        """List change orders for a project."""
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
        )

    async def get_summary(self, project_id: uuid.UUID) -> dict:
        """Get aggregated stats for a project's change orders."""
        return await self.repo.get_summary(project_id)

    # ── Update ────────────────────────────────────────────────────────────

    async def update_order(
        self,
        order_id: uuid.UUID,
        data: ChangeOrderUpdate,
    ) -> ChangeOrder:
        """Update change order fields. Only draft orders can be edited."""
        order = await self.get_order(order_id)

        if order.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft change orders can be edited",
            )

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return order

        await self.repo.update_fields(order_id, **fields)
        await self.session.refresh(order)

        logger.info("Change order updated: %s (fields=%s)", order_id, list(fields.keys()))
        return order

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_order(self, order_id: uuid.UUID) -> None:
        """Delete a change order. Only draft orders can be deleted."""
        order = await self.get_order(order_id)

        if order.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft change orders can be deleted",
            )

        await self.repo.delete(order_id)
        logger.info("Change order deleted: %s", order_id)

    # ── Status transitions ────────────────────────────────────────────────

    async def _assert_not_self_approval(
        self,
        order: "ChangeOrder",
        user_id: str,
        action: str,
    ) -> None:
        """BUG-353: prevent the same user who submitted from approving / rejecting.

        Self-approval is a classic four-eyes-principle violation — in
        construction it means a site manager could both request and sign
        off a scope change without anyone else seeing it. Enforced at
        service layer so router shortcuts don't bypass it.
        """
        if order.submitted_by and str(order.submitted_by) == str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"You cannot {action} a change order you submitted yourself "
                    "(four-eyes principle)."
                ),
            )

    async def submit_order(self, order_id: uuid.UUID, user_id: str) -> ChangeOrder:
        """Submit a change order for approval."""
        order = await self.get_order(order_id)
        self._validate_transition(order.status, "submitted")

        now = datetime.now(UTC).isoformat()[:19]
        await self.repo.update_fields(
            order_id,
            status="submitted",
            submitted_by=user_id,
            submitted_at=now,
        )
        await self.session.refresh(order)

        logger.info("Change order submitted: %s by %s", order.code, user_id)
        return order

    async def approve_order(self, order_id: uuid.UUID, user_id: str) -> ChangeOrder:
        """Approve a submitted change order.

        On approval the order's ``cost_impact`` is applied to
        ``project.budget_estimate`` so downstream EVM / reporting reflect the
        new contractual commitment. A ``changeorder.approved`` event is
        published so other modules (budget dashboards, notifications) can
        react without coupling directly to this service.
        """
        from decimal import Decimal, InvalidOperation

        from sqlalchemy import select

        from app.modules.projects.models import Project

        order = await self.get_order(order_id)
        # Idempotent: re-approving an already-approved change order is a
        # no-op (ENH-095). Prevents double budget-writeback if a client
        # retries an approval call after a flaky network round-trip.
        if order.status == "approved":
            return order
        await self._assert_not_self_approval(order, user_id, "approve")
        self._validate_transition(order.status, "approved")

        # Snapshot fields that are safe to use in the event payload later
        # (update_fields calls expire_all).
        project_id_s = str(order.project_id)
        code_s = order.code
        cost_impact_s = order.cost_impact or "0"

        now = datetime.now(UTC).isoformat()[:19]
        await self.repo.update_fields(
            order_id,
            status="approved",
            approved_by=user_id,
            approved_at=now,
        )

        # Writeback: project.budget_estimate += cost_impact. Stored as string
        # to keep Decimal precision regardless of DB backend.
        try:
            delta = Decimal(str(cost_impact_s))
        except (InvalidOperation, ValueError):
            delta = Decimal("0")
        project_updated = False
        if delta != 0:
            project = (
                await self.session.execute(
                    select(Project).where(Project.id == order.project_id)
                )
            ).scalar_one_or_none()
            if project is not None:
                try:
                    current = Decimal(str(project.budget_estimate)) if project.budget_estimate else Decimal("0")
                except (InvalidOperation, ValueError):
                    current = Decimal("0")
                project.budget_estimate = str(current + delta)
                project_updated = True
                await self.session.flush()

        await _safe_publish(
            "changeorder.approved",
            {
                "change_order_id": str(order_id),
                "project_id": project_id_s,
                "code": code_s,
                "cost_impact": str(delta),
                "approved_by": user_id,
                "project_budget_updated": project_updated,
            },
            source_module="oe_changeorders",
        )

        fresh = await self.repo.get_by_id(order_id)
        logger.info("Change order approved: %s by %s (delta=%s)", code_s, user_id, delta)
        return fresh or order

    async def reject_order(self, order_id: uuid.UUID, user_id: str) -> ChangeOrder:
        """Reject a submitted change order.

        BUG-351: writes to dedicated ``rejected_by`` / ``rejected_at`` fields
        rather than reusing the ``approved_*`` columns. Audit trails and
        dashboards now show "rejected by X" instead of "approved by X"
        when a CO is refused.
        """
        order = await self.get_order(order_id)
        await self._assert_not_self_approval(order, user_id, "reject")
        self._validate_transition(order.status, "rejected")

        now = datetime.now(UTC).isoformat()[:19]
        await self.repo.update_fields(
            order_id,
            status="rejected",
            rejected_by=user_id,
            rejected_at=now,
        )
        fresh = await self.repo.get_by_id(order_id)

        logger.info(
            "Change order rejected: %s by %s",
            (fresh or order).code,
            user_id,
        )
        return fresh or order

    def _validate_transition(self, current: str, target: str) -> None:
        """Validate a status transition."""
        allowed = VALID_TRANSITIONS.get(current, [])
        if target not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot transition from '{current}' to '{target}'",
            )

    # ── Items ─────────────────────────────────────────────────────────────

    async def add_item(
        self,
        order_id: uuid.UUID,
        data: ChangeOrderItemCreate,
    ) -> ChangeOrderItem:
        """Add an item to a change order and recalculate cost impact."""
        order = await self.get_order(order_id)

        # BUG-352: items are frozen once a CO leaves ``draft``. A submitted
        # CO represents a commitment already under review by the other
        # party, so silently mutating its line items is a contractual
        # integrity hazard. Revert to draft via an explicit transition if
        # changes are needed.
        if order.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Items can only be modified while change order is in 'draft' status",
            )

        # Capture identifying fields BEFORE the recalculation. update_fields
        # expires the session, so accessing `order.code` afterwards would
        # trigger a lazy load and crash with MissingGreenlet in async context.
        order_code = order.code

        cost_delta = (data.new_quantity * data.new_rate) - (data.original_quantity * data.original_rate)

        item = ChangeOrderItem(
            change_order_id=order_id,
            description=data.description,
            change_type=data.change_type,
            original_quantity=str(data.original_quantity),
            new_quantity=str(data.new_quantity),
            original_rate=str(data.original_rate),
            new_rate=str(data.new_rate),
            cost_delta=str(round(cost_delta, 2)),
            unit=data.unit,
            sort_order=data.sort_order,
            metadata_=data.metadata,
        )
        item = await self.repo.create_item(item)

        await self._recalculate_cost_impact(order_id)

        # _recalculate_cost_impact expires all session objects, so the freshly
        # created item's attributes are stale — refresh before returning so the
        # router can build the response without lazy-loading.
        await self.session.refresh(item)

        logger.info("Item added to change order %s: %s", order_code, data.description[:40])
        return item

    async def update_item(
        self,
        order_id: uuid.UUID,
        item_id: uuid.UUID,
        data: ChangeOrderItemUpdate,
    ) -> ChangeOrderItem:
        """Update an item and recalculate cost impact."""
        order = await self.get_order(order_id)

        # BUG-352: items are frozen once a CO leaves ``draft``. A submitted
        # CO represents a commitment already under review by the other
        # party, so silently mutating its line items is a contractual
        # integrity hazard. Revert to draft via an explicit transition if
        # changes are needed.
        if order.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Items can only be modified while change order is in 'draft' status",
            )

        item = await self.repo.get_item_by_id(item_id)
        if item is None or item.change_order_id != order_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Change order item not found",
            )

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Recalculate cost_delta if quantities or rates changed
        orig_qty = fields.get("original_quantity", float(item.original_quantity))
        new_qty = fields.get("new_quantity", float(item.new_quantity))
        orig_rate = fields.get("original_rate", float(item.original_rate))
        new_rate = fields.get("new_rate", float(item.new_rate))

        if any(k in fields for k in ("original_quantity", "new_quantity", "original_rate", "new_rate")):
            cost_delta = (new_qty * new_rate) - (orig_qty * orig_rate)
            fields["cost_delta"] = str(round(cost_delta, 2))

        # Convert float fields to strings for storage
        for key in ("original_quantity", "new_quantity", "original_rate", "new_rate"):
            if key in fields:
                fields[key] = str(fields[key])

        if fields:
            await self.repo.update_item_fields(item_id, **fields)
            await self._recalculate_cost_impact(order_id)
            await self.session.refresh(item)

        return item

    async def delete_item(self, order_id: uuid.UUID, item_id: uuid.UUID) -> None:
        """Delete an item and recalculate cost impact."""
        order = await self.get_order(order_id)

        # BUG-352: items are frozen once a CO leaves ``draft``. A submitted
        # CO represents a commitment already under review by the other
        # party, so silently mutating its line items is a contractual
        # integrity hazard. Revert to draft via an explicit transition if
        # changes are needed.
        if order.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Items can only be modified while change order is in 'draft' status",
            )

        # Capture the code before recalculation expires the session.
        order_code = order.code

        item = await self.repo.get_item_by_id(item_id)
        if item is None or item.change_order_id != order_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Change order item not found",
            )

        await self.repo.delete_item(item_id)
        await self._recalculate_cost_impact(order_id)

        logger.info("Item deleted from change order %s: %s", order_code, item_id)

    async def _recalculate_cost_impact(self, order_id: uuid.UUID) -> None:
        """Recalculate the total cost impact from all items."""
        items = await self.repo.list_items_for_order(order_id)
        total = sum(float(item.cost_delta) for item in items)
        await self.repo.update_fields(order_id, cost_impact=str(round(total, 2)))
