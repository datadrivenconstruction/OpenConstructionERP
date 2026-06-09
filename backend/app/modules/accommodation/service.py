"""Accommodation business logic - stateless service layer.

All cross-table operations (booking creation with status gates, PropDev
bootstrap, HR-driven room suggestion, state-machine transitions) live
here so the router stays a thin HTTP adapter.

IDOR posture (Wave-5 pattern): every helper returns 404, not 403, when
the caller does not own the parent project. We never leak the existence
of a UUID the caller is not allowed to see.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accommodation.models import (
    Accommodation,
    Booking,
    Charge,
    Room,
)

# ── State machine ─────────────────────────────────────────────────────────

# Booking lifecycle: reserved → checked_in → checked_out, with cancel
# allowed from any non-final state. Reaching ``cancelled`` / ``checked_out``
# locks the row (no further transitions). ``maintenance`` / ``blocked``
# rooms gate booking creation but never appear in the booking status.

_BOOKING_TRANSITIONS: dict[str, set[str]] = {
    "reserved": {"checked_in", "cancelled"},
    "checked_in": {"checked_out", "cancelled"},
    "checked_out": set(),
    "cancelled": set(),
}


def is_valid_booking_transition(current: str, target: str) -> bool:
    """Return True iff ``current → target`` is allowed by the state machine."""
    if current == target:
        return True  # idempotent updates are fine
    return target in _BOOKING_TRANSITIONS.get(current, set())


# Charge lifecycle: pending → invoiced → paid, with ``waived`` reachable
# from any non-paid state (an operator can write off a charge before it is
# settled). ``paid`` and ``waived`` are terminal: a settled or written-off
# line-item is a closed financial record and must not silently change.
_CHARGE_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"invoiced", "paid", "waived"},
    "invoiced": {"paid", "waived"},
    "paid": set(),
    "waived": set(),
}

# Charge statuses whose line-items are locked against edit / delete. Once a
# charge is settled (``paid``) or written off (``waived``) it is part of the
# financial trail and may only be inspected, never mutated or removed.
_LOCKED_CHARGE_STATUSES: tuple[str, ...] = ("paid", "waived")


def is_valid_charge_transition(current: str, target: str) -> bool:
    """Return True iff ``current → target`` is allowed by the charge machine."""
    if current == target:
        return True  # idempotent updates are fine
    return target in _CHARGE_TRANSITIONS.get(current, set())


def assert_charge_mutable(charge: Charge) -> None:
    """Raise 409 if the charge's status forbids edits / deletion.

    A ``paid`` or ``waived`` charge is a closed financial record; correcting
    it means reversing the settlement first, not editing the line in place.
    """
    if charge.status in _LOCKED_CHARGE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Charge is {charge.status} and can no longer be modified"),
        )


# ── Project-access helper (IDOR gate) ─────────────────────────────────────


async def _user_is_admin(session: AsyncSession, user_id: str) -> bool:
    """Lightweight admin probe - never raises."""
    try:
        from app.modules.users.repository import UserRepository

        user_repo = UserRepository(session)
        try:
            uid = uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            return False
        user = await user_repo.get_by_id(uid)
        return user is not None and getattr(user, "role", "") == "admin"
    except Exception:  # noqa: BLE001
        return False


async def _verify_project_access(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: str,
) -> None:
    """404 on both 'project missing' and 'access denied' - Wave-5 IDOR."""
    from app.modules.projects.repository import ProjectRepository

    repo = ProjectRepository(session)
    project = await repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Accommodation not found",
        )

    if await _user_is_admin(session, user_id):
        return

    if str(getattr(project, "owner_id", "")) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Accommodation not found",
        )


async def _accessible_project_ids(
    session: AsyncSession,
    user_id: str,
) -> list[uuid.UUID] | None:
    """Return the project IDs the caller may see.

    Returns ``None`` for admins (meaning "no filter - see everything")
    and a list of UUIDs for regular users (their owned projects).
    """
    if await _user_is_admin(session, user_id):
        return None
    from app.modules.projects.models import Project

    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return []
    rows = await session.execute(
        select(Project.id).where(Project.owner_id == uid),
    )
    return [r[0] for r in rows.all()]


# ── Accommodation helpers ────────────────────────────────────────────────


async def get_accommodation_or_404(
    session: AsyncSession,
    accommodation_id: uuid.UUID,
    user_id: str,
) -> Accommodation:
    """Load an accommodation, enforcing project access + soft-delete tombstone."""
    accom = await session.get(Accommodation, accommodation_id)
    if accom is None or accom.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Accommodation not found",
        )
    await _verify_project_access(session, accom.project_id, user_id)
    return accom


async def get_room_or_404(
    session: AsyncSession,
    room_id: uuid.UUID,
    user_id: str,
) -> tuple[Room, Accommodation]:
    """Load a room + its parent accommodation, enforcing project access."""
    room = await session.get(Room, room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )
    accom = await get_accommodation_or_404(session, room.accommodation_id, user_id)
    return room, accom


async def get_booking_or_404(
    session: AsyncSession,
    booking_id: uuid.UUID,
    user_id: str,
) -> tuple[Booking, Room, Accommodation]:
    """Load a booking + its room + accommodation, enforcing project access."""
    booking = await session.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )
    room, accom = await get_room_or_404(session, booking.room_id, user_id)
    return booking, room, accom


async def get_charge_or_404(
    session: AsyncSession,
    charge_id: uuid.UUID,
    user_id: str,
) -> tuple[Charge, Booking, Room, Accommodation]:
    """Load a charge + its booking / room / accommodation, IDOR-gated.

    Returns 404 (never 403) when the caller cannot reach the parent
    project, consistent with the rest of the module.
    """
    charge = await session.get(Charge, charge_id)
    if charge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Charge not found",
        )
    booking, room, accom = await get_booking_or_404(
        session,
        charge.booking_id,
        user_id,
    )
    return charge, booking, room, accom


# ── Booking creation gate ────────────────────────────────────────────────


def assert_room_bookable(room: Room) -> None:
    """Raise 409 if the room's status forbids new bookings."""
    if room.status in ("maintenance", "blocked"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Room is {room.status} and cannot accept bookings",
        )


