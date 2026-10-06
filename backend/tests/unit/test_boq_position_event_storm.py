# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A bill written row by row must not open one database session per row.

Every importer that keeps the per-row loop (GAEB, Excel, the smart import)
calls ``add_position`` once per row inside one request, and each call defers a
``boq.position.created`` publish to the commit. The one commit then fires every
publish at once, each as its own task, and each task used to open its own
session in the vector-index subscriber and again in the activity-log
subscriber. A 1000-row bill opened about 1000 sessions at the same moment,
which a pool of 34 cannot serve and a pool-less engine turns into 1000 server
connections.

These tests drive the real subscribers on a fresh bus (the test shim lives on
the application singleton only, so ``publish_detached`` runs as in production)
with counting session factories in place of the database, and pin that the BOQ
subscribers coalesce the burst: a bounded number of sessions open at any
moment, every row still reaches the index and the trail, and a delete queued
behind a create wins.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import uuid
from collections import Counter
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.events import Event, EventBus

N_EVENTS = 1000


class _Result:
    """Answers both reads the index worker makes: the positions and their bills."""

    def __init__(self, meter: _Meter) -> None:
        self._meter = meter

    def scalars(self) -> list[Any]:
        return list(self._meter.rows.values())

    def all(self) -> list[tuple[uuid.UUID, uuid.UUID]]:
        return list(self._meter.boqs.items())

    def scalar_one_or_none(self) -> None:
        return None

    def scalar(self) -> None:
        return None


class _Session:
    def __init__(self, meter: _Meter, label: str) -> None:
        self._meter = meter
        self._label = label
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, *_a: Any, **_k: Any) -> _Result:
        await asyncio.sleep(0)
        return _Result(self._meter)

    async def commit(self) -> None:
        await asyncio.sleep(0)
        effect = self._meter.commit_effects.pop(0) if self._meter.commit_effects else None
        if effect is not None:
            raise effect
        self._meter.committed[self._label].extend(self.added)

    async def rollback(self) -> None:
        await asyncio.sleep(0)

    def expunge_all(self) -> None:
        return None


class _Ctx:
    def __init__(self, meter: _Meter, label: str) -> None:
        self._meter = meter
        self._label = label

    async def __aenter__(self) -> _Session:
        meter = self._meter
        meter.open[self._label] += 1
        meter.opened[self._label] += 1
        meter.peak[self._label] = max(meter.peak[self._label], meter.open[self._label])
        meter.total_open += 1
        meter.total_peak = max(meter.total_peak, meter.total_open)
        # A real checkout waits on the network; give every other task the chance
        # to open its own session meanwhile, which is what makes the storm.
        await asyncio.sleep(0)
        return _Session(meter, self._label)

    async def __aexit__(self, *_exc: Any) -> bool:
        await asyncio.sleep(0)
        self._meter.open[self._label] -= 1
        self._meter.total_open -= 1
        return False


class _Meter:
    """Counting stand-in for ``async_session_factory``, one label per subscriber module."""

    def __init__(self) -> None:
        self.open: Counter[str] = Counter()
        self.peak: Counter[str] = Counter()
        self.opened: Counter[str] = Counter()
        self.total_open = 0
        self.total_peak = 0
        self.rows: dict[uuid.UUID, Any] = {}
        self.boqs: dict[uuid.UUID, uuid.UUID] = {}
        self.committed: dict[str, list[Any]] = {}
        self.commit_effects: list[BaseException | None] = []

    def factory(self, label: str) -> Any:
        self.committed.setdefault(label, [])

        def _make() -> _Ctx:
            return _Ctx(self, label)

        return _make


