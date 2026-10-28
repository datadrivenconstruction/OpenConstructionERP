# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Site Logistics service - business logic for gates, laydown zones and deliveries.

Stateless service layer. The delivery rules are enforced here so a booking that
breaks them is never persisted:

* a delivery window must fall inside its gate's open/close hours, read on the
  site's clock (the time zone of the logistics concept),
* two *approved* deliveries on the same gate must not overlap in time, and
* an approved delivery never carries a load its gate cannot take, nor exceeds
  the concept's deliveries per hour. ``_assert_approvable`` is the one place
  that decides this; create, update and approve all go through it.

The checks reuse the pure helpers in ``validators.py`` and the plan service and
raise ``HTTPException(400)`` with a clear, user-facing message.
"""

import logging
import uuid
from datetime import UTC, datetime, tzinfo
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.json_merge import merge_metadata
from app.modules.site_logistics.coverage import BillLine, DeliveredLine, coverage_by_position, to_decimal
from app.modules.site_logistics.errors import LogisticsError
from app.modules.site_logistics.events import (
    DELIVERY_APPROVED,
    DELIVERY_BOOKED,
    DELIVERY_REJECTED,
)
from app.modules.site_logistics.models import DeliveryBooking, DeliveryLine, Gate, LaydownZone, LogisticsConcept
from app.modules.site_logistics.planning import narrower_hours
from app.modules.site_logistics.repository import (
    BillPositionRepository,
    DeliveryLineRepository,
    DeliveryRepository,
    GateRepository,
    LaydownZoneRepository,
)
from app.modules.site_logistics.schemas import (
    BILL_COVERAGE_LIMIT,
    BillCoverageResponse,
    BillCoverageRow,
    DeliveryCreate,
    DeliveryLineInput,
    DeliveryUpdate,
    GateCreate,
    GateUpdate,
    LaydownZoneCreate,
    LaydownZoneUpdate,
    SiteLogisticsStatsResponse,
)
from app.modules.site_logistics.validators import (
    GATE_HOURS_UNCHECKED,
    delivery_within_gate_hours,
    find_first_overlap,
)

logger = logging.getLogger(__name__)

# Statuses a delivery can no longer be scheduled out of - the vehicle is on its
# way in or done, so approve/reject/window edits are refused.
_TERMINAL_ON_SITE = ("arrived", "completed")


def _refusal(code: str, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    """A refused booking in the style of these routes, carrying the stable code its ``can`` flag reports."""
    exc = HTTPException(status_code=status_code, detail=detail)
    exc.code = code  # type: ignore[attr-defined]
    return exc


def _ensure_aware(value: datetime, tz: tzinfo | None = None) -> datetime:
    """Make a window comparable and storable.

    A value with an offset is the instant it names. A naive value comes from a
    ``datetime-local`` input and is the site's wall clock, so it gets the site
    time zone ``tz``. While the site has no zone it is stored labelled UTC, as it
    always was; no time-of-day rule is evaluated without a zone, so nothing reads
    that label as a clock.
    """
    return value.replace(tzinfo=tz or UTC) if value.tzinfo is None else value


class SiteLogisticsService:
    """Business logic for site logistics operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.gate_repo = GateRepository(session)
        self.zone_repo = LaydownZoneRepository(session)
        self.delivery_repo = DeliveryRepository(session)
        self.line_repo = DeliveryLineRepository(session)
        self.bill_repo = BillPositionRepository(session)

    # ── Gates ─────────────────────────────────────────────────────────────

    async def create_gate(self, data: GateCreate, user_id: str | None = None) -> Gate:
        """Create a site access gate."""
        gate = Gate(
            project_id=data.project_id,
            name=data.name,
            open_time=data.open_time,
            close_time=data.close_time,
            capacity_per_slot=data.capacity_per_slot,
            notes=data.notes,
            access_kind=data.access_kind,
            max_axle_load_t=data.max_axle_load_t,
            max_gross_t=data.max_gross_t,
            max_height_m=data.max_height_m,
            max_width_m=data.max_width_m,
            max_length_m=data.max_length_m,
            turning_radius_m=data.turning_radius_m,
            created_by=user_id,
            metadata_=data.metadata,
        )
        gate = await self.gate_repo.create(gate)
        await self.session.commit()
        logger.info("Site gate created: %s for project %s", data.name, data.project_id)
        return gate

    async def get_gate(self, gate_id: uuid.UUID) -> Gate:
        """Get a gate by ID. Raises 404 if not found."""
        gate = await self.gate_repo.get_by_id(gate_id)
        if gate is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")
        return gate

    async def list_gates(self, project_id: uuid.UUID) -> list[Gate]:
        """List gates for a project."""
        return await self.gate_repo.list_for_project(project_id)

    async def update_gate(self, gate_id: uuid.UUID, data: GateUpdate) -> Gate:
        """Update a gate. Re-validates that close stays after open."""
        gate = await self.get_gate(gate_id)
        fields = self._merge_metadata_fields(data.model_dump(exclude_unset=True), gate)
        if not fields:
            return gate

        open_time = fields.get("open_time", gate.open_time)
        close_time = fields.get("close_time", gate.close_time)
        if close_time <= open_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="close_time must be later than open_time",
            )

        await self.gate_repo.update_fields(gate_id, **fields)
        await self.session.refresh(gate)
        await self.session.commit()
        return gate

    async def delete_gate(self, gate_id: uuid.UUID) -> None:
        """Delete a gate. Deliveries keep their history (gate_id is set null)."""
        gate = await self.get_gate(gate_id)
        await self.gate_repo.delete(gate)
        await self.session.commit()
        logger.info("Site gate deleted: %s", gate_id)

    # ── Laydown zones ─────────────────────────────────────────────────────

    async def create_zone(self, data: LaydownZoneCreate, user_id: str | None = None) -> LaydownZone:
        """Create a laydown zone."""
        await self._assert_plan_row("area", data.site_area_id, data.project_id)
        zone = LaydownZone(
            project_id=data.project_id,
            name=data.name,
            capacity_desc=data.capacity_desc,
            usage_note=data.usage_note,
            site_area_id=data.site_area_id,
            created_by=user_id,
            metadata_=data.metadata,
        )
        zone = await self.zone_repo.create(zone)
        await self.session.commit()
        logger.info("Laydown zone created: %s for project %s", data.name, data.project_id)
        return zone

    async def get_zone(self, zone_id: uuid.UUID) -> LaydownZone:
        """Get a laydown zone by ID. Raises 404 if not found."""
        zone = await self.zone_repo.get_by_id(zone_id)
        if zone is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Laydown zone not found")
        return zone

    async def list_zones(self, project_id: uuid.UUID) -> list[LaydownZone]:
        """List laydown zones for a project."""
        return await self.zone_repo.list_for_project(project_id)

    async def update_zone(self, zone_id: uuid.UUID, data: LaydownZoneUpdate) -> LaydownZone:
        """Update a laydown zone."""
        zone = await self.get_zone(zone_id)
        fields = self._merge_metadata_fields(data.model_dump(exclude_unset=True), zone)
        if not fields:
            return zone
        if fields.get("site_area_id") is not None:
            await self._assert_plan_row("area", fields["site_area_id"], zone.project_id)
        await self.zone_repo.update_fields(zone_id, **fields)
        await self.session.refresh(zone)
        await self.session.commit()
        return zone

    async def delete_zone(self, zone_id: uuid.UUID) -> None:
        """Delete a laydown zone."""
        zone = await self.get_zone(zone_id)
        await self.zone_repo.delete(zone)
        await self.session.commit()
        logger.info("Laydown zone deleted: %s", zone_id)

    # ── Deliveries ────────────────────────────────────────────────────────

    async def create_delivery(self, data: DeliveryCreate, user_id: str | None = None) -> DeliveryBooking:
        """Book an inbound delivery, validating window and gate rules first."""
        tz = await self._plan().site_tz(data.project_id)
        window_start = _ensure_aware(data.window_start, tz)
        window_end = _ensure_aware(data.window_end, tz)

        await self._assert_plan_row("transport", data.transport_id, data.project_id)
        await self._plan_call(
            self._plan().assert_delivery_links(
                data.project_id,
                takt_location_id=data.takt_location_id,
                plant_item_id=data.plant_item_id,
                flow_code=data.flow_code,
            )
        )
        gate = None
        if data.status == "approved":
            await self._lock_approvals(data.project_id, data.gate_id)
        if data.gate_id is not None:
            gate = await self._load_project_gate(data.gate_id, data.project_id)
            self._assert_within_gate_hours(
                gate, window_start, window_end, await self._concept_hours(gate.project_id), tz
            )
        if data.status == "approved":
            await self._assert_approvable(
                data.project_id,
                gate=gate,
                gross_weight_t=data.gross_weight_t,
                transport_id=data.transport_id,
                start=window_start,
                end=window_end,
                exclude_id=None,
            )

        lines = await self._build_lines(data.project_id, data.lines)

        delivery = DeliveryBooking(
            project_id=data.project_id,
            gate_id=data.gate_id,
            supplier_name=data.supplier_name,
            contact_name=data.contact_name,
            contact_phone=data.contact_phone,
            vehicle_type=data.vehicle_type,
            materials_desc=data.materials_desc,
            window_start=window_start,
            window_end=window_end,
            status=data.status,
            po_ref=data.po_ref,
            notes=data.notes,
            transport_id=data.transport_id,
            direction=data.direction,
            gross_weight_t=data.gross_weight_t,
            plant_item_id=data.plant_item_id,
            takt_location_id=data.takt_location_id,
            flow_code=data.flow_code,
            created_by=user_id,
            lines=lines,
            metadata_=data.metadata,
        )
        delivery = await self.delivery_repo.create(delivery)
        await self.session.refresh(delivery)
        await self.session.commit()

        logger.info(
            "Delivery booked: %s at gate %s [%s] for project %s",
            data.supplier_name,
            data.gate_id,
            data.status,
            data.project_id,
        )
        self._emit(DELIVERY_BOOKED, delivery, user_id)
        if delivery.status == "approved":
            self._emit(DELIVERY_APPROVED, delivery, user_id)
        return delivery

    async def get_delivery(self, delivery_id: uuid.UUID) -> DeliveryBooking:
        """Get a delivery by ID. Raises 404 if not found."""
        delivery = await self.delivery_repo.get_by_id(delivery_id)
        if delivery is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
        return delivery

    async def list_deliveries(
        self,
        project_id: uuid.UUID,
        *,
        day: datetime | None = None,
        gate_id: uuid.UUID | None = None,
        status_filter: str | None = None,
    ) -> list[DeliveryBooking]:
        """List deliveries for a project, optionally filtered by day/gate/status."""
        day_start: datetime | None = None
        day_end: datetime | None = None
        if day is not None:
            day = _ensure_aware(day)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=999999)
        return await self.delivery_repo.list_for_project(
            project_id,
            day_start=day_start,
            day_end=day_end,
            gate_id=gate_id,
            status=status_filter,
        )

    async def update_delivery(self, delivery_id: uuid.UUID, data: DeliveryUpdate) -> DeliveryBooking:
        """Update a delivery, re-validating window and gate rules on the result."""
        delivery = await self.get_delivery(delivery_id)
        sent = data.model_dump(exclude_unset=True)
        if sent.get("status", delivery.status) == "approved":
            await self._lock_approvals(delivery.project_id, sent.get("gate_id", delivery.gate_id))
            # The booking as it stands once the writers before this one are done.
            await self.session.refresh(delivery)
        previous_status = delivery.status
        fields = self._merge_metadata_fields(data.model_dump(exclude_unset=True), delivery)
        # Lines are their own rows, so they never travel in the column update.
        line_inputs = data.lines if "lines" in fields else None
        fields.pop("lines", None)
        if not fields and line_inputs is None:
            return delivery

        tz = await self._plan().site_tz(delivery.project_id)
        for key in ("window_start", "window_end", "status", "direction"):
            if key in fields and fields[key] is None:
                # These columns are NOT NULL: null is not "leave it", it is a wrong value.
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"field_required: {key}")
        if "window_start" in fields:
            fields["window_start"] = _ensure_aware(fields["window_start"], tz)
        if "window_end" in fields:
            fields["window_end"] = _ensure_aware(fields["window_end"], tz)

        new_start: datetime = fields.get("window_start", delivery.window_start)
        new_end: datetime = fields.get("window_end", delivery.window_end)
        new_gate_id = fields.get("gate_id", delivery.gate_id)
        new_status = fields.get("status", delivery.status)

        if new_end <= new_start:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="window_end must be after window_start",
            )
        if fields.get("transport_id") is not None:
            await self._assert_plan_row("transport", fields["transport_id"], delivery.project_id)
        await self._plan_call(
            self._plan().assert_delivery_links(
                delivery.project_id,
                takt_location_id=fields.get("takt_location_id"),
                plant_item_id=fields.get("plant_item_id"),
                flow_code=fields.get("flow_code"),
                current_plant_item_id=delivery.plant_item_id,
            )
        )
        gate = None
        if new_gate_id is not None:
            gate = await self._load_project_gate(new_gate_id, delivery.project_id)
            self._assert_within_gate_hours(gate, new_start, new_end, await self._concept_hours(delivery.project_id), tz)
        if new_status == "approved":
            # The values the booking will carry after this update, not the stored ones.
            await self._assert_approvable(
                delivery.project_id,
                gate=gate,
                gross_weight_t=fields.get("gross_weight_t", delivery.gross_weight_t),
                transport_id=fields.get("transport_id", delivery.transport_id),
                start=new_start,
                end=new_end,
                exclude_id=delivery_id,
            )

        if line_inputs is not None:
            lines = await self._build_lines(delivery.project_id, line_inputs)
            await self.line_repo.replace_for_delivery(delivery_id, lines)
        if fields:
            await self.delivery_repo.update_fields(delivery_id, **fields)
        # A full refresh reloads the ``lines`` collection through its selectin
        # loader, so the response carries the list that was just written.
        await self.session.refresh(delivery)
        await self.session.commit()

        if new_status == "approved" and previous_status != "approved":
            self._emit(DELIVERY_APPROVED, delivery, delivery.created_by)
        logger.info("Delivery updated: %s (fields=%s)", delivery_id, list(fields.keys()))
        return delivery

    async def delete_delivery(self, delivery_id: uuid.UUID) -> None:
        """Delete a delivery booking and the bill lines it carried."""
        delivery = await self.get_delivery(delivery_id)
        await self.delivery_repo.delete(delivery)
        # Committed here like every sibling delete. The request-scoped session
        # dependency also commits on the way out, so this was never a lost
        # write - it just left this one path relying on the caller.
        await self.session.commit()
        logger.info("Delivery deleted: %s", delivery_id)

    async def approve_delivery(
        self,
        delivery_id: uuid.UUID,
        *,
        reason: str | None = None,
        user_id: str | None = None,
    ) -> DeliveryBooking:
        """Approve a delivery: requested/rejected -> approved, clash-checked."""
        delivery = await self.get_delivery(delivery_id)
        await self._lock_approvals(delivery.project_id, delivery.gate_id)
        # Read again behind the lock: another approval may have decided this booking meanwhile.
        await self.session.refresh(delivery)
        if delivery.status == "approved":
            return delivery
        await self._guard_approve(delivery)

        fields = self._decision_fields(delivery, "approved", reason, user_id)
        await self.delivery_repo.update_fields(delivery_id, **fields)
        await self.session.refresh(delivery)
        await self.session.commit()
        logger.info("Delivery approved: %s by %s", delivery_id, user_id)
        self._emit(DELIVERY_APPROVED, delivery, user_id)
        return delivery

    async def reject_delivery(
        self,
        delivery_id: uuid.UUID,
        *,
        reason: str | None = None,
        user_id: str | None = None,
    ) -> DeliveryBooking:
        """Reject a delivery: requested/approved -> rejected, releasing its slot."""
        delivery = await self.get_delivery(delivery_id)
        self._guard_decision(delivery, "reject")
        if delivery.status == "rejected":
            return delivery

        fields = self._decision_fields(delivery, "rejected", reason, user_id)
        await self.delivery_repo.update_fields(delivery_id, **fields)
        await self.session.refresh(delivery)
        await self.session.commit()
        logger.info("Delivery rejected: %s by %s", delivery_id, user_id)
        self._emit(DELIVERY_REJECTED, delivery, user_id)
        return delivery

    async def _lock_approvals(self, project_id: uuid.UUID, gate_id: uuid.UUID | None) -> None:
        """Queue the writers that produce an approved delivery, for the check and the write.

        The hourly rate of the concept and the slot on a gate are both counted over
        the approved bookings. Two approvals that read that set before either
        commits would both pass, so each one first takes the row the count hangs
        on: the concept row (the rate) and then the gate row (the slot), always in
        this order. The locks last until the transaction ends. A read never takes
        them: the ``can`` flags call the guards, not this. The lock is the kind
        that lets a new booking reference the gate meanwhile, so a request for a
        slot does not wait behind an approval.
        """
        await self.session.execute(
            select(LogisticsConcept.id).where(LogisticsConcept.project_id == project_id).with_for_update(key_share=True)
        )
        if gate_id is not None:
            await self.session.execute(select(Gate.id).where(Gate.id == gate_id).with_for_update(key_share=True))

    # ── Guards and allowed moves ──────────────────────────────────────────
    #
    # A guard refuses without changing anything. The write calls it, and ``can``
    # calls the same guard to say what the write would answer.

    @staticmethod
    def _guard_decision(delivery: DeliveryBooking, action: str) -> None:
        """A delivery that is on site or done is a record: it is not approved or rejected again."""
        if delivery.status in _TERMINAL_ON_SITE:
            raise _refusal("delivery_already_on_site", f"Cannot {action} a delivery that has already {delivery.status}")

    async def _guard_approve(self, delivery: DeliveryBooking) -> None:
        """Everything an approval checks at decision time.

        Window, gate hours and clash are checked again here: a gate's hours or a
        rival booking may have changed since the delivery was requested.
        """
        self._guard_decision(delivery, "approve")
        gate = None
        if delivery.gate_id is not None:
            gate = await self._load_project_gate(delivery.gate_id, delivery.project_id)
            self._assert_within_gate_hours(
                gate,
                delivery.window_start,
                delivery.window_end,
                await self._concept_hours(delivery.project_id),
                await self._plan().site_tz(delivery.project_id),
            )
        await self._assert_approvable(
            delivery.project_id,
            gate=gate,
            gross_weight_t=delivery.gross_weight_t,
            transport_id=delivery.transport_id,
            start=delivery.window_start,
            end=delivery.window_end,
            exclude_id=delivery.id,
        )

    @staticmethod
    def can_plain(perms: Any) -> dict[str, Any]:
        """The flags of a gate or a laydown zone: no state refuses, only the permission."""
        from app.modules.site_logistics.plan_service import _flag

        return {"edit": _flag(perms.write), "delete": _flag(perms.write)}

    @staticmethod
    def can_board(perms: Any) -> dict[str, Any]:
        """Whether the caller may add a gate, a laydown zone or a delivery (these lists have no envelope)."""
        from app.modules.site_logistics.plan_service import _flag

        return {kind: {"create": _flag(perms.write)} for kind in ("gate", "zone", "delivery")}

    async def can_delivery(self, delivery: DeliveryBooking, perms: Any) -> dict[str, Any]:
        """What the caller may do with one delivery now: ``{allowed, applies, reason}`` per action.

        ``reason`` is the code of the refusal the write would answer with, or
        ``permission_denied``. Approving an approved delivery and rejecting a
        rejected one do not apply.
        """
        from app.modules.site_logistics.plan_service import _flag

        async def why_not(guard: Any) -> str | None:
            try:
                out = guard()
                if hasattr(out, "__await__"):
                    await out
            except HTTPException as exc:
                return str(getattr(exc, "code", "delivery_refused"))
            return None

        flags = {"edit": _flag(perms.write), "delete": _flag(perms.write)}
        if delivery.status == "approved":
            flags["approve"] = _flag(perms.approve, "invalid_transition", applies=False)
        else:
            flags["approve"] = _flag(perms.approve, await why_not(lambda: self._guard_approve(delivery)))
        if delivery.status == "rejected":
            flags["reject"] = _flag(perms.approve, "invalid_transition", applies=False)
        else:
            flags["reject"] = _flag(perms.approve, await why_not(lambda: self._guard_decision(delivery, "reject")))
        return flags

    # ── Bill coverage ─────────────────────────────────────────────────────

    async def get_bill_coverage(
        self,
        project_id: uuid.UUID,
        *,
        boq_id: uuid.UUID | None = None,
        search: str | None = None,
        limit: int = BILL_COVERAGE_LIMIT,
    ) -> BillCoverageResponse:
        """Read the project's bill as a delivery ledger.

        One query serves two screens: the coverage table on the logistics page,
        and the position picker in the booking dialog - which is why the picker
        can show how much of a line is still outstanding while you pick it.

        Args:
            project_id: Project whose bill is being read.
            boq_id: Optional single bill to narrow to.
            search: Optional ordinal / description filter.
            limit: Maximum rows returned; the response reports the full count
                and raises ``truncated`` when the cap bit.

        Returns:
            The coverage rows plus the project-wide totals that do not depend
            on the filter (linked positions, detached lines).
        """
        limit = max(1, min(limit, BILL_COVERAGE_LIMIT))
        rows = await self.bill_repo.list_deliverable(project_id, boq_id=boq_id, search=search, limit=limit)
        total = await self.bill_repo.count_deliverable(project_id, boq_id=boq_id, search=search)
        facts = await self.line_repo.list_project_line_facts(project_id)
        detached = await self.line_repo.count_detached_lines(project_id)
        _, positions_covered = await self.line_repo.count_linked_deliveries(project_id)
        currency = await self._project_currency(project_id)

        bill = [
            BillLine(
                position_id=str(position.id),
                boq_id=str(owning_boq_id),
                ordinal=position.ordinal or "",
                description=position.description or "",
                unit=position.unit or "",
                quantity=to_decimal(position.quantity),
                unit_rate=to_decimal(position.unit_rate),
            )
            for position, owning_boq_id in rows
        ]
        delivered = [
            DeliveredLine(position_id=str(position_id), quantity=to_decimal(quantity), status=str(delivery_status))
            for position_id, quantity, delivery_status in facts
        ]
        coverage = coverage_by_position(bill, delivered)

        out: list[BillCoverageRow] = []
        value_total = Decimal("0")
        for entry in bill:
            cov = coverage[entry.position_id]
            value_total += cov.delivered_value
            out.append(
                BillCoverageRow(
                    position_id=uuid.UUID(entry.position_id),
                    boq_id=uuid.UUID(entry.boq_id),
                    ordinal=entry.ordinal,
                    description=entry.description,
                    unit=entry.unit,
                    bill_quantity=str(entry.quantity),
                    unit_rate=str(entry.unit_rate),
                    bill_total=str(entry.quantity * entry.unit_rate),
                    delivered_quantity=str(cov.delivered_quantity),
                    booked_quantity=str(cov.booked_quantity),
                    outstanding_quantity=str(cov.outstanding_quantity),
                    delivered_value=str(cov.delivered_value),
                    delivery_line_count=cov.delivery_line_count,
                    over_delivered=cov.over_delivered,
                )
            )

        return BillCoverageResponse(
            rows=out,
            total=total,
            truncated=total > len(out),
            currency=currency,
            linked_position_count=positions_covered,
            delivered_value_total=str(value_total),
            detached_line_count=detached,
        )

    # ── Stats ─────────────────────────────────────────────────────────────

    async def get_stats(self, project_id: uuid.UUID) -> SiteLogisticsStatsResponse:
        """Return aggregate delivery statistics for a project."""
        by_status = await self.delivery_repo.status_counts(project_id)
        gates = await self.gate_repo.list_for_project(project_id)
        zones = await self.zone_repo.list_for_project(project_id)
        upcoming = await self.delivery_repo.count_upcoming_approved(project_id, datetime.now(UTC))
        linked_deliveries, positions_covered = await self.line_repo.count_linked_deliveries(project_id)
        return SiteLogisticsStatsResponse(
            total_deliveries=sum(by_status.values()),
            by_status=by_status,
            gate_count=len(gates),
            laydown_zone_count=len(zones),
            upcoming_approved=upcoming,
            deliveries_linked_to_bill=linked_deliveries,
            positions_covered=positions_covered,
        )

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _build_lines(
        self,
        project_id: uuid.UUID,
        inputs: list[DeliveryLineInput],
    ) -> list[DeliveryLine]:
        """Turn line payloads into rows, resolving each against the project's bill.

        A position from another project is refused outright: a delivery board
        must not be able to book against a bill its own site cannot see.

        Description and unit are taken from the position rather than from the
        request, and so is the ordinal. The bill is the source of truth for what the work is, and the
        unit in particular has to match or the coverage table would sum tonnes
        against a cubic-metre line. The platform's unit conversion
        (``app.core.unit_conversion``) only restates a quantity between the
        metric and imperial spelling of the SAME dimension, so there is nothing
        in the tree that could convert a delivered tonne into a billed m3;
        letting the requester type a free unit would produce a total that looks
        right and is not. A line with no position keeps whatever ordinal the
        request carries, which is how a detached line survives an edit made for
        an unrelated reason.

        Args:
            project_id: Project the delivery belongs to.
            inputs: The line payloads from the request, in display order.

        Returns:
            Unattached :class:`DeliveryLine` rows, ready to be persisted.

        Raises:
            HTTPException 400: A referenced position is missing or belongs to
                another project.
        """
        position_ids = [item.boq_position_id for item in inputs if item.boq_position_id is not None]
        positions: dict[uuid.UUID, Any] = {}
        if position_ids:
            owners = await self.bill_repo.project_ids_for_positions(position_ids)
            missing = [str(pid) for pid in position_ids if pid not in owners]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Bill position not found: {', '.join(sorted(set(missing)))}",
                )
            foreign = [str(pid) for pid in position_ids if owners[pid] != project_id]
            if foreign:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A bill position on this delivery belongs to a different project",
                )
            positions = await self.bill_repo.get_positions(position_ids)

        lines: list[DeliveryLine] = []
        for index, item in enumerate(inputs):
            position = positions.get(item.boq_position_id) if item.boq_position_id is not None else None
            description = (position.description if position else item.description) or ""
            unit = (position.unit if position else item.unit) or ""
            lines.append(
                DeliveryLine(
                    boq_position_id=item.boq_position_id,
                    position_ordinal=position.ordinal if position else item.position_ordinal,
                    description=description[:500],
                    quantity=Decimal(item.quantity),
                    unit=unit[:20],
                    note=item.note,
                    sort_order=index,
                )
            )
        return lines

    async def _project_currency(self, project_id: uuid.UUID) -> str:
        """Return the project's currency code, or an empty string when unset."""
        from app.modules.projects.models import Project

        stmt = select(Project.currency).where(Project.id == project_id)
        return (await self.session.execute(stmt)).scalar_one_or_none() or ""

    async def _load_project_gate(self, gate_id: uuid.UUID, project_id: uuid.UUID) -> Gate:
        """Load a gate and confirm it belongs to the delivery's project."""
        gate = await self.gate_repo.get_by_id(gate_id)
        if gate is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")
        if gate.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Gate belongs to a different project",
            )
        return gate

    def _plan(self) -> Any:
        """The plan service on this session: the site clock, the gate load rule and the link checks live there."""
        from app.modules.site_logistics.plan_service import LogisticsPlanService

        return LogisticsPlanService(self.session)

    @staticmethod
    async def _plan_call(awaitable: Any) -> Any:
        """Run a plan service call and show its refusal in this router's ``HTTPException`` style.

        The detail starts with the stable error code. A 422 of the plan becomes
        the 400 these routes have always used for a refused booking.
        """
        try:
            return await awaitable
        except LogisticsError as exc:
            code = status.HTTP_400_BAD_REQUEST if exc.status_code == 422 else exc.status_code
            info = f": {exc.detail}" if exc.detail else ""
            raise _refusal(exc.code, f"{exc.code}{info}", code) from exc

    async def _assert_approvable(
        self,
        project_id: uuid.UUID,
        *,
        gate: Gate | None,
        gross_weight_t: Decimal | None,
        transport_id: uuid.UUID | None,
        start: datetime,
        end: datetime,
        exclude_id: uuid.UUID | None,
    ) -> None:
        """Everything an APPROVED delivery has to satisfy, for every path that produces one.

        Rule 5 (gate load, lifted only by a granted oversize permit covering the
        transport and the window), rule 12 (deliveries per hour of the concept)
        and the slot clash on the gate.
        """
        plan = self._plan()
        await self._plan_call(
            plan.assert_gate_load(
                project_id,
                gate=gate,
                vehicle={"gross_weight_t": gross_weight_t},
                transport_id=transport_id,
                start=start,
                end=end,
            )
        )
        rate = await plan.delivery_rate_violation(project_id, start, exclude_id=exclude_id)
        if rate is not None:
            info = ", ".join(f"{k}={v}" for k, v in rate.items() if k != "code")
            raise _refusal(rate["code"], f"{rate['code']}: {info}" if info else rate["code"])
        if gate is not None:
            await self._assert_no_overlap(gate.id, start, end, exclude_id=exclude_id)

    @staticmethod
    def _assert_within_gate_hours(
        gate: Gate,
        window_start: datetime,
        window_end: datetime,
        concept_hours: tuple[str | None, str | None] | None = None,
        tz: tzinfo | None = None,
    ) -> None:
        """Raise 400 when the window falls outside the gate's operating hours on the site clock.

        ``concept_hours`` are the logistics concept's delivery hours; they apply
        only where they are narrower than the gate's (rule 12). ``tz`` is the site
        time zone. On a site without one the hours are not compared and the window
        passes: see :meth:`delivery_warnings` for how that is told.
        """
        open_time, close_time = narrower_hours((gate.open_time, gate.close_time), concept_hours)
        ok, reason = delivery_within_gate_hours(open_time, close_time, window_start, window_end, tz)
        if not ok:
            raise _refusal("outside_gate_hours", str(reason))

    async def delivery_warnings(self, delivery: DeliveryBooking) -> list[dict[str, Any]]:
        """What was not checked for this delivery, each ``{code, severity, field}``.

        ``gate_hours_unchecked``: the gate (or the concept) has opening hours and
        the site has no time zone, so the window was not compared with them.
        ``field`` names the concept field that ends the warning.
        """
        if delivery.gate_id is None or delivery.window_start is None or delivery.window_end is None:
            return []
        if await self._plan().site_tz(delivery.project_id) is not None:
            return []
        gate = await self.gate_repo.get_by_id(delivery.gate_id)
        if gate is None:
            return []
        open_time, close_time = narrower_hours(
            (gate.open_time, gate.close_time), await self._concept_hours(delivery.project_id)
        )
        _, reason = delivery_within_gate_hours(open_time, close_time, delivery.window_start, delivery.window_end, None)
        if str(reason or "").startswith(GATE_HOURS_UNCHECKED):
            return [{"code": GATE_HOURS_UNCHECKED, "severity": "warning", "field": "site_timezone"}]
        return []

    async def _concept_hours(self, project_id: uuid.UUID) -> tuple[str | None, str | None] | None:
        """The logistics concept's delivery hours of a project, ``None`` without a concept."""
        from app.modules.site_logistics.models import LogisticsConcept

        row = (
            await self.session.execute(
                select(LogisticsConcept.delivery_open, LogisticsConcept.delivery_close).where(
                    LogisticsConcept.project_id == project_id
                )
            )
        ).first()
        if row is None or not row[0] or not row[1]:
            return None
        return (row[0], row[1])

    async def _assert_plan_row(self, kind: str, row_id: uuid.UUID | None, project_id: uuid.UUID) -> None:
        """404 when a new foreign key names a plan row of another project (rule 20)."""
        if row_id is None:
            return
        from app.modules.site_logistics.models import SiteArea, Transport

        model = {"area": SiteArea, "transport": Transport}[kind]
        owner = (await self.session.execute(select(model.project_id).where(model.id == row_id))).scalar_one_or_none()
        if owner != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{kind.capitalize()} not found")

    async def _assert_no_overlap(
        self,
        gate_id: uuid.UUID,
        window_start: datetime,
        window_end: datetime,
        *,
        exclude_id: uuid.UUID | None,
    ) -> None:
        """Raise 400 when an approved delivery already holds an overlapping slot."""
        existing = await self.delivery_repo.list_approved_for_gate(gate_id, exclude_id=exclude_id)
        clash = find_first_overlap(window_start, window_end, [(s, e) for _id, s, e in existing])
        if clash is not None:
            clash_start, clash_end = clash
            raise _refusal(
                "slot_taken",
                "This window clashes with an approved delivery from "
                f"{clash_start:%Y-%m-%d %H:%M} to {clash_end:%H:%M} on this gate",
            )

    @staticmethod
    def _merge_metadata_fields(fields: dict[str, Any], entity: object) -> dict[str, Any]:
        """Rename the incoming ``metadata`` key to ``metadata_`` and merge it."""
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(entity, "metadata_", None), incoming) if isinstance(incoming, dict) else incoming
            )
        return fields

    @staticmethod
    def _decision_fields(
        delivery: DeliveryBooking,
        decision: str,
        reason: str | None,
        user_id: str | None,
    ) -> dict[str, Any]:
        """Build the update fields for an approve/reject, recording an audit note."""
        md = dict(delivery.metadata_ or {})
        md["last_decision"] = {
            "decision": decision,
            "by": user_id,
            "at": datetime.now(UTC).isoformat(),
            "reason": reason,
        }
        return {"status": decision, "metadata_": md}

    @staticmethod
    def _emit(topic: str, delivery: DeliveryBooking, user_id: str | None) -> None:
        """Publish a delivery lifecycle event for cross-module subscribers."""
        event_bus.publish_detached(
            topic,
            data={
                "project_id": str(delivery.project_id),
                "delivery_id": str(delivery.id),
                "gate_id": str(delivery.gate_id) if delivery.gate_id else None,
                "supplier_name": delivery.supplier_name,
                "window_start": delivery.window_start.isoformat() if delivery.window_start else None,
                "window_end": delivery.window_end.isoformat() if delivery.window_end else None,
                "status": delivery.status,
                "user_id": user_id,
            },
            source_module="site_logistics",
        )