# Bookings that still hold the room. ``cancelled`` and ``checked_out``
# free the slot - see the matching transitions in ``_BOOKING_TRANSITIONS``.
_LIVE_BOOKING_STATUSES: tuple[str, ...] = ("reserved", "checked_in")


async def assert_no_booking_overlap(
    session: AsyncSession,
    room_id: uuid.UUID,
    check_in: date,
    check_out: date | None,
    *,
    exclude_booking_id: uuid.UUID | None = None,
) -> None:
    """Raise 409 if ``[check_in, check_out)`` overlaps a live booking.

    Half-open interval semantics mirror :func:`_apply_booking_filters`
    so the create/update guard is symmetric with the list-overlap
    filter: back-to-back stays (``b.check_out == new.check_in``) are
    allowed; any other intersection is rejected. ``check_out=None``
    means the new booking is open-ended and conflicts with anything
    starting on or after its ``check_in``. ``exclude_booking_id`` lets
    PATCH skip the row being edited so re-saving its own window is a
    no-op.
    """
    stmt = select(Booking.id).where(Booking.room_id == room_id).where(Booking.status.in_(_LIVE_BOOKING_STATUSES))
    if exclude_booking_id is not None:
        stmt = stmt.where(Booking.id != exclude_booking_id)

    # Existing booking ends strictly after our start (or is open-ended).
    stmt = stmt.where(
        or_(Booking.check_out.is_(None), Booking.check_out > check_in),
    )
    # Our window must end strictly after the other's start - unless
    # we're open-ended, in which case no upper bound applies.
    if check_out is not None:
        stmt = stmt.where(Booking.check_in < check_out)

    conflict = (await session.execute(stmt.limit(1))).first()
    if conflict is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Booking dates overlap an existing reservation for this room",
        )


