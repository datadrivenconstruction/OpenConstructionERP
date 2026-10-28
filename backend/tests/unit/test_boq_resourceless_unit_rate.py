"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Founder bug: a Unit Rate on a position WITHOUT (contributing) resources must
be directly editable and PERSIST; a blank / zero-quantity resource row must not
lock the cell or wipe the manual rate. A position with a REAL resource keeps its
derived, non-editable rate (the resource-driven invariant).

Root cause: the frontend editable predicate and the backend derive decision both
treated ANY non-empty ``metadata.resources`` list as "resource-driven", even a
list whose entries all carry a zero quantity. Such a phantom/degenerate list
locked the Unit Rate cell (frontend) and, on any resources-touching write,
re-derived ``unit_rate`` as ``Σ(qty × rate) = 0`` - silently wiping the manual
rate (backend). Both sides now key off the same notion: a resource contributes
only when it has a non-zero quantity
(``_has_contributing_resources`` / ``hasContributingResources``).

Isolation mirrors ``test_boq_resource_currency_rollup``: each test runs inside a
rolled-back outer transaction via ``tests._pg``.

Run:
    cd backend
    python -m pytest tests/unit/test_boq_resourceless_unit_rate.py -v --tb=short
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.boq.schemas import PositionUpdate
from app.modules.boq.service import BOQService, _has_contributing_resources
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        from app.modules.users.models import User

        s.add(
            User(
                id=OWNER_ID,
                email=f"o-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x",
                full_name="O",
            )
        )
        await s.flush()
        await s.commit()
        yield s


async def _make_position(
    session,
    *,
    unit_rate: str,
    quantity: str = "2",
    metadata_: dict | None = None,
):
    """Create Project + BOQ + one leaf Position; return (service, position)."""
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    session.add(Project(id=project_id, name="P", owner_id=OWNER_ID, currency="EUR"))
    await session.flush()
    boq = BOQ(id=uuid.uuid4(), project_id=project_id, name="B")
    session.add(boq)
    await session.flush()

    total = str(Decimal(quantity) * Decimal(unit_rate))
    pos = Position(
        id=uuid.uuid4(),
        boq_id=boq.id,
        ordinal="0010",
        description="p",
        unit="m3",
        quantity=quantity,
        unit_rate=unit_rate,
        total=total,
        metadata_=metadata_,
        sort_order=10,
    )
    session.add(pos)
    await session.commit()
    return BOQService(session), pos


# ── Pure predicate ───────────────────────────────────────────────────────


def test_has_contributing_resources_pure():
    # Nothing / empty / wrong type → no resources.
    assert _has_contributing_resources(None) is False
    assert _has_contributing_resources([]) is False
    assert _has_contributing_resources("nope") is False
    # A list whose every entry has a zero (or blank / non-numeric) quantity is
    # degenerate → still "no contributing resources".
    assert _has_contributing_resources([{"quantity": 0, "unit_rate": 5}]) is False
    assert _has_contributing_resources([{"quantity": 0}, {"quantity": 0.0}]) is False
    assert _has_contributing_resources([{"name": "blank"}]) is False
    assert _has_contributing_resources([{"quantity": "abc"}]) is False
    assert _has_contributing_resources(["not-a-dict", {"quantity": 0}]) is False
    # A non-zero quantity contributes even when the price is still 0 (the user
    # adds the resource line first, then fills in the price).
    assert _has_contributing_resources([{"quantity": 1, "unit_rate": 0}]) is True
    assert _has_contributing_resources([{"quantity": "2.5", "unit_rate": 30}]) is True
    assert _has_contributing_resources([{"quantity": 0}, {"quantity": 3}]) is True


# ── (a) Founder scenario — resource-less rate stays editable + persists ────


@pytest.mark.asyncio
async def test_blank_zero_quantity_resource_does_not_wipe_manual_rate(session):
    """Adding a blank / zero-quantity resource row must NOT re-derive the rate
    to 0. The position is treated as resource-less: its manual rate stands.

    This is the exact defect the founder hit: before the fix the write derived
    ``unit_rate = Σ(0 × 0) = 0`` and the manual rate vanished.
    """
    service, pos = await _make_position(session, unit_rate="50", quantity="2")

    updated = await service.update_position(
        pos.id,
        PositionUpdate(
            metadata={
                "resources": [
                    {"name": "blank", "type": "material", "unit": "m3", "quantity": 0, "unit_rate": 0},
                ],
            },
        ),
        actor_id=OWNER_ID,
    )

    assert Decimal(str(updated.unit_rate)) == Decimal("50"), "manual rate must survive a blank resource row"
    assert Decimal(str(updated.total)) == Decimal("100")  # 2 × 50


@pytest.mark.asyncio
async def test_direct_unit_rate_edit_persists_on_degenerate_resource_position(session):
    """A position carrying only a zero-quantity resource is directly priceable:
    a typed Unit Rate persists and reads back unchanged (survives the write)."""
    service, pos = await _make_position(
        session,
        unit_rate="0",
        quantity="2",
        metadata_={
            "resources": [
                {"name": "blank", "type": "material", "unit": "m3", "quantity": 0, "unit_rate": 0},
            ],
        },
    )

    updated = await service.update_position(
        pos.id,
        PositionUpdate(unit_rate=Decimal("123.45")),  # bare edit, as the now-editable cell sends
        actor_id=OWNER_ID,
    )

    assert Decimal(str(updated.unit_rate)) == Decimal("123.45")
    assert Decimal(str(updated.total)) == Decimal("246.90")  # 2 × 123.45

    # Read back from the DB to prove it survives the round-trip, not just the
    # in-memory refresh.
    reread = await service.position_repo.get_by_id(pos.id)
    assert Decimal(str(reread.unit_rate)) == Decimal("123.45")


# ── (b) Invariant — a real resource drives the rate, and wins over a submit ─


@pytest.mark.asyncio
async def test_real_resource_derives_unit_rate(session):
    """A resource with a non-zero quantity drives the rate: ``unit_rate`` is the
    Σ of per-unit resource subtotals, not a typed value."""
    service, pos = await _make_position(session, unit_rate="0", quantity="2")

    updated = await service.update_position(
        pos.id,
        PositionUpdate(
            metadata={
                "resources": [
                    {"name": "concrete", "type": "material", "unit": "m3", "quantity": 2, "unit_rate": 30},
                ],
            },
        ),
        actor_id=OWNER_ID,
    )

    # Per-unit norm: 2 × 30 = 60 (no division by position qty).
    assert Decimal(str(updated.unit_rate)) == Decimal("60")
    assert Decimal(str(updated.total)) == Decimal("120")  # position qty 2 × 60


@pytest.mark.asyncio
async def test_real_resource_rate_is_authoritative_over_submitted_value(session):
    """The resources-present invariant: when a contributing resource is written,
    the derived Σ wins even if the same PATCH also submits a bogus ``unit_rate``.
    The cell is never directly editable while a real resource prices the line."""
    service, pos = await _make_position(session, unit_rate="0", quantity="2")

    updated = await service.update_position(
        pos.id,
        PositionUpdate(
            unit_rate=Decimal("999"),  # tampered / stale client value
            metadata={
                "resources": [
                    {"name": "concrete", "type": "material", "unit": "m3", "quantity": 2, "unit_rate": 30},
                ],
            },
        ),
        actor_id=OWNER_ID,
    )

    assert Decimal(str(updated.unit_rate)) == Decimal("60"), "derived rate must override the submitted value"
