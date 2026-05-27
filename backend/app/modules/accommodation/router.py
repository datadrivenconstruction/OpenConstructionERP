"""Accommodation API routes.

Mounted by the module loader at ``/api/v1/accommodation/``.

IDOR posture: every read / write through a parent identifier (project
or accommodation) routes through ``service._verify_project_access`` /
``get_*_or_404`` so unrelated users always see 404, never 403.

State-machine: ``BookingUpdate`` enforces the transition map declared
in :mod:`app.modules.accommodation.service`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.accommodation.models import (
    Accommodation,
    Booking,
    Charge,
    Room,
)
from app.modules.accommodation.schemas import (
    AccommodationCreate,
    AccommodationDetailResponse,
    AccommodationResponse,
    AccommodationUpdate,
    BookingCreate,
    BookingDetailResponse,
    BookingListResponse,
    BookingResponse,
    BookingUpdate,
    BootstrapFromPropDevResponse,
    ChargeCreate,
    ChargeResponse,
    RoomBulkCreate,
    RoomResponse,
    RoomUpdate,
    SuggestFromHRRequest,
    SuggestFromHRResponse,
)
from app.modules.accommodation.service import (
    _accessible_project_ids,
    _verify_project_access,
    active_bookings_count,
    assert_no_booking_overlap,
    assert_room_bookable,
    bootstrap_from_propdev_block,
    get_accommodation_or_404,
    get_booking_or_404,
    get_room_or_404,
    inherit_currency_for_room,
    is_valid_booking_transition,
    list_bookings_for_accommodation,
    list_bookings_for_room,
    suggest_room_for_employee,
)

# ── Allowed status values for the list filter ────────────────────────────
# Mirror the regex in ``schemas._BOOKING_STATUS_PATTERN`` so an unknown
# value reaches a 422 before we touch the DB.
_BOOKING_STATUS_VALUES = ("reserved", "checked_in", "checked_out", "cancelled")


def _parse_booking_status_filter(values: list[str] | None) -> list[str] | None:
    """Validate a ``?status=`` query filter (single or multi-value)."""
    if not values:
        return None
    cleaned: list[str] = []
    for v in values:
        if v not in _BOOKING_STATUS_VALUES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown booking status: {v!r}",
            )
        if v not in cleaned:
            cleaned.append(v)
    return cleaned


def _decorate_bookings(
    bookings: list[Booking],
    room_label_by_id: dict[uuid.UUID, str],
) -> list[BookingResponse]:
    """Attach ``room_label`` to each booking response (no extra queries)."""
    out: list[BookingResponse] = []
    for b in bookings:
        base = BookingResponse.model_validate(b).model_dump(by_alias=False)
        base["room_label"] = room_label_by_id.get(b.room_id)
        out.append(BookingResponse.model_validate(base))
    return out


router = APIRouter()


# ── Accommodation CRUD ────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=list[AccommodationResponse],
    dependencies=[Depends(RequirePermission("accommodation.read"))],
)
async def list_accommodations(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AccommodationResponse]:
    """List accommodations for projects the current user can access."""
    accessible = await _accessible_project_ids(session, user_id)

    stmt = (
        select(Accommodation)
        .where(Accommodation.deleted_at.is_(None))
        .order_by(desc(Accommodation.created_at))
        .limit(limit)
        .offset(offset)
    )
    if project_id is not None:
        # When a specific project is requested, gate on access first.
        await _verify_project_access(session, project_id, user_id)
        stmt = stmt.where(Accommodation.project_id == project_id)
    elif accessible is not None:
        if not accessible:
            return []
        stmt = stmt.where(Accommodation.project_id.in_(accessible))

    rows = (await session.execute(stmt)).scalars().all()
    return [AccommodationResponse.model_validate(r) for r in rows]


@router.post(
    "/",
    response_model=AccommodationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("accommodation.create"))],
)
async def create_accommodation(
    payload: AccommodationCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> AccommodationResponse:
    """Create a new accommodation under a project the caller can access."""
    await _verify_project_access(session, payload.project_id, user_id)

    accom = Accommodation(
        project_id=payload.project_id,
        name=payload.name,
        kind=payload.kind,
        address=payload.address,
        geo_lat=payload.geo_lat,
        geo_lon=payload.geo_lon,
        bim_model_id=payload.bim_model_id,
        property_dev_block_id=payload.property_dev_block_id,
        capacity_total=payload.capacity_total,
        notes=payload.notes,
        created_by=str(user_id),
        metadata_=payload.metadata,
    )
    session.add(accom)
    await session.flush()
    await session.refresh(accom)
    return AccommodationResponse.model_validate(accom)


@router.get(
    "/{accommodation_id}",
    response_model=AccommodationDetailResponse,
    dependencies=[Depends(RequirePermission("accommodation.read"))],
)
async def get_accommodation(
    accommodation_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> AccommodationDetailResponse:
    """Return one accommodation with nested rooms + active-booking count."""
    accom = await get_accommodation_or_404(session, accommodation_id, user_id)

    rooms = (
        (await session.execute(select(Room).where(Room.accommodation_id == accom.id).order_by(Room.label.asc())))
        .scalars()
        .all()
    )
    counter = await active_bookings_count(session, accom.id)

    base = AccommodationResponse.model_validate(accom).model_dump(by_alias=False)
    base["rooms"] = [RoomResponse.model_validate(r) for r in rooms]
    base["active_bookings_count"] = counter
    return AccommodationDetailResponse.model_validate(base)


@router.patch(
    "/{accommodation_id}",
    response_model=AccommodationResponse,
    dependencies=[Depends(RequirePermission("accommodation.update"))],
)
async def update_accommodation(
    accommodation_id: uuid.UUID,
    payload: AccommodationUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> AccommodationResponse:
    """Partial update."""
    accom = await get_accommodation_or_404(session, accommodation_id, user_id)
    data = payload.model_dump(exclude_unset=True)
    metadata = data.pop("metadata", None)
    for key, value in data.items():
        setattr(accom, key, value)
    if metadata is not None:
        accom.metadata_ = metadata
    await session.flush()
    # Re-load so ``updated_at`` (server-side ``onupdate=func.now()``) is
    # populated without Pydantic tripping a lazy-IO MissingGreenlet on access.
    await session.refresh(accom)
    return AccommodationResponse.model_validate(accom)


@router.delete(
    "/{accommodation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("accommodation.delete"))],
)
async def delete_accommodation(
    accommodation_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    """Soft-delete by stamping ``deleted_at``. Rows are kept for audit."""
    accom = await get_accommodation_or_404(session, accommodation_id, user_id)
    accom.deleted_at = datetime.now(UTC)
    await session.flush()


@router.get(
    "/{accommodation_id}/bookings",
    response_model=BookingListResponse,
    dependencies=[Depends(RequirePermission("accommodation.read"))],
)
async def list_bookings_for_accommodation_endpoint(
    accommodation_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    status_filter: list[str] | None = Query(
        default=None,
        alias="status",
    ),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> BookingListResponse:
    """List bookings across every room of one accommodation.

    Multi-value ``?status=`` is accepted (FastAPI parses repeated query
    params into a list). Date filtering uses overlap semantics — see
    :func:`service._apply_booking_filters`.
    """
    statuses = _parse_booking_status_filter(status_filter)
    bookings, room_label_by_id = await list_bookings_for_accommodation(
        session,
        accommodation_id,
        user_id,
        statuses=statuses,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
    items = _decorate_bookings(bookings, room_label_by_id)
    return BookingListResponse(
        items=items,
        total=len(items),
        limit=limit,
        offset=offset,
    )


# ── Rooms ─────────────────────────────────────────────────────────────────


@router.post(
    "/{accommodation_id}/rooms",
    response_model=list[RoomResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("accommodation.room.create"))],
)
async def bulk_create_rooms(
    accommodation_id: uuid.UUID,
    payload: RoomBulkCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> list[RoomResponse]:
    """Bulk-create rooms under an accommodation.

    Rejects the whole batch with 409 on any duplicate ``(accom, label)``.
    """
    accom = await get_accommodation_or_404(session, accommodation_id, user_id)

    seen: set[str] = set()
    new_rooms: list[Room] = []
    for r in payload.rooms:
        if r.label in seen:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Duplicate label in batch: {r.label}",
            )
        seen.add(r.label)
        currency = await inherit_currency_for_room(
            session,
            accom,
            r.base_rate_currency,
        )
        new_rooms.append(
            Room(
                accommodation_id=accom.id,
                label=r.label,
                capacity=r.capacity,
                bim_element_id=r.bim_element_id,
                base_rate=r.base_rate,
                base_rate_currency=currency,
                status=r.status,
                metadata_=r.metadata,
            )
        )

    # Verify no existing label collisions before inserting.
    existing = set((await session.execute(select(Room.label).where(Room.accommodation_id == accom.id))).scalars().all())
    collisions = sorted(label for label in seen if label in existing)
    if collisions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Label(s) already exist: {', '.join(collisions)}",
        )

    session.add_all(new_rooms)
    await session.flush()
    for room in new_rooms:
        await session.refresh(room)
    return [RoomResponse.model_validate(r) for r in new_rooms]


@router.get(
    "/{accommodation_id}/rooms",
    response_model=list[RoomResponse],
    dependencies=[Depends(RequirePermission("accommodation.read"))],
)
async def list_rooms(
    accommodation_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    room_status: str | None = Query(default=None, alias="status"),
) -> list[RoomResponse]:
    """List rooms (optionally filtered by status) for one accommodation."""
    accom = await get_accommodation_or_404(session, accommodation_id, user_id)
    stmt = select(Room).where(Room.accommodation_id == accom.id).order_by(Room.label.asc())
    if room_status is not None:
        stmt = stmt.where(Room.status == room_status)
    rows = (await session.execute(stmt)).scalars().all()
    return [RoomResponse.model_validate(r) for r in rows]


@router.patch(
    "/rooms/{room_id}",
    response_model=RoomResponse,
    dependencies=[Depends(RequirePermission("accommodation.room.update"))],
)
async def update_room(
    room_id: uuid.UUID,
    payload: RoomUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> RoomResponse:
    """Partial update for a room."""
    room, _accom = await get_room_or_404(session, room_id, user_id)
    data = payload.model_dump(exclude_unset=True)
    metadata = data.pop("metadata", None)
    for key, value in data.items():
        setattr(room, key, value)
    if metadata is not None:
        room.metadata_ = metadata
    await session.flush()
    await session.refresh(room)
    return RoomResponse.model_validate(room)


# ── Bookings ──────────────────────────────────────────────────────────────


@router.get(
    "/rooms/{room_id}/bookings",
    response_model=BookingListResponse,
    dependencies=[Depends(RequirePermission("accommodation.read"))],
)
async def list_bookings_for_room_endpoint(
    room_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    status_filter: list[str] | None = Query(
        default=None,
        alias="status",
    ),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> BookingListResponse:
    """List bookings for one specific room."""
    statuses = _parse_booking_status_filter(status_filter)
    bookings, room_label_by_id = await list_bookings_for_room(
        session,
        room_id,
        user_id,
        statuses=statuses,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
    items = _decorate_bookings(bookings, room_label_by_id)
    return BookingListResponse(
        items=items,
        total=len(items),
        limit=limit,
        offset=offset,
    )


@router.post(
    "/rooms/{room_id}/bookings",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("accommodation.booking.create"))],
)
async def create_booking(
    room_id: uuid.UUID,
    payload: BookingCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> BookingResponse:
    """Create a booking — gates on room status + payload date validity."""
    room, _accom = await get_room_or_404(session, room_id, user_id)
    assert_room_bookable(room)
    # Block silent double-booking — half-open overlap with any live row.
    await assert_no_booking_overlap(
        session,
        room.id,
        payload.check_in,
        payload.check_out,
    )

    booking = Booking(
        room_id=room.id,
        occupant_contact_id=payload.occupant_contact_id,
        occupant_name=payload.occupant_name,
        check_in=payload.check_in,
        check_out=payload.check_out,
        status=payload.status,
        source=payload.source,
        created_by=str(user_id),
        metadata_=payload.metadata,
    )
    session.add(booking)

    # When the booking lands in an active state, flip the room to
    # occupied. ``reserved`` is held by the room (its slot is committed)
    # but we leave ``available`` flipping until check-in time to mirror
    # real-world hotel/camp practice — front desks reserve rooms without
    # marking them occupied until the guest actually arrives.
    if payload.status == "checked_in":
        room.status = "occupied"

    await session.flush()
    await session.refresh(booking)
    return BookingResponse.model_validate(booking)


@router.get(
    "/bookings/{booking_id}",
    response_model=BookingDetailResponse,
    dependencies=[Depends(RequirePermission("accommodation.read"))],
)
async def get_booking(
    booking_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> BookingDetailResponse:
    """Return one booking with its charges."""
    booking, _room, _accom = await get_booking_or_404(
        session,
        booking_id,
        user_id,
    )
    charges = (
        (await session.execute(select(Charge).where(Charge.booking_id == booking.id).order_by(Charge.created_at.asc())))
        .scalars()
        .all()
    )
    base = BookingResponse.model_validate(booking).model_dump(by_alias=False)
    base["charges"] = [ChargeResponse.model_validate(c) for c in charges]
    return BookingDetailResponse.model_validate(base)


@router.patch(
    "/bookings/{booking_id}",
    response_model=BookingResponse,
    dependencies=[Depends(RequirePermission("accommodation.booking.update"))],
)
async def update_booking(
    booking_id: uuid.UUID,
    payload: BookingUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> BookingResponse:
    """Partial update with state-machine enforcement."""
    booking, room, _accom = await get_booking_or_404(
        session,
        booking_id,
        user_id,
    )
    data = payload.model_dump(exclude_unset=True)
    metadata = data.pop("metadata", None)

    # State-machine gate. ``BookingUpdate.status`` is regex-validated so
    # only legal target labels reach this point — we just check that the
    # transition itself is allowed.
    target_status = data.get("status")
    if target_status is not None and not is_valid_booking_transition(
        booking.status,
        target_status,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Invalid transition: {booking.status} → {target_status}"),
        )

    # If the patch moves the booking dates and the resulting row will
    # still hold the room (i.e. not transitioning to cancelled /
    # checked_out), re-check overlap against the rest of the room's
    # live bookings. Excluding the booking's own id makes a no-op PATCH
    # of identical dates idempotent.
    resulting_status = target_status if target_status is not None else booking.status
    if ("check_in" in data or "check_out" in data) and resulting_status in ("reserved", "checked_in"):
        new_check_in = data.get("check_in", booking.check_in)
        new_check_out = data.get("check_out", booking.check_out)
        await assert_no_booking_overlap(
            session,
            booking.room_id,
            new_check_in,
            new_check_out,
            exclude_booking_id=booking.id,
        )

    for key, value in data.items():
        setattr(booking, key, value)
    if metadata is not None:
        booking.metadata_ = metadata

    # Reflect terminal transitions on the room status — but only when the
    # room isn't actively in maintenance / blocked.
    if target_status == "checked_in" and room.status not in ("maintenance", "blocked"):
        room.status = "occupied"
    elif target_status in ("checked_out", "cancelled") and room.status == "occupied":
        room.status = "available"

    await session.flush()
    await session.refresh(booking)
    return BookingResponse.model_validate(booking)


# ── Charges ───────────────────────────────────────────────────────────────


@router.post(
    "/bookings/{booking_id}/charges",
    response_model=ChargeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("accommodation.charge.create"))],
)
async def create_charge(
    booking_id: uuid.UUID,
    payload: ChargeCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> ChargeResponse:
    """Attach a charge to a booking. Inherits currency from room if blank."""
    booking, room, accom = await get_booking_or_404(
        session,
        booking_id,
        user_id,
    )

    currency = payload.currency
    if not currency:
        # Inherit room → project — never a hardcoded EUR.
        currency = room.base_rate_currency or await inherit_currency_for_room(
            session,
            accom,
            "",
        )

    charge = Charge(
        booking_id=booking.id,
        kind=payload.kind,
        description=payload.description,
        amount=payload.amount,
        currency=currency,
        period_start=payload.period_start,
        period_end=payload.period_end,
        status=payload.status,
        metadata_=payload.metadata,
    )
    session.add(charge)
    await session.flush()
    await session.refresh(charge)
    return ChargeResponse.model_validate(charge)


@router.get(
    "/bookings/{booking_id}/charges",
    response_model=list[ChargeResponse],
    dependencies=[Depends(RequirePermission("accommodation.read"))],
)
async def list_charges(
    booking_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> list[ChargeResponse]:
    """List charges attached to a booking."""
    booking, _room, _accom = await get_booking_or_404(
        session,
        booking_id,
        user_id,
    )
    rows = (
        (await session.execute(select(Charge).where(Charge.booking_id == booking.id).order_by(Charge.created_at.asc())))
        .scalars()
        .all()
    )
    return [ChargeResponse.model_validate(r) for r in rows]


# ── Cross-module integrations ────────────────────────────────────────────


@router.post(
    "/{accommodation_id}/bootstrap-from-propdev/{block_id}",
    response_model=BootstrapFromPropDevResponse,
    dependencies=[
        Depends(RequirePermission("accommodation.bootstrap_from_propdev")),
    ],
)
async def bootstrap_from_propdev(
    accommodation_id: uuid.UUID,
    block_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> BootstrapFromPropDevResponse:
    """One-click: PropDev block plots → Rooms 1:1. Idempotent on re-run."""
    accom = await get_accommodation_or_404(session, accommodation_id, user_id)
    result = await bootstrap_from_propdev_block(session, accom, block_id)
    return BootstrapFromPropDevResponse(**result)  # type: ignore[arg-type]


@router.post(
    "/bookings/suggest-from-hr",
    response_model=SuggestFromHRResponse,
    dependencies=[Depends(RequirePermission("accommodation.suggest_from_hr"))],
)
async def suggest_from_hr(
    payload: SuggestFromHRRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> SuggestFromHRResponse:
    """Return the lowest-labelled available worker-camp room.

    NOT auto-confirmed. The UI must POST the actual booking once the
    operator approves the suggestion.
    """
    room = await suggest_room_for_employee(
        session,
        user_id,
        payload.employee_contact_id,
        payload.start_date,
    )
    accom = await session.get(Accommodation, room.accommodation_id)
    if accom is None:
        # Shouldn't happen — JOIN above guarantees it — but be defensive.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No available room",
        )
    return SuggestFromHRResponse(
        room_id=room.id,
        room_label=room.label,
        accommodation_id=accom.id,
        accommodation_name=accom.name,
        accommodation_kind=accom.kind,
        capacity=room.capacity,
        base_rate=room.base_rate,
        base_rate_currency=room.base_rate_currency,
    )