# ── PropDev bootstrap ────────────────────────────────────────────────────


async def bootstrap_from_propdev_block(
    session: AsyncSession,
    accommodation: Accommodation,
    block_id: uuid.UUID,
) -> dict[str, int | uuid.UUID]:
    """Iterate a PropDev block's plots → create rooms 1:1.

    Idempotent: running it twice does NOT duplicate rooms. Existing rows
    are matched by ``(accommodation_id, label)`` and skipped. The
    PropDev module is optional; if it's not loaded we return a zero-row
    result rather than crashing.
    """
    try:
        from app.modules.property_dev.models import Block, Plot
    except Exception:  # noqa: BLE001 - PropDev disabled / missing
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PropDev module is not available",
        ) from None

    block = await session.get(Block, block_id)
    if block is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PropDev block not found",
        )

    # Pull every plot under this block.
    plot_rows = (await session.execute(select(Plot).where(Plot.block_id == block_id))).scalars().all()

    # Pre-load existing room labels so we can dedupe in one pass.
    existing_labels: set[str] = set(
        (await session.execute(select(Room.label).where(Room.accommodation_id == accommodation.id))).scalars().all()
    )

    created = 0
    skipped = 0
    for plot in plot_rows:
        label = (plot.plot_number or "").strip()
        if not label:
            skipped += 1
            continue
        if label in existing_labels:
            skipped += 1
            continue
        # Carry the BIM element id if the plot's metadata stashed one.
        bim_eid: str | None = None
        meta = getattr(plot, "metadata_", None) or {}
        if isinstance(meta, dict):
            ref = meta.get("bim_element_id")
            if isinstance(ref, str) and ref:
                bim_eid = ref[:120]

        # Reuse the plot's currency for the room's base-rate currency
        # when available; service layer for explicit Room creation will
        # backfill the same way.
        currency = (getattr(plot, "currency", "") or "")[:3]

        room = Room(
            accommodation_id=accommodation.id,
            label=label,
            capacity=1,
            bim_element_id=bim_eid,
            base_rate=Decimal("0"),
            base_rate_currency=currency,
            status="available",
        )
        session.add(room)
        existing_labels.add(label)
        created += 1

    # Persist link on the accommodation so subsequent calls are obviously
    # idempotent at the API surface too.
    accommodation.property_dev_block_id = block_id

    await session.flush()
    return {
        "accommodation_id": accommodation.id,
        "block_id": block_id,
        "rooms_created": created,
        "rooms_skipped": skipped,
        "total_rooms": len(existing_labels),
    }


# ── HR-driven suggestion ─────────────────────────────────────────────────


