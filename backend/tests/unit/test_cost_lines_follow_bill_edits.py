# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bill edits refresh cost lines in batches, never one session per edited row."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.modules.costmodel import events

pytestmark = pytest.mark.asyncio


def _event(**data):
    return SimpleNamespace(data=data)


async def test_a_burst_of_edits_is_refreshed_in_a_few_batches(monkeypatch) -> None:
    batches: list[list[tuple[str, str]]] = []

    async def record(items):
        batches.append(list(items))

    monkeypatch.setattr(events, "_refresh", record)
    ids = [str(uuid.uuid4()) for _ in range(500)]
    for pid in ids:
        await events._on_bill_position_updated(_event(position_id=pid, changes={"quantity": {"old": "1", "new": "2"}}))
    # The same row edited twice is refreshed once.
    await events._on_bill_position_updated(_event(position_id=ids[0], changes={"total": {}}))
    await events._on_bill_position_deleted(_event(position_id=ids[1], boq_id="b1"))
    await events.drain_bill_refresh()

    assert len(batches) <= 4, "one session per batch of rows, not per row"
    flat = [key for batch in batches for key in batch]
    assert sorted(k for k in flat if k[0] == "position") == sorted(("position", p) for p in ids)
    assert ("bill", "b1") in flat


async def test_an_edit_that_moves_no_money_queues_nothing(monkeypatch) -> None:
    batches: list[list[tuple[str, str]]] = []

    async def record(items):
        batches.append(list(items))

    monkeypatch.setattr(events, "_refresh", record)
    await events._on_bill_position_updated(_event(position_id=str(uuid.uuid4()), changes={"description": {}}))
    await events.drain_bill_refresh()
    assert batches == []

    await events._on_bill_position_updated(_event(position_id=str(uuid.uuid4()), changes={"metadata": {}}))
    await events.drain_bill_refresh()
    assert len(batches) == 1, "resources live in metadata and can move the rate"
