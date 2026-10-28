"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Re-indexing a BOQ position after an edit must not stall the event loop.

Every ``boq.position.updated`` event re-indexes the position through
``app.core.vector_index.index_one``. That used to clip the text on the event
loop, which asks for the embedder and so waits on the model-load lock for as
long as another thread holds it (a 3 s hold measured as a 2.98 s loop freeze),
and then ran the synchronous LanceDB delete and add on the loop too. All of it
was wasted on a price edit: neither the embedded text nor the stored payload
carries a price.

These tests use the real BOQ position adapter and a fake in-memory store. They
pin two things. First, the embedder, the store lookup, the write and the delete
all run in worker threads, checked by thread identity rather than timing, and
with an embedder that only returns once the loop itself releases it. Second, a
price edit embeds and writes nothing, while a change to anything the store
holds (text or payload) still indexes, and so does a store that cannot answer.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any

import pytest

from app.core import vector as vector_mod
from app.core import vector_index as vector_index_mod
from app.core.vector_index import delete_one, index_one
from app.modules.boq.models import Position
from app.modules.boq.vector_adapter import boq_position_adapter

PROJECT_ID = str(uuid.uuid4())


def _position() -> Position:
    """A transient position with the fields the adapter reads and a price."""
    return Position(
        id=uuid.uuid4(),
        boq_id=uuid.uuid4(),
        ordinal="01.02.003",
        description="Reinforced concrete wall C30/37, 24 cm",
        unit="m3",
        quantity="10",
        unit_rate="185.00",
        total="1850.00",
        classification={"din276": "330"},
        validation_status="pending",
        source="manual",
        metadata_={},
    )


class _FakeStore:
    """In-memory stand-in for the vector store, recording which threads touch it."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict[str, Any]] = {}
        self.encodes = 0
        self.writes = 0
        self.deletes = 0
        self.threads: list[str] = []
        self.lookup_error: Exception | None = None

    def get(self, collection: str, row_id: str) -> dict[str, Any] | None:
        self.threads.append(f"lookup:{threading.get_ident()}")
        if self.lookup_error is not None:
            raise self.lookup_error
        record = self.records.get((collection, row_id))
        return dict(record) if record else None

    def put(self, collection: str, items: list[dict[str, Any]]) -> int:
        self.threads.append(f"write:{threading.get_ident()}")
        self.writes += 1
        for item in items:
            self.records[(collection, item["id"])] = {k: v for k, v in item.items() if k != "vector"}
        return len(items)

    def delete(self, collection: str, ids: list[str]) -> int:
        self.threads.append(f"delete:{threading.get_ident()}")
        self.deletes += 1
        for row_id in ids:
            self.records.pop((collection, row_id), None)
        return len(ids)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    """Swap the store and the encoder for fakes, and keep the real model out of it."""
    fake = _FakeStore()

    async def fake_encode(texts: list[str]) -> list[list[float]]:
        fake.encodes += 1
        return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(vector_index_mod, "vector_get_collection_record", fake.get)
    monkeypatch.setattr(vector_index_mod, "vector_index_collection", fake.put)
    monkeypatch.setattr(vector_index_mod, "vector_delete_collection", fake.delete)
    monkeypatch.setattr(vector_index_mod, "encode_texts_async", fake_encode)
    # No tokenizer: ``_safe_text`` takes its character-cap path.
    monkeypatch.setattr(vector_mod, "get_embedder", lambda: None)
    return fake


async def test_a_price_edit_embeds_and_writes_nothing(store: _FakeStore) -> None:
    position = _position()
    assert await index_one(boq_position_adapter, position, project_id=PROJECT_ID) is True
    assert (store.encodes, store.writes) == (1, 1)

    position.unit_rate = "199.90"
    position.quantity = "12.5"
    position.total = "2498.75"
    position.metadata_ = {"resources": [{"code": "C30", "rate": "120.00"}]}
    assert await index_one(boq_position_adapter, position, project_id=PROJECT_ID) is True
    assert (store.encodes, store.writes) == (1, 1), (
        "a price edit re-embedded or re-wrote a position whose text and payload did not change"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("description", "Reinforced concrete wall C35/45, 30 cm"),  # embedded text
        ("unit", "m2"),  # embedded text
        ("classification", {"din276": "331"}),  # embedded text and payload
        ("validation_status", "errors"),  # payload only
        ("source", "gaeb_import"),  # payload only
    ],
)
async def test_a_change_the_store_holds_is_indexed(store: _FakeStore, field: str, value: object) -> None:
    position = _position()
    await index_one(boq_position_adapter, position, project_id=PROJECT_ID)
    setattr(position, field, value)
    assert await index_one(boq_position_adapter, position, project_id=PROJECT_ID) is True
    assert (store.encodes, store.writes) == (2, 2)


async def test_a_move_to_another_project_is_indexed(store: _FakeStore) -> None:
    position = _position()
    await index_one(boq_position_adapter, position, project_id=PROJECT_ID)
    await index_one(boq_position_adapter, position, project_id=str(uuid.uuid4()))
    assert store.writes == 2


async def test_a_store_that_cannot_answer_is_indexed_anyway(store: _FakeStore) -> None:
    position = _position()
    await index_one(boq_position_adapter, position, project_id=PROJECT_ID)
    store.lookup_error = RuntimeError("lance table is locked")
    assert await index_one(boq_position_adapter, position, project_id=PROJECT_ID) is True
    assert store.writes == 2


async def test_the_embedder_and_the_store_are_reached_off_the_loop(
    store: _FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The embedder returns only when the loop releases it, so it must not run on the loop.

    Were ``get_embedder`` called on the event loop, the loop could not get to
    ``release.set()`` and the embedder would give up after its timeout, which
    the assertion on ``released_by_loop`` catches.
    """
    release = threading.Event()
    seen: dict[str, Any] = {}

    def embedder_busy_loading() -> None:
        """Stand-in for ``get_embedder`` while another thread holds the model-load lock."""
        seen["embedder_thread"] = threading.get_ident()
        seen["released_by_loop"] = release.wait(timeout=20)

    monkeypatch.setattr(vector_mod, "get_embedder", embedder_busy_loading)
    loop_thread = threading.get_ident()

    task = asyncio.create_task(index_one(boq_position_adapter, _position(), project_id=PROJECT_ID))
    await asyncio.sleep(0)
    release.set()
    assert await task is True

    assert seen["released_by_loop"] is True, "the event loop was blocked while the embedder waited"
    assert seen["embedder_thread"] != loop_thread
    touched = {entry.split(":")[0] for entry in store.threads}
    assert touched == {"lookup", "write"}
    assert all(int(entry.split(":")[1]) != loop_thread for entry in store.threads), store.threads


async def test_a_delete_is_reached_off_the_loop(store: _FakeStore) -> None:
    loop_thread = threading.get_ident()
    assert await delete_one(boq_position_adapter, str(uuid.uuid4())) is True
    assert store.deletes == 1
    assert all(int(entry.split(":")[1]) != loop_thread for entry in store.threads), store.threads