async def suggest_room_for_employee(
    session: AsyncSession,
    user_id: str,
    employee_contact_id: uuid.UUID,
    start_date,
) -> Room:
    """Suggest the lowest-labelled available worker_camp room.

    "Lowest" is a lexicographic ORDER BY on ``label`` so labels like
    ``"B-101"`` come before ``"B-202"``. Caller scope: only
    accommodations in projects the user can access.

    Returns the suggested room. Raises 404 if no room is available.
    NOT a confirmation - the UI must follow up with a real
    ``POST /rooms/{id}/bookings``.
    """
    # The employee_contact_id arg is part of the public API so a future
    # iteration can prefer a room near the employee's project. For the
    # MVP we just ensure the contact exists (gate against random UUIDs)
    # and otherwise ignore it.
    #
    # IDOR posture (Wave-5): the contact must belong to the caller's
    # tenant - otherwise a caller could probe the existence of any Contact
    # UUID (404 vs proceed). Admins bypass the scope. We return 404, never
    # 403, on a contact the caller is not allowed to see (consistent with
    # the module's 404-on-not-owned stance). The contacts module gates on
    # ``tenant_id`` with a ``created_by`` fallback for pre-v2.3.1 rows.
    from app.modules.contacts.models import Contact

    contact = await session.get(Contact, employee_contact_id)
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee contact not found",
        )

    if not await _user_is_admin(session, user_id):
        caller = str(user_id)
        tenant = getattr(contact, "tenant_id", None)
        created_by = getattr(contact, "created_by", None)
        owns = (tenant is not None and str(tenant) == caller) or (
            tenant is None and created_by is not None and str(created_by) == caller
        )
        if not owns:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee contact not found",
            )

    project_ids = await _accessible_project_ids(session, user_id)

    stmt = (
        select(Room)
        .join(Accommodation, Accommodation.id == Room.accommodation_id)
        .where(Room.status == "available")
        .where(Accommodation.kind == "worker_camp")
        .where(Accommodation.deleted_at.is_(None))
        .order_by(Room.label.asc())
        .limit(1)
    )
    if project_ids is not None:
        if not project_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No available room",
            )
        stmt = stmt.where(Accommodation.project_id.in_(project_ids))

    room = (await session.execute(stmt)).scalars().first()
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No available room",
        )
    return room


# ── Active-booking counter (used by detail response) ─────────────────────


async def active_bookings_count(
    session: AsyncSession,
    accommodation_id: uuid.UUID,
) -> int:
    """Count bookings whose status is reserved or checked_in."""
    stmt = (
        select(func.count(Booking.id))
        .join(Room, Room.id == Booking.room_id)
        .where(Room.accommodation_id == accommodation_id)
        .where(Booking.status.in_(("reserved", "checked_in")))
    )
    return int((await session.execute(stmt)).scalar() or 0)


# ── Booking list queries (with room_label decoration) ────────────────────


def _apply_booking_filters(
    stmt,
    *,
    statuses: list[str] | None,
    from_date: date | None,
    to_date: date | None,
):
    """Apply optional ``status[]`` + date-overlap filters to a Booking query.

    Date overlap rule (half-open interval matching real booking semantics):
    a booking ``[check_in, check_out)`` overlaps a window
    ``[from_date, to_date]`` when ``check_in <= to_date`` AND
    ``(check_out IS NULL OR check_out > from_date)`` - open-ended bookings
    (NULL ``check_out``) always overlap any future window whose start they
    precede.
    """
    if statuses:
        stmt = stmt.where(Booking.status.in_(statuses))
    if from_date is not None:
        # Booking ends strictly after the window starts (or is open-ended).
        stmt = stmt.where(
            or_(Booking.check_out.is_(None), Booking.check_out > from_date),
        )
    if to_date is not None:
        # Booking starts on or before the window ends.
        stmt = stmt.where(Booking.check_in <= to_date)
    return stmt


