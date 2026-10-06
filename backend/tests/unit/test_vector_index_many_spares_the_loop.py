# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Indexing a batch of rows must not stall the event loop either.

A bill created row by row is indexed in batches through
``app.core.vector_index.index_many``, the same way ``index_one`` handles a
single edit. Clipping the text asks for the embedder, which waits on the
model-load lock while another thread loads the model, and the store write is
synchronous disk I/O. On the loop, a 200-row batch froze every request served
by the process for as long as either took. Checked by thread identity, with an
embedder that only returns once the loop itself releases it.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any

import pytest

from app.core import vector as vector_mod
from app.core import vector_index as vector_index_mod
from app.core.vector_index import delete_many, index_many
from app.modules.boq.models import Position
from app.modules.boq.vector_adapter import boq_position_adapter

PROJECT_ID = str(uuid.uuid4())


def _position(n: int) -> Position:
    return Position(
        id=uuid.uuid4(),
        boq_id=uuid.uuid4(),
        ordinal=f"01.02.{n:03d}",
        description=f"Reinforced concrete wall C30/37, {n} cm",
        unit="m3",
        quantity="10",
        unit_rate="185.00",
        total="1850.00",
        classification={"din276": "330"},
        validation_status="pending",
        source="manual",
        metadata_={},
    )


class _Store:
    def __init__(self) -> None:
        self.threads: list[tuple[str, int]] = []
        self.written: list[dict[str, Any]] = []

    def put(self, _collection: str, items: list[dict[str, Any]]) -> int:
        self.threads.append(("write", threading.get_ident()))
        self.written.extend(items)
        return len(items)

    def delete(self, _collection: str, ids: list[str]) -> int:
        self.threads.append(("delete", threading.get_ident()))
        return len(ids)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _Store:
    fake = _Store()

    async def fake_encode(texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(vector_index_mod, "vector_index_collection", fake.put)
    monkeypatch.setattr(vector_index_mod, "vector_delete_collection", fake.delete)
    monkeypatch.setattr(vector_index_mod, "encode_texts_async", fake_encode)
    monkeypatch.setattr(vector_mod, "get_embedder", lambda: None)
    return fake


async def test_the_embedder_and_the_store_are_reached_off_the_loop(
    store: _Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()
    seen: dict[str, Any] = {}

    def embedder_busy_loading() -> None:
        seen.setdefault("embedder_thread", threading.get_ident())
        seen["released_by_loop"] = release.wait(timeout=20)

    monkeypatch.setattr(vector_mod, "get_embedder", embedder_busy_loading)
    loop_thread = threading.get_ident()
    rows = [_position(n) for n in range(3)]

    task = asyncio.create_task(index_many(boq_position_adapter, rows, project_id=PROJECT_ID))
    await asyncio.sleep(0)
    release.set()
    assert await task == 3

    assert seen["released_by_loop"] is True, "the event loop was blocked while the embedder waited"
    assert seen["embedder_thread"] != loop_thread
    assert store.threads and all(ident != loop_thread for _, ident in store.threads), store.threads
    assert {item["project_id"] for item in store.written} == {PROJECT_ID}


async def test_a_batch_delete_is_reached_off_the_loop(store: _Store) -> None:
    loop_thread = threading.get_ident()
    assert await delete_many(boq_position_adapter, [str(uuid.uuid4()), str(uuid.uuid4())]) == 2
    assert store.threads and all(ident != loop_thread for _, ident in store.threads), store.threads