class _Index:
    """Records what reaches the vector store through each seam."""

    def __init__(self) -> None:
        self.many_calls: list[tuple[list[uuid.UUID], str | None]] = []
        self.one_calls: list[uuid.UUID] = []
        self.deleted: list[str] = []
        self.many_error: Exception | None = None

    async def many(self, _adapter: object, rows: list[Any], **kwargs: Any) -> int:
        await asyncio.sleep(0)
        if self.many_error is not None:
            raise self.many_error
        self.many_calls.append(([row.id for row in rows], kwargs.get("project_id")))
        return len(rows)

    async def one(self, _adapter: object, row: Any, **_kwargs: Any) -> bool:
        await asyncio.sleep(0)
        self.one_calls.append(row.id)
        return True

    async def delete(self, _adapter: object, row_id: str) -> bool:
        await asyncio.sleep(0)
        self.deleted.append(str(row_id))
        return True

    @property
    def indexed(self) -> list[uuid.UUID]:
        return [pid for ids, _ in self.many_calls for pid in ids] + list(self.one_calls)


def _boq_events() -> Any:
    return importlib.import_module("app.modules.boq.events")


async def _drain(mod: Any) -> None:
    drain = getattr(mod, "drain_pending", None)
    if drain is not None:
        await drain()


@pytest.fixture
def meter() -> _Meter:
    return _Meter()


@pytest.fixture
def index(monkeypatch: pytest.MonkeyPatch, meter: _Meter) -> _Index:
    mod = _boq_events()
    seam = _Index()
    monkeypatch.setattr(mod, "async_session_factory", meter.factory("boq"))
    monkeypatch.setattr(mod, "vector_index_many", seam.many)
    monkeypatch.setattr(mod, "vector_index_one", seam.one)
    monkeypatch.setattr(mod, "vector_delete_one", seam.delete)
    return seam