async def list_bookings_for_accommodation(
    session: AsyncSession,
    accommodation_id: uuid.UUID,
    user_id: str,
    *,
    statuses: list[str] | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Booking], dict[uuid.UUID, str], int]:
    """List bookings across every room of an accommodation.

    Returns ``(bookings, room_label_by_room_id, total)`` where ``total`` is
    the count of all matching bookings (before ``limit``/``offset``) so the
    router can populate ``BookingListResponse.total`` correctly across pages,
    and ``room_label_by_room_id`` lets it decorate the response with
    ``room_label`` without a per-row N+1.

    IDOR-gated through :func:`get_accommodation_or_404` - a caller who
    can't see the parent project gets a 404, never a 403.
    """
    accom = await get_accommodation_or_404(session, accommodation_id, user_id)

    # Pull every room id + label up front so the response decoration is
    # cheap and a deleted-then-restored room never widens the query.
    room_rows = (
        await session.execute(
            select(Room.id, Room.label).where(
                Room.accommodation_id == accom.id,
            )
        )
    ).all()
    room_label_by_id: dict[uuid.UUID, str] = {r[0]: r[1] for r in room_rows}
    if not room_label_by_id:
        return [], {}, 0

    room_ids = list(room_label_by_id.keys())

    # Total matching count (same filters, no limit/offset) so pagination
    # metadata reflects the full result set, not just the current page.
    count_stmt = _apply_booking_filters(
        select(func.count(Booking.id)).where(Booking.room_id.in_(room_ids)),
        statuses=statuses,
        from_date=from_date,
        to_date=to_date,
    )
    total = int((await session.execute(count_stmt)).scalar() or 0)

    stmt = (
        select(Booking)
        .where(Booking.room_id.in_(room_ids))
        .order_by(Booking.check_in.desc(), Booking.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    stmt = _apply_booking_filters(
        stmt,
        statuses=statuses,
        from_date=from_date,
        to_date=to_date,
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows), room_label_by_id, total


async def list_bookings_for_room(
    session: AsyncSession,
    room_id: uuid.UUID,
    user_id: str,
    *,
    statuses: list[str] | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Booking], dict[uuid.UUID, str], int]:
    """List bookings for a single room.

    Returns ``(bookings, room_label_by_room_id, total)`` where ``total`` is
    the count of all matching bookings (before ``limit``/``offset``).

    Same IDOR posture as :func:`list_bookings_for_accommodation` - the
    caller must own the parent project or we 404.
    """
    room, _accom = await get_room_or_404(session, room_id, user_id)

    # Total matching count (same filters, no limit/offset) so pagination
    # metadata reflects the full result set, not just the current page.
    count_stmt = _apply_booking_filters(
        select(func.count(Booking.id)).where(Booking.room_id == room.id),
        statuses=statuses,
        from_date=from_date,
        to_date=to_date,
    )
    total = int((await session.execute(count_stmt)).scalar() or 0)

    stmt = (
        select(Booking)
        .where(Booking.room_id == room.id)
        .order_by(Booking.check_in.desc(), Booking.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    stmt = _apply_booking_filters(
        stmt,
        statuses=statuses,
        from_date=from_date,
        to_date=to_date,
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows), {room.id: room.label}, total


# ── Currency-inheritance helpers ─────────────────────────────────────────


async def _resolve_project_currency(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> str:
    """Look up the parent project's currency (best-effort)."""
    try:
        from app.modules.projects.models import Project

        proj = await session.get(Project, project_id)
        if proj is not None:
            return (getattr(proj, "currency", "") or "")[:3]
    except Exception:  # noqa: BLE001
        pass
    return ""


async def inherit_currency_for_room(
    session: AsyncSession,
    accommodation: Accommodation,
    explicit: str,
) -> str:
    """Apply the v3 EUR-default-kill rule: fall back to project currency.

    A blank-or-whitespace explicit value inherits rather than persisting a
    meaningless ``"  "`` string. The schema already strips whitespace on
    the happy path, but normalising here keeps every caller safe even if a
    future write path skips the schema layer.
    """
    if explicit and explicit.strip():
        return explicit.strip()
    return await _resolve_project_currency(session, accommodation.project_id)


async def resolve_charge_currency(
    session: AsyncSession,
    room: Room,
    accommodation: Accommodation,
    explicit: str | None,
) -> str:
    """Resolve a charge currency: explicit → room → project, never blank-stored.

    Treats ``None`` / empty / whitespace-only ``explicit`` as "inherit" so a
    charge never lands a meaningless ``"  "`` in the DB (Defect #5). Falls
    back room → project, mirroring the create path.
    """
    if explicit and explicit.strip():
        return explicit.strip()
    if room.base_rate_currency and room.base_rate_currency.strip():
        return room.base_rate_currency.strip()
    return await inherit_currency_for_room(session, accommodation, "")
