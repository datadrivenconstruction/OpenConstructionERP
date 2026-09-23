# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A completed variation moves the contract sum once, and never on a closed contract.

``variations.contract_sum.updated`` is published when a variation order
completes against a contract. Exactly one subscriber owns the rollup into
``Contract.total_value``: ``_on_variation_completed`` in the wave-5
cross-module subscribers. It keys redelivery on the variation, checks project
and currency, dedupes against the mirrored change order and leaves a
terminated or completed contract at its agreed value, the same statuses
``apply_change_order_to_contract`` refuses.

A second subscriber on the same event, ``contracts.events._on_vo_contract_sum_updated``,
used to be registered next to it. It read its argument as a dict while the
bus hands every handler an ``Event``, so it raised on every completed
variation and never moved a value. Had its signature ever been corrected it
would have posted each variation a second time, with none of the guards above
and on closed contracts too. It has been removed.

These tests go through the production wiring (the two registrars that run at
startup) and the real bus, with a payload shaped like the one
``VariationsService.transition_variation_order`` publishes, so the value is
moved by whatever the running app would call and nothing else.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.core.event_handlers as core_handlers
import app.modules.notifications._wave5_cross_module_subscribers as w5
from app.core.events import EventBus
from app.modules.contracts.models import Contract
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import isolated_engine

VO_COMPLETED_EVENT = "variations.contract_sum.updated"
BASE_VALUE = Decimal("100000")
DELTA = Decimal("12500.50")


class _World:
    """A throwaway database holding one project; contracts are added per test."""

    def __init__(self, factory: async_sessionmaker[AsyncSession], project_id: uuid.UUID) -> None:
        self.factory = factory
        self.project_id = project_id

    async def contract(self, status: str) -> uuid.UUID:
        async with self.factory() as session:
            contract = Contract(
                code=f"CT-{uuid.uuid4().hex[:8]}",
                title="Main works",
                project_id=self.project_id,
                status=status,
                currency="EUR",
                total_value=BASE_VALUE,
            )
            session.add(contract)
            await session.commit()
            return contract.id

    async def read(self, contract_id: uuid.UUID) -> tuple[Decimal, dict[str, Any]]:
        """Re-read in a fresh session: the subscriber commits in its own."""
        async with self.factory() as session:
            contract = await session.get(Contract, contract_id)
            assert contract is not None
            return Decimal(str(contract.total_value)), dict(contract.metadata_ or {})

    def payload(self, contract_id: uuid.UUID) -> dict[str, Any]:
        """The keys ``VariationsService.transition_variation_order`` publishes."""
        return {
            "project_id": str(self.project_id),
            "vo_id": str(uuid.uuid4()),
            "contract_id": str(contract_id),
            "code": "VO-001",
            "delta_amount": str(DELTA),
            "currency": "EUR",
            "contract_standard": "",
            "contract_clause_ref": "",
        }


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        # The wave-5 subscriber opens its own session by design; point it at
        # the throwaway database so it reads and writes the rows made here.
        monkeypatch.setattr(w5, "async_session_factory", factory)
        async with factory() as session:
            user = User(
                email=f"vo-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                full_name="Variation rollup",
                role="admin",
            )
            session.add(user)
            await session.flush()
            project = Project(name=f"VO {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="EUR")
            session.add(project)
            await session.commit()
            yield _World(factory, project.id)


@pytest.fixture
def production_bus(monkeypatch: pytest.MonkeyPatch) -> EventBus:
    """A fresh bus wired by the same two registrars the app runs at startup."""
    bus = EventBus()
    monkeypatch.setattr(core_handlers, "event_bus", bus)
    monkeypatch.setattr(w5, "event_bus", bus)
    core_handlers.register_event_handlers()
    w5.register_wave5_notification_subscribers()
    # The outgoing-webhook forwarder listens to every event and opens the
    # application database; it moves no contract value and is not under test.
    bus.unsubscribe("*", core_handlers._dispatch_to_webhooks)
    return bus


def test_one_subscriber_owns_the_variation_rollup(production_bus: EventBus) -> None:
    """Two writers on this event post a completed variation to the contract twice."""
    assert production_bus.list_handlers(VO_COMPLETED_EVENT) == {VO_COMPLETED_EVENT: ["_on_variation_completed"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["active", "suspended"])
async def test_a_completed_variation_moves_a_live_contract_once(
    world: _World, production_bus: EventBus, status: str
) -> None:
    """The control: the same payload does reach the value on a live contract."""
    contract_id = await world.contract(status)

    result = await production_bus.publish(VO_COMPLETED_EVENT, world.payload(contract_id))

    assert result.errors == []
    value, metadata = await world.read(contract_id)
    assert value == BASE_VALUE + DELTA
    assert len(metadata["variation_ids"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "terminated"])
async def test_a_completed_variation_leaves_a_closed_contract_at_its_agreed_value(
    world: _World, production_bus: EventBus, status: str
) -> None:
    """A closed contract keeps its value; a later adjustment goes on the final account."""
    contract_id = await world.contract(status)

    result = await production_bus.publish(VO_COMPLETED_EVENT, world.payload(contract_id))

    assert result.errors == []
    value, metadata = await world.read(contract_id)
    assert value == BASE_VALUE
    assert "variation_ids" not in metadata