def _known_rows(meter: _Meter, count: int, *, boq_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    """Rows the fake database holds, all in one bill of one project unless told otherwise."""
    boq_id = boq_id or uuid.uuid4()
    meter.boqs.setdefault(boq_id, uuid.uuid4())
    ids = [uuid.uuid4() for _ in range(count)]
    for pid in ids:
        meter.rows[pid] = SimpleNamespace(id=pid, boq_id=boq_id)
    return ids


def _created(pid: uuid.UUID, boq_id: uuid.UUID, n: int) -> dict[str, str]:
    """The payload ``add_position`` publishes."""
    return {"position_id": str(pid), "boq_id": str(boq_id), "ordinal": f"01.{n:04d}"}


async def test_a_thousand_creates_after_one_commit_open_a_bounded_number_of_sessions(
    monkeypatch: pytest.MonkeyPatch, meter: _Meter, index: _Index
) -> None:
    """The per-row import burst, against the subscribers it reaches in production.

    The webhook and timeline wildcards are on the bus too and are metered under
    their own labels, so the printed table shows every subscriber's share; the
    bound asserted here is on the BOQ subscribers', which this module owns.
    """
    from app.core import event_handlers
    from app.modules.integrations.service import WebhookService
    from app.modules.timeline import events as timeline_events

    mod = _boq_events()

    async def _no_webhooks(self: object, *_a: Any, **_k: Any) -> int:
        await asyncio.sleep(0)
        return 0

    async def _no_timeline(*_a: Any, **_k: Any) -> None:
        await asyncio.sleep(0)

    monkeypatch.setattr("app.database.async_session_factory", meter.factory("webhooks"))
    monkeypatch.setattr(WebhookService, "dispatch_event", _no_webhooks)
    monkeypatch.setattr(timeline_events, "async_session_factory", meter.factory("timeline"))
    monkeypatch.setattr(timeline_events, "log_activity", _no_timeline)

    bus = EventBus()
    bus.subscribe("boq.position.created", mod._on_position_created)
    bus.subscribe("*", event_handlers._dispatch_to_webhooks)
    bus.subscribe("*", timeline_events._record_event)
    bus.subscribe("*", mod._log_boq_activity)

    boq_id = uuid.uuid4()
    ids = _known_rows(meter, N_EVENTS, boq_id=boq_id)
    tasks = [
        bus.publish_detached("boq.position.created", _created(pid, boq_id, n), source_module="oe_boq")
        for n, pid in enumerate(ids, start=1)
    ]
    await asyncio.gather(*tasks)
    await _drain(mod)

    print(
        f"\npeak concurrent sessions for {N_EVENTS} creates: "
        f"{dict(meter.peak)} (all subscribers together {meter.total_peak}); opened {dict(meter.opened)}"
    )
    assert meter.peak["boq"] <= 2, f"BOQ subscribers held {meter.peak['boq']} sessions at once"
    assert meter.opened["boq"] < N_EVENTS // 10, meter.opened["boq"]
    assert meter.peak["webhooks"] <= 4
    assert meter.peak["timeline"] == 1
    assert meter.opened["webhooks"] == N_EVENTS  # bounded concurrency, not webhook batching
    assert meter.opened["timeline"] < N_EVENTS
    assert sorted(index.indexed) == sorted(ids), "every created row reaches the index exactly once"
    assert index.deleted == []

    logged = meter.committed["boq"]
    assert len(logged) == N_EVENTS, "every create reaches the activity trail"
    by_target = {row.target_id: row for row in logged}
    assert by_target[ids[0]].description == "Added position 01.0001"
    assert by_target[ids[-1]].description == f"Added position 01.{N_EVENTS:04d}"
    assert all(row.boq_id == boq_id and row.action == "position.created" for row in logged)


async def test_a_delete_queued_behind_a_create_wins(meter: _Meter, index: _Index) -> None:
    mod = _boq_events()
    boq_id = uuid.uuid4()
    gone, kept = _known_rows(meter, 2, boq_id=boq_id)
    await asyncio.gather(
        mod._on_position_created(Event(name="boq.position.created", data=_created(gone, boq_id, 1))),
        mod._on_position_created(Event(name="boq.position.created", data=_created(kept, boq_id, 2))),
        mod._on_position_deleted(Event(name="boq.position.deleted", data={"position_id": str(gone)})),
    )
    await _drain(mod)

    assert index.indexed == [kept]
    assert index.deleted == [str(gone)]


async def test_a_row_gone_before_the_worker_reads_it_is_removed(meter: _Meter, index: _Index) -> None:
    mod = _boq_events()
    boq_id = uuid.uuid4()
    (present,) = _known_rows(meter, 1, boq_id=boq_id)
    missing = uuid.uuid4()
    await asyncio.gather(
        mod._on_position_created(Event(name="boq.position.created", data=_created(present, boq_id, 1))),
        mod._on_position_created(Event(name="boq.position.created", data=_created(missing, boq_id, 2))),
    )
    await _drain(mod)

    assert index.indexed == [present]
    assert index.deleted == [str(missing)]


async def test_creates_are_indexed_under_their_own_project(meter: _Meter, index: _Index) -> None:
    """``project_id_of`` would lazy-load the bill, so the worker names the project itself."""
    mod = _boq_events()
    first_boq, second_boq = uuid.uuid4(), uuid.uuid4()
    first = _known_rows(meter, 3, boq_id=first_boq)
    second = _known_rows(meter, 2, boq_id=second_boq)
    await asyncio.gather(
        *(
            mod._on_position_created(Event(name="boq.position.created", data=_created(pid, boq, n)))
            for n, (pid, boq) in enumerate([(p, first_boq) for p in first] + [(p, second_boq) for p in second])
        )
    )
    await _drain(mod)

    by_project = {project: sorted(ids) for ids, project in index.many_calls}
    assert by_project == {
        str(meter.boqs[first_boq]): sorted(first),
        str(meter.boqs[second_boq]): sorted(second),
    }


async def test_a_burst_is_read_and_embedded_in_chunks(meter: _Meter, index: _Index) -> None:
    mod = _boq_events()
    boq_id = uuid.uuid4()
    ids = _known_rows(meter, N_EVENTS, boq_id=boq_id)
    await asyncio.gather(
        *(
            mod._on_position_created(Event(name="boq.position.created", data=_created(pid, boq_id, n)))
            for n, pid in enumerate(ids)
        )
    )
    await _drain(mod)

    sizes = [len(batch) for batch, _ in index.many_calls]
    assert sum(sizes) == N_EVENTS
    assert max(sizes) <= 200, sizes
    assert meter.opened["boq"] == len(sizes), "one session per chunk read"


async def test_an_edit_keeps_the_single_row_path_that_skips_an_unchanged_record(meter: _Meter, index: _Index) -> None:
    """``index_one`` is the call that skips a price edit; a burst of edits still shares one session."""
    mod = _boq_events()
    boq_id = uuid.uuid4()
    ids = _known_rows(meter, 5, boq_id=boq_id)
    await asyncio.gather(
        *(mod._on_position_updated(Event(name="boq.position.updated", data={"position_id": str(pid)})) for pid in ids)
    )
    await _drain(mod)

    assert sorted(index.one_calls) == sorted(ids)
    assert index.many_calls == []
    assert meter.opened["boq"] == 1


async def test_a_bulk_create_goes_through_the_same_batches(meter: _Meter, index: _Index) -> None:
    """One path: a row named by a per-row event and by a bulk event is indexed once."""
    mod = _boq_events()
    boq_id = uuid.uuid4()
    ids = _known_rows(meter, 450, boq_id=boq_id)
    await asyncio.gather(
        mod._on_position_created(Event(name="boq.position.created", data=_created(ids[0], boq_id, 1))),
        mod._on_positions_bulk_created(
            Event(
                name="boq.positions.bulk_created",
                data={"boq_id": str(boq_id), "count": len(ids), "position_ids": [str(p) for p in ids]},
            )
        ),
    )
    await _drain(mod)

    assert sorted(index.indexed) == sorted(ids)
    assert max(len(batch) for batch, _ in index.many_calls) <= 200
    assert meter.peak["boq"] <= 1


async def test_a_failing_index_is_logged_once_and_the_worker_lives_on(
    caplog: pytest.LogCaptureFixture, meter: _Meter, index: _Index
) -> None:
    from app.core import cache as cache_mod

    mod = _boq_events()
    mod._vector_warn = cache_mod._RateLimitedLogger(window_seconds=60.0)
    boq_id = uuid.uuid4()
    ids = _known_rows(meter, 300, boq_id=boq_id)
    index.many_error = ConnectionError("embeddings-down")
    with caplog.at_level(logging.WARNING, logger="app.core.cache"):
        await asyncio.gather(
            *(
                mod._on_position_created(Event(name="boq.position.created", data=_created(pid, boq_id, n)))
                for n, pid in enumerate(ids)
            )
        )
        await _drain(mod)
    warned = [rec for rec in caplog.records if "boq.vector.index" in rec.getMessage()]
    assert len(warned) == 1, [rec.getMessage() for rec in warned]

    index.many_error = None
    (later,) = _known_rows(meter, 1, boq_id=boq_id)
    await mod._on_position_created(Event(name="boq.position.created", data=_created(later, boq_id, 999)))
    await _drain(mod)
    assert index.indexed == [later]


async def test_a_bad_row_in_an_activity_batch_costs_its_scope_not_the_batch(
    caplog: pytest.LogCaptureFixture, meter: _Meter, index: _Index
) -> None:
    """The batch is rejected as a whole, so its rows are written again one by one."""
    mod = _boq_events()
    boq_id = uuid.uuid4()
    events = [
        Event(name="boq.position.updated", data={"boq_id": str(boq_id), "position_id": str(uuid.uuid4())})
        for _ in range(3)
    ]
    foreign_key = IntegrityError("INSERT INTO oe_boq_activity_log ...", {}, Exception("foreign key violation"))
    # The batch fails, then the first row alone fails and goes in unscoped.
    meter.commit_effects = [foreign_key, foreign_key]
    with caplog.at_level(logging.WARNING):
        await asyncio.gather(*(mod._log_boq_activity(evt) for evt in events))
        await _drain(mod)

    logged = meter.committed["boq"]
    assert len(logged) == 3, "no entry is lost"
    assert sum(1 for row in logged if row.boq_id is None) == 1
    assert sum(1 for row in logged if row.boq_id == boq_id) == 2
    assert any("no longer exists" in rec.getMessage() for rec in caplog.records)
