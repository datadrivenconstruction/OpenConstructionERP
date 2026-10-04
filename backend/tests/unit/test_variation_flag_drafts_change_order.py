# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A flagged variation becomes a DRAFT change order, once, linked to its source.

``variation.flagged`` used to reach nothing but the outgoing-webhook wildcard,
and neither of its two triggers fired at all: the RFI flag listened for
``rfi.response.design_change``, which nothing published, and the NCR flag for
``ncr.cost_impact``, while the NCR module publishes
``ncr.closed_with_cost_impact``. So an answered RFI with a cost impact, or a
closed NCR with one, left no trace in the change order register unless
somebody remembered to press "create variation".

What these tests hold:

* the draft is a draft (no money moves until a person approves it),
* its amount, currency and days come from the source record, not the payload,
* the same flag twice, or four at once, gives one change order,
* the subscriber and the manual "create variation" action share one record in
  both orders of arrival,
* a payload naming another project's record creates nothing.

The database half runs on a throwaway PostgreSQL database because the
subscriber opens its own session through ``app.database.async_session_factory``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import event_handlers
from app.core.events import Event, EventBus, event_bus
from app.modules.changeorders.events import (
    AMOUNT_NEEDS_REVIEW_KEY,
    AUTO_DRAFTED_KEY,
    VARIATION_FLAGGED,
    _on_variation_flagged,
    register_changeorder_event_subscribers,
)
from app.modules.changeorders.models import ChangeOrder
from app.modules.ncr.models import NCR
from app.modules.projects.models import Project
from app.modules.rfi.models import RFI
from app.modules.users.models import User
from tests._pg import isolated_engine

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def _module_db() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def factory(
    _module_db: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> async_sessionmaker[AsyncSession]:
    import app.database as database_module

    monkeypatch.setattr(database_module, "async_session_factory", _module_db)
    return _module_db


async def _project(factory: async_sessionmaker[AsyncSession], currency: str = "EUR") -> tuple[uuid.UUID, uuid.UUID]:
    async with factory() as s:
        user = User(
            email=f"vf-{uuid.uuid4().hex[:10]}@datadrivenconstruction.io",
            hashed_password="x" * 16,
            full_name="Variation Flag",
        )
        s.add(user)
        await s.flush()
        project = Project(
            id=uuid.uuid4(),
            name=f"VF {uuid.uuid4().hex[:6]}",
            owner_id=user.id,
            currency=currency,
            region="DACH",
            classification_standard="din276",
            metadata_={},
            fx_rates=[],
        )
        s.add(project)
        await s.commit()
        return project.id, user.id


async def _rfi(
    factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    raised_by: uuid.UUID,
    *,
    status: str = "answered",
    cost_impact: bool = True,
    value: str | None = "12500.50",
    days: int | None = 7,
) -> uuid.UUID:
    async with factory() as s:
        rfi = RFI(
            project_id=project_id,
            rfi_number=f"RFI-{uuid.uuid4().hex[:4]}",
            subject="Beam depth at grid C",
            question="Can the beam at grid C be 450 deep?",
            raised_by=raised_by,
            status=status,
            official_response="Use 500 deep, revised drawing S-201 rev B." if status != "open" else None,
            cost_impact=cost_impact,
            cost_impact_value=value,
            schedule_impact=days is not None,
            schedule_impact_days=days,
        )
        s.add(rfi)
        await s.commit()
        return rfi.id


async def _ncr(
    factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    status: str = "closed",
    cost: str | None = "BRL 12,000",
    days: int | None = 3,
) -> uuid.UUID:
    async with factory() as s:
        ncr = NCR(
            project_id=project_id,
            ncr_number=f"NCR-{uuid.uuid4().hex[:4]}",
            title="Honeycombing in core wall",
            description="Core wall level 3 shows honeycombing over 2 m2.",
            ncr_type="workmanship",
            severity="major",
            status=status,
            corrective_action="Break out and recast.",
            cost_impact=cost,
            schedule_impact_days=days,
        )
        s.add(ncr)
        await s.commit()
        return ncr.id


async def _orders(factory: async_sessionmaker[AsyncSession], project_id: uuid.UUID) -> list[ChangeOrder]:
    async with factory() as s:
        rows = await s.execute(select(ChangeOrder).where(ChangeOrder.project_id == project_id))
        return list(rows.scalars().all())


def _flag(source_type: str, source_id: Any, project_id: Any) -> Event:
    return Event(
        name=VARIATION_FLAGGED,
        data={"source_type": source_type, "source_id": str(source_id), "project_id": str(project_id)},
    )


# ── Wiring ──────────────────────────────────────────────────────────────────


def test_the_subscriber_is_registered_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.changeorders import events as co_events

    bus = EventBus()
    monkeypatch.setattr(co_events, "event_bus", bus)

    register_changeorder_event_subscribers()
    register_changeorder_event_subscribers()

    assert bus._handlers[VARIATION_FLAGGED] == [_on_variation_flagged]


def test_the_flag_handlers_listen_for_names_that_are_published(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = EventBus()
    monkeypatch.setattr(event_handlers, "event_bus", bus)

    event_handlers.register_event_handlers()

    assert event_handlers._handle_ncr_cost_impact in bus._handlers.get("ncr.closed_with_cost_impact", [])
    assert event_handlers._handle_rfi_response_design_change in bus._handlers.get("rfi.response.design_change", [])
    assert "ncr.cost_impact" not in bus._handlers


# ── RFI ─────────────────────────────────────────────────────────────────────


async def test_an_answered_rfi_with_a_cost_becomes_one_draft(factory: async_sessionmaker[AsyncSession]) -> None:
    project_id, user_id = await _project(factory)
    rfi_id = await _rfi(factory, project_id, user_id)

    await _on_variation_flagged(_flag("rfi", rfi_id, project_id))

    (order,) = await _orders(factory, project_id)
    assert order.status == "draft", "an event must never approve money"
    assert order.cost_impact == Decimal("12500.50")
    assert order.schedule_impact_days == 7
    assert order.currency == "EUR"
    assert order.reason_category == "client_request", "must match what the manual action records"
    assert order.approved_amount is None
    assert order.metadata_["source"] == "rfi"
    assert order.metadata_["rfi_id"] == str(rfi_id)
    assert order.metadata_[AUTO_DRAFTED_KEY] is True
    assert order.linked_rfi_ids == [str(rfi_id)]
    async with factory() as s:
        assert (await s.get(RFI, rfi_id)).change_order_id == str(order.id)


async def test_the_same_flag_twice_drafts_once(factory: async_sessionmaker[AsyncSession]) -> None:
    project_id, user_id = await _project(factory)
    rfi_id = await _rfi(factory, project_id, user_id)

    await _on_variation_flagged(_flag("rfi", rfi_id, project_id))
    await _on_variation_flagged(_flag("rfi", rfi_id, project_id))

    assert len(await _orders(factory, project_id)) == 1


async def test_concurrent_flags_draft_once(factory: async_sessionmaker[AsyncSession]) -> None:
    project_id, user_id = await _project(factory)
    rfi_id = await _rfi(factory, project_id, user_id)

    await asyncio.gather(*(_on_variation_flagged(_flag("rfi", rfi_id, project_id)) for _ in range(4)))

    assert len(await _orders(factory, project_id)) == 1


@pytest.mark.parametrize(
    ("status", "cost_impact"),
    [("open", True), ("draft", True), ("answered", False)],
)
async def test_an_rfi_that_does_not_qualify_drafts_nothing(
    factory: async_sessionmaker[AsyncSession],
    status: str,
    cost_impact: bool,
) -> None:
    project_id, user_id = await _project(factory)
    rfi_id = await _rfi(factory, project_id, user_id, status=status, cost_impact=cost_impact)

    await _on_variation_flagged(_flag("rfi", rfi_id, project_id))

    assert await _orders(factory, project_id) == []


async def test_a_payload_naming_another_projects_rfi_drafts_nothing(factory: async_sessionmaker[AsyncSession]) -> None:
    """The project in the payload must be the record's own."""
    project_a, user_a = await _project(factory)
    project_b, _ = await _project(factory)
    rfi_id = await _rfi(factory, project_a, user_a)

    await _on_variation_flagged(_flag("rfi", rfi_id, project_b))

    assert await _orders(factory, project_a) == []
    assert await _orders(factory, project_b) == []


async def test_an_rfi_without_an_amount_drafts_at_zero(factory: async_sessionmaker[AsyncSession]) -> None:
    """Flagged with a cost but not yet priced: the draft is there to be priced."""
    project_id, user_id = await _project(factory)
    rfi_id = await _rfi(factory, project_id, user_id, value=None, days=None)

    await _on_variation_flagged(_flag("rfi", rfi_id, project_id))

    (order,) = await _orders(factory, project_id)
    assert order.cost_impact == Decimal("0")
    assert order.schedule_impact_days == 0


# ── NCR ─────────────────────────────────────────────────────────────────────


async def test_a_closed_ncr_with_a_currency_coded_cost_drafts_in_that_currency(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """``"BRL 12,000"`` is 12000 in reais, not zero and not 12 euros."""
    project_id, _ = await _project(factory, currency="EUR")
    ncr_id = await _ncr(factory, project_id)

    await _on_variation_flagged(_flag("ncr", ncr_id, project_id))

    (order,) = await _orders(factory, project_id)
    assert order.status == "draft"
    assert order.cost_impact == Decimal("12000")
    assert order.currency == "BRL"
    assert order.schedule_impact_days == 3
    assert order.reason_category == "non_conformance"
    assert order.metadata_["ncr_id"] == str(ncr_id)
    assert order.metadata_["ncr_cost_impact_raw"] == "BRL 12,000"
    async with factory() as s:
        assert (await s.get(NCR, ncr_id)).change_order_id == str(order.id)


async def test_a_plain_ncr_amount_takes_the_project_currency(factory: async_sessionmaker[AsyncSession]) -> None:
    project_id, _ = await _project(factory, currency="GBP")
    ncr_id = await _ncr(factory, project_id, cost="4500")

    await _on_variation_flagged(_flag("ncr", ncr_id, project_id))

    (order,) = await _orders(factory, project_id)
    assert (order.cost_impact, order.currency) == (Decimal("4500"), "GBP")


@pytest.mark.parametrize(
    ("cost", "amount", "currency"),
    [
        # The old reader stripped commas only: 12.00, 12.5005, an exception and
        # no match. Each would have been a draft off by a thousand, or none.
        ("BRL 12.000,00", "12000.00", "BRL"),
        ("EUR 12.500,50", "12500.50", "EUR"),
        ("1.234.567", "1234567", "GBP"),
        ("12000 EUR", "12000", "EUR"),
        ("RUB 1 234 567,89", "1234567.89", "RUB"),
    ],
)
async def test_an_ncr_cost_is_read_in_the_convention_it_was_written_in(
    factory: async_sessionmaker[AsyncSession],
    cost: str,
    amount: str,
    currency: str,
) -> None:
    project_id, _ = await _project(factory, currency="GBP")
    ncr_id = await _ncr(factory, project_id, cost=cost)

    await _on_variation_flagged(_flag("ncr", ncr_id, project_id))

    (order,) = await _orders(factory, project_id)
    assert (order.cost_impact, order.currency) == (Decimal(amount), currency)
    assert AMOUNT_NEEDS_REVIEW_KEY not in order.metadata_


@pytest.mark.parametrize(
    ("project_currency", "cost", "why"),
    [
        # Twelve and a half dinar, or twelve thousand five hundred.
        ("KWD", "12.500", "ambiguous"),
        ("EUR", "KWD 1,250", "ambiguous"),
        # Digits, but not one amount.
        ("EUR", "approx. 5000", "unreadable"),
        ("EUR", "5000-6000", "unreadable"),
    ],
)
async def test_a_cost_that_cannot_be_read_drafts_at_zero_and_asks_for_the_amount(
    factory: async_sessionmaker[AsyncSession],
    project_currency: str,
    cost: str,
    why: str,
) -> None:
    """A blank a person must fill beats a plausible wrong number, and beats no draft."""
    project_id, _ = await _project(factory, currency=project_currency)
    ncr_id = await _ncr(factory, project_id, cost=cost)

    await _on_variation_flagged(_flag("ncr", ncr_id, project_id))

    (order,) = await _orders(factory, project_id)
    assert order.status == "draft"
    assert order.cost_impact == Decimal("0")
    assert order.metadata_[AMOUNT_NEEDS_REVIEW_KEY] == why
    assert order.metadata_["ncr_cost_impact_raw"] == cost


async def test_the_ncr_action_reads_the_cost_the_same_way(factory: async_sessionmaker[AsyncSession]) -> None:
    """Pressing "create variation" by hand must not still read 12.000,00 as twelve."""
    from app.modules.ncr.router import create_variation_from_ncr
    from app.modules.ncr.service import NCRService

    project_id, user_id = await _project(factory, currency="EUR")
    ncr_id = await _ncr(factory, project_id, cost="BRL 12.000,00")
    ambiguous_id = await _ncr(factory, project_id, cost="approx. 5000")

    async with factory() as s:
        for source_id in (ncr_id, ambiguous_id):
            await create_variation_from_ncr(
                ncr_id=source_id,
                session=s,
                user_id=str(user_id),
                _perm=None,
                service=NCRService(s),
            )
        await s.commit()

    by_ncr = {o.metadata_["ncr_id"]: o for o in await _orders(factory, project_id)}
    read = by_ncr[str(ncr_id)]
    assert (read.cost_impact, read.currency) == (Decimal("12000.00"), "BRL")
    assert AMOUNT_NEEDS_REVIEW_KEY not in read.metadata_
    unread = by_ncr[str(ambiguous_id)]
    assert (unread.cost_impact, unread.currency) == (Decimal("0"), "EUR")
    assert unread.metadata_[AMOUNT_NEEDS_REVIEW_KEY] == "unreadable"


@pytest.mark.parametrize(
    ("status", "cost"),
    [("verification", "5000"), ("void", "5000"), ("closed", "to be assessed"), ("closed", "0"), ("closed", None)],
)
async def test_an_ncr_that_does_not_qualify_drafts_nothing(
    factory: async_sessionmaker[AsyncSession],
    status: str,
    cost: str | None,
) -> None:
    project_id, _ = await _project(factory)
    ncr_id = await _ncr(factory, project_id, status=status, cost=cost)

    await _on_variation_flagged(_flag("ncr", ncr_id, project_id))

    assert await _orders(factory, project_id) == []


# ── Idempotency against the manual action ───────────────────────────────────


async def test_an_order_raised_by_hand_first_is_not_duplicated(factory: async_sessionmaker[AsyncSession]) -> None:
    project_id, _ = await _project(factory)
    ncr_id = await _ncr(factory, project_id)
    async with factory() as s:
        manual = ChangeOrder(project_id=project_id, code="CO-001", title="By hand", metadata_={})
        s.add(manual)
        await s.flush()
        (await s.get(NCR, ncr_id)).change_order_id = str(manual.id)
        await s.commit()

    await _on_variation_flagged(_flag("ncr", ncr_id, project_id))

    assert [o.code for o in await _orders(factory, project_id)] == ["CO-001"]


async def test_a_lost_back_link_is_restored_instead_of_drafting_again(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id, _ = await _project(factory)
    ncr_id = await _ncr(factory, project_id)
    async with factory() as s:
        earlier = ChangeOrder(
            project_id=project_id,
            code="CO-001",
            title="Earlier",
            status="rejected",
            metadata_={"source": "ncr", "ncr_id": str(ncr_id)},
        )
        s.add(earlier)
        await s.commit()
        earlier_id = earlier.id

    await _on_variation_flagged(_flag("ncr", ncr_id, project_id))

    orders = await _orders(factory, project_id)
    assert [o.id for o in orders] == [earlier_id], "a rejected draft must not come back on a replay"
    async with factory() as s:
        assert (await s.get(NCR, ncr_id)).change_order_id == str(earlier_id)


async def test_the_manual_action_after_the_draft_returns_the_draft(factory: async_sessionmaker[AsyncSession]) -> None:
    """Pressing "create variation" on the RFI must open the draft, not mint a second."""
    from app.modules.rfi.router import create_variation_from_rfi
    from app.modules.rfi.service import RFIService

    project_id, user_id = await _project(factory)
    rfi_id = await _rfi(factory, project_id, user_id)
    await _on_variation_flagged(_flag("rfi", rfi_id, project_id))
    (draft,) = await _orders(factory, project_id)

    async with factory() as s:
        response = await create_variation_from_rfi(
            rfi_id=rfi_id,
            user_id=str(user_id),
            session=s,
            _perm=None,
            _co_perm=None,
            service=RFIService(s),
        )
        await s.commit()

    assert response.change_order_id == str(draft.id)
    assert len(await _orders(factory, project_id)) == 1


async def test_the_manual_action_racing_the_subscriber_still_yields_one_order(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """A person pressing the button the moment the RFI is answered.

    Both sides lock the RFI row before reading its link, so whichever runs
    second sees the first one's order. Run in both start orders, several
    times, because a race that loses once proves nothing.
    """
    from app.modules.rfi.router import create_variation_from_rfi
    from app.modules.rfi.service import RFIService

    async def manual(rfi_id: uuid.UUID, user_id: uuid.UUID) -> str:
        async with factory() as s:
            response = await create_variation_from_rfi(
                rfi_id=rfi_id,
                user_id=str(user_id),
                session=s,
                _perm=None,
                _co_perm=None,
                service=RFIService(s),
            )
            await asyncio.sleep(0.01)  # hold the lock across a yield, as a real request does
            await s.commit()
            return response.change_order_id

    for manual_first in (True, False, True, False):
        project_id, user_id = await _project(factory)
        rfi_id = await _rfi(factory, project_id, user_id)
        auto = _on_variation_flagged(_flag("rfi", rfi_id, project_id))
        by_hand = manual(rfi_id, user_id)
        results = await asyncio.gather(*((by_hand, auto) if manual_first else (auto, by_hand)))

        orders = await _orders(factory, project_id)
        assert len(orders) == 1, f"manual_first={manual_first}: {len(orders)} change orders for one RFI"
        returned = results[0] if manual_first else results[1]
        assert returned == str(orders[0].id)
        async with factory() as s:
            assert (await s.get(RFI, rfi_id)).change_order_id == str(orders[0].id)


async def test_the_ncr_action_racing_the_subscriber_still_yields_one_order(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    from app.modules.ncr.router import create_variation_from_ncr
    from app.modules.ncr.service import NCRService

    async def manual(ncr_id: uuid.UUID, user_id: uuid.UUID) -> str:
        async with factory() as s:
            response = await create_variation_from_ncr(
                ncr_id=ncr_id,
                session=s,
                user_id=str(user_id),
                _perm=None,
                service=NCRService(s),
            )
            await asyncio.sleep(0.01)
            await s.commit()
            return response["change_order_id"]

    for manual_first in (True, False):
        project_id, user_id = await _project(factory)
        ncr_id = await _ncr(factory, project_id)
        auto = _on_variation_flagged(_flag("ncr", ncr_id, project_id))
        by_hand = manual(ncr_id, user_id)
        await asyncio.gather(*((by_hand, auto) if manual_first else (auto, by_hand)))

        assert len(await _orders(factory, project_id)) == 1, f"manual_first={manual_first}"


async def test_a_code_collision_keeps_the_source_locked_until_the_link_is_written(
    factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The subscriber's CO-NNN code collides with another order mid-draft.

    ``create_order`` retries a collided code. It used to do that with a full
    ``session.rollback()``, which released the subscriber's lock on the NCR row
    after the "already has an order?" check had passed. A person pressing
    "create variation" in that gap minted a second order for the same cost.
    The probe below stands in for that person: it tries to take the row lock
    at the moment of the retry and must find it still held.
    """
    from sqlalchemy.exc import DBAPIError

    from app.modules.changeorders.repository import ChangeOrderRepository

    project_id, _ = await _project(factory)
    ncr_id = await _ncr(factory, project_id)
    async with factory() as s:
        other = ChangeOrder(project_id=project_id, code="CO-001", title="Unrelated", metadata_={})
        s.add(other)
        await s.commit()
        other_id = other.id

    real_count = ChangeOrderRepository.count_for_project
    probes: list[str] = []

    async def stale_then_real(self: ChangeOrderRepository, pid: uuid.UUID) -> int:
        if not probes:
            probes.append("stale count")
            return 0  # mints CO-001, which the unrelated order already holds
        async with factory() as probe:
            try:
                await probe.execute(select(NCR.id).where(NCR.id == ncr_id).with_for_update(nowait=True))
                probes.append("source row free")
            except DBAPIError:
                probes.append("source row locked")
            await probe.rollback()
        return await real_count(self, pid)

    monkeypatch.setattr(ChangeOrderRepository, "count_for_project", stale_then_real)

    await _on_variation_flagged(_flag("ncr", ncr_id, project_id))

    assert probes == ["stale count", "source row locked"], "the retry released the lock on the NCR"
    orders = {o.id: o for o in await _orders(factory, project_id)}
    assert len(orders) == 2, "the draft is missing, or the collision left a stray order"
    assert orders[other_id].code == "CO-001"
    assert orders[other_id].metadata_ == {}, "the unrelated order was touched"
    (draft,) = [o for o in orders.values() if o.id != other_id]
    assert draft.metadata_["ncr_id"] == str(ncr_id)
    assert draft.cost_impact == Decimal("12000")
    async with factory() as s:
        assert (await s.get(NCR, ncr_id)).change_order_id == str(draft.id)


# ── The whole chain ─────────────────────────────────────────────────────────


@pytest.fixture
def chain(monkeypatch: pytest.MonkeyPatch) -> EventBus:
    """A private bus carrying the flag handlers and the change order subscriber."""
    from app.modules.changeorders import events as co_events

    bus = EventBus()
    monkeypatch.setattr(event_handlers, "event_bus", bus)
    monkeypatch.setattr(co_events, "event_bus", bus)
    event_handlers.register_event_handlers()
    register_changeorder_event_subscribers()
    return bus


async def test_ncr_closed_with_cost_impact_reaches_the_register(
    factory: async_sessionmaker[AsyncSession],
    chain: EventBus,
) -> None:
    project_id, _ = await _project(factory)
    ncr_id = await _ncr(factory, project_id)

    await chain.publish(
        "ncr.closed_with_cost_impact",
        {
            "ncr_id": str(ncr_id),
            "project_id": str(project_id),
            "ncr_number": "NCR-001",
            "title": "Honeycombing in core wall",
            "cost_impact": "BRL 12,000",
            "schedule_impact_days": 3,
        },
    )

    (order,) = await _orders(factory, project_id)
    assert order.cost_impact == Decimal("12000")


async def test_an_ncr_cost_nobody_can_read_still_reaches_the_register(
    factory: async_sessionmaker[AsyncSession],
    chain: EventBus,
) -> None:
    """The flag must not drop a cost the draft would ask a person to enter."""
    project_id, _ = await _project(factory, currency="KWD")
    ncr_id = await _ncr(factory, project_id, cost="12.500")

    await chain.publish(
        "ncr.closed_with_cost_impact",
        {
            "ncr_id": str(ncr_id),
            "project_id": str(project_id),
            "ncr_number": "NCR-002",
            "title": "Honeycombing in core wall",
            "cost_impact": "12.500",
        },
    )

    (order,) = await _orders(factory, project_id)
    assert order.cost_impact == Decimal("0")
    assert order.metadata_[AMOUNT_NEEDS_REVIEW_KEY] == "ambiguous"


@pytest.mark.parametrize("cost", ["0", "to be assessed", "-500"])
async def test_an_ncr_without_a_positive_cost_raises_no_flag(
    factory: async_sessionmaker[AsyncSession],
    chain: EventBus,
    cost: str,
) -> None:
    project_id, _ = await _project(factory)
    ncr_id = await _ncr(factory, project_id, cost=cost)

    await chain.publish(
        "ncr.closed_with_cost_impact",
        {"ncr_id": str(ncr_id), "project_id": str(project_id), "cost_impact": cost},
    )

    assert await _orders(factory, project_id) == []


async def test_rfi_design_change_reaches_the_register(
    factory: async_sessionmaker[AsyncSession],
    chain: EventBus,
) -> None:
    project_id, user_id = await _project(factory)
    rfi_id = await _rfi(factory, project_id, user_id)

    await chain.publish(
        "rfi.response.design_change",
        {
            "project_id": str(project_id),
            "rfi_id": str(rfi_id),
            "rfi_number": "RFI-001",
            "subject": "Beam depth at grid C",
            "cost_impact": True,
            "cost_impact_value": "12500.50",
        },
    )

    assert len(await _orders(factory, project_id)) == 1


# ── The publishers ──────────────────────────────────────────────────────────


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """What the publishers really hand the bus, captured at publish_detached."""
    seen: list[tuple[str, dict[str, Any]]] = []

    def _record(name: str, data: dict | None = None, source_module: str | None = None) -> None:
        seen.append((name, dict(data or {})))

    monkeypatch.setattr(event_bus, "publish_detached", _record)
    return seen


async def test_answering_a_cost_rfi_publishes_the_design_change_after_commit(
    factory: async_sessionmaker[AsyncSession],
    recorded: list[tuple[str, dict[str, Any]]],
) -> None:
    from app.modules.rfi.service import RFIService

    project_id, user_id = await _project(factory)
    rfi_id = await _rfi(factory, project_id, user_id, status="open")

    async with factory() as s:
        await RFIService(s).respond_to_rfi(rfi_id, "Use 500 deep.", str(user_id))
        assert "rfi.response.design_change" not in [n for n, _ in recorded], "published before the commit"
        await s.commit()

    payloads = [d for n, d in recorded if n == "rfi.response.design_change"]
    assert len(payloads) == 1
    assert payloads[0]["rfi_id"] == str(rfi_id)
    assert payloads[0]["project_id"] == str(project_id)
    assert payloads[0]["cost_impact"] is True


async def test_answering_an_rfi_without_cost_publishes_no_design_change(
    factory: async_sessionmaker[AsyncSession],
    recorded: list[tuple[str, dict[str, Any]]],
) -> None:
    from app.modules.rfi.service import RFIService

    project_id, user_id = await _project(factory)
    rfi_id = await _rfi(factory, project_id, user_id, status="open", cost_impact=False)

    async with factory() as s:
        await RFIService(s).respond_to_rfi(rfi_id, "No change needed.", str(user_id))
        await s.commit()

    assert "rfi.response.design_change" not in [n for n, _ in recorded]


async def test_closing_a_costed_ncr_publishes_after_commit(
    factory: async_sessionmaker[AsyncSession],
    recorded: list[tuple[str, dict[str, Any]]],
) -> None:
    from app.modules.ncr.service import NCRService

    project_id, _ = await _project(factory)
    ncr_id = await _ncr(factory, project_id, status="verification")

    async with factory() as s:
        await NCRService(s).close_ncr(ncr_id)
        assert "ncr.closed_with_cost_impact" not in [n for n, _ in recorded], "published before the commit"
        await s.commit()

    payloads = [d for n, d in recorded if n == "ncr.closed_with_cost_impact"]
    assert len(payloads) == 1
    assert payloads[0]["ncr_id"] == str(ncr_id)
    assert payloads[0]["cost_impact"] == "BRL 12,000"
