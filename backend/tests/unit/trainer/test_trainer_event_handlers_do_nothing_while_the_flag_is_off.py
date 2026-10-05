# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Trainer event handlers return at their first line while the academy flag is off.

Each case has its twin: with the flag on, the same event reaches the resolver.
A handler that ignored the flag, or one that never resolved anything, fails.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.events import Event
from app.modules.trainer import events


@pytest.fixture
def resolver(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def record(data: dict[str, Any]) -> list[uuid.UUID]:
        calls.append(dict(data))
        return []

    monkeypatch.setattr(events, "mark_stale_for_event", record)
    return calls


def _flag(monkeypatch, on: bool) -> None:
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace(academy_mode=on))


@pytest.mark.parametrize(
    ("handler", "name"),
    [(events.on_erp_event, "boq.position.updated"), (events.on_prefixed_event, "variations.vo.voided")],
)
async def test_a_handler_reads_nothing_while_the_flag_is_off(monkeypatch, resolver, handler, name) -> None:
    event = Event(name=name, data={"project_id": str(uuid.uuid4())})
    _flag(monkeypatch, False)
    await handler(event)
    assert resolver == []

    _flag(monkeypatch, True)
    await handler(event)
    assert resolver == [event.data]


async def test_the_wildcard_handler_takes_only_its_prefixes(monkeypatch, resolver) -> None:
    _flag(monkeypatch, True)
    await events.on_prefixed_event(Event(name="documents.document.created", data={"project_id": "x"}))
    assert resolver == []


async def test_a_seed_event_is_never_learner_activity(monkeypatch, resolver) -> None:
    from app.modules.trainer.seeder import seeding

    _flag(monkeypatch, True)
    with seeding(uuid.uuid4()):
        await events.on_erp_event(Event(name="boq.position.updated", data={"boq_id": str(uuid.uuid4())}))
    assert resolver == []


def test_only_published_or_prefixed_names_are_tracked() -> None:
    assert not any(name.startswith(events.TRACKED_PREFIXES) for name in events.TRACKED_EVENTS)
    assert "boq.position.updated" in events.TRACKED_EVENTS
