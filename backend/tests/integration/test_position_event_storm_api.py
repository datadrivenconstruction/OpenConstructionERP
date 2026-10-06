# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The per-row write path and the bulk route, end to end, against the booted app.

GAEB (``_persist_imported_boq``), Excel (``import_boq_excel``) and the smart
import all create the rows of a bill with ``BOQService.add_position`` inside one
request session, and each call defers its ``boq.position.created`` publish to
that session's commit. The first test does exactly that and meters, per
subscriber module, how many sessions the subscribers hold at once once the
commit fires every publish together. Every ``async_session_factory`` the app
imported is swapped for a counting fake after the rows are written, so the
burst never reaches the shared server, and the engine's own checkouts are
counted as a cross-check that nothing went round the factories.

The second pins that the bulk positions route (what the takeoff page posts)
reaches the search index through the same batches.

Run:
    cd backend
    OE_TEST_DB=pg python -m pytest tests/integration/test_position_event_storm_api.py -v -s
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from types import ModuleType
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401

N_ROWS = 250


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    fastapi_app = create_app()

    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield fastapi_app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="module")
async def auth_headers(http_client) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"event-storm-{uuid.uuid4().hex[:8]}@storm.io"
    password = f"EventStorm{uuid.uuid4().hex[:6]}9"
    reg = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Event Storm"},
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.status_code} {reg.text}"
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True, role="admin"))
        await s.commit()
    login = await http_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, f"login failed: {login.text}"
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _new_boq(http_client: AsyncClient, auth_headers: dict[str, str]) -> str:
    project = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"Storm {uuid.uuid4().hex[:6]}", "description": "event storm", "region": "DE", "currency": "EUR"},
        headers=auth_headers,
    )
    assert project.status_code == 201, project.text
    boq = await http_client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project.json()["id"], "name": "Storm bill", "description": "storm"},
        headers=auth_headers,
    )
    assert boq.status_code == 201, boq.text
    return boq.json()["id"]


class _Scalars(list):
    def all(self) -> list[Any]:
        return list(self)

    def first(self) -> Any:
        return self[0] if self else None


class _Result:
    """An empty answer, except for the rows and bills handed to the BOQ worker's reads."""

    def __init__(self, rows: list[Any] = (), pairs: list[tuple[Any, Any]] = ()) -> None:
        self._rows = list(rows)
        self._pairs = list(pairs)

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one_or_none(self) -> None:
        return None

    def scalar(self) -> None:
        return None

    def all(self) -> list[Any]:
        return list(self._pairs)

    def first(self) -> None:
        return None


class _FakeSession:
    def __init__(self, result: _Result) -> None:
        self._result = result

    def add(self, _obj: Any) -> None:
        return None

    def add_all(self, _objs: Any) -> None:
        return None

    async def execute(self, *_a: Any, **_k: Any) -> _Result:
        await asyncio.sleep(0)
        return self._result

    async def commit(self) -> None:
        await asyncio.sleep(0)

    async def rollback(self) -> None:
        await asyncio.sleep(0)

    async def flush(self) -> None:
        await asyncio.sleep(0)

    def expunge_all(self) -> None:
        return None

    @asynccontextmanager
    async def begin_nested(self):
        # AsyncSession.begin_nested returns an async context manager, not a
        # bare coroutine. The generic __getattr__ stub leaked an unawaited
        # coroutine when the real timeline audit helper used a savepoint.
        yield self

    def __getattr__(self, _name: str) -> Any:
        async def _noop(*_a: Any, **_k: Any) -> None:
            await asyncio.sleep(0)

        return _noop


class _Meter:
    def __init__(self) -> None:
        self.open: Counter[str] = Counter()
        self.peak: Counter[str] = Counter()
        self.opened: Counter[str] = Counter()
        self.total_open = 0

    def factory(self, label: str, result: _Result | None = None) -> Any:
        meter = self
        answer = result if result is not None else _Result()

        class _Ctx:
            async def __aenter__(self) -> _FakeSession:
                meter.open[label] += 1
                meter.opened[label] += 1
                meter.peak[label] = max(meter.peak[label], meter.open[label])
                meter.total_open += 1
                await asyncio.sleep(0)
                return _FakeSession(answer)

            async def __aexit__(self, *_exc: Any) -> bool:
                await asyncio.sleep(0)
                meter.open[label] -= 1
                meter.total_open -= 1
                return False

        return _Ctx


async def _settle(meter: _Meter, *, seconds: float = 60.0) -> None:
    """Wait until no subscriber session is open and none has opened for a while."""
    from app.modules.boq import events as boq_events

    quiet = 0
    last = None
    for _ in range(int(seconds / 0.05)):
        await asyncio.sleep(0.05)
        drain = getattr(boq_events, "drain_pending", None)
        if drain is not None:
            await drain()
        snapshot = sum(meter.opened.values())
        quiet = quiet + 1 if (meter.total_open == 0 and snapshot == last) else 0
        last = snapshot
        if quiet >= 20:
            return


@pytest.mark.asyncio
async def test_a_bill_written_row_by_row_holds_few_sessions_after_its_commit(
    http_client, auth_headers, monkeypatch
) -> None:
    from sqlalchemy import event as sa_event
    from sqlalchemy import select

    from app.core.events import event_bus
    from app.database import async_session_factory, engine
    from app.modules.boq import events as boq_events
    from app.modules.boq.models import BOQ, Position
    from app.modules.boq.schemas import PositionCreate
    from app.modules.boq.service import BOQService

    boq_id = uuid.UUID(await _new_boq(http_client, auth_headers))
    indexed: list[str] = []

    async def _many(_adapter: object, rows: list, **_kwargs: object) -> int:
        indexed.extend(str(row.id) for row in rows)
        return len(rows)

    async def _one(_adapter: object, row: object, **_kwargs: object) -> bool:
        indexed.append(str(row.id))  # type: ignore[attr-defined]
        return True

    async def _delete(_adapter: object, _row_id: str) -> bool:
        return True

    created: list[str] = []
    real_factory = async_session_factory
    async with real_factory() as session:
        service = BOQService(session)
        for n in range(1, N_ROWS + 1):
            row = await service.add_position(
                PositionCreate(
                    boq_id=boq_id,
                    ordinal=f"01.{n:04d}",
                    description=f"Storm row {n}",
                    unit="m3",
                    quantity=1,
                    unit_rate=10,
                )
            )
            created.append(str(row.id))

        # The rows are written; from here on every subscriber session is a fake
        # one, metered under the module that opened it. The BOQ worker's fake
        # answers its two reads with the rows just written and their bill's
        # project, read now through the real session; the vector seams are
        # recorders.
        stored = list((await session.execute(select(Position).where(Position.boq_id == boq_id))).scalars())
        project_id = (await session.execute(select(BOQ.project_id).where(BOQ.id == boq_id))).scalar_one()
        boq_answer = _Result(stored, [(boq_id, project_id)])
        meter = _Meter()
        swapped: list[str] = []
        for name, module in list(sys.modules.items()):
            if not isinstance(module, ModuleType) or not (name == "app" or name.startswith("app.")):
                continue
            if getattr(module, "async_session_factory", None) is real_factory:
                answer = boq_answer if module is boq_events else None
                monkeypatch.setattr(module, "async_session_factory", meter.factory(name, answer))
                swapped.append(name)
        monkeypatch.setattr(boq_events, "vector_index_many", _many, raising=False)
        monkeypatch.setattr(boq_events, "vector_index_one", _one)
        monkeypatch.setattr(boq_events, "vector_delete_one", _delete)

        checked_out = {"now": 0, "peak": 0}

        def _checkout(*_a: Any) -> None:
            checked_out["now"] += 1
            checked_out["peak"] = max(checked_out["peak"], checked_out["now"])

        def _checkin(*_a: Any) -> None:
            checked_out["now"] -= 1

        pool = engine.sync_engine.pool
        sa_event.listen(pool, "checkout", _checkout)
        sa_event.listen(pool, "checkin", _checkin)
        try:
            await session.commit()
            await _settle(meter)
        finally:
            sa_event.remove(pool, "checkout", _checkout)
            sa_event.remove(pool, "checkin", _checkin)

    print(
        f"\nsubscribers of boq.position.created: {event_bus.list_handlers('boq.position.created')}"
        f"\nwildcard subscribers: {[h.__qualname__ for h in event_bus._wildcard_handlers]}"
        f"\nfactories swapped in {len(swapped)} modules"
        f"\npeak concurrent subscriber sessions after one commit of {N_ROWS} rows: {dict(meter.peak)}"
        f"\nsessions opened: {dict(meter.opened)}"
        f"\nengine checkouts outside the factories, peak: {checked_out['peak']}"
    )
    assert meter.peak["app.modules.boq.events"] <= 2, dict(meter.peak)
    assert sorted(set(indexed) & set(created)) == sorted(created)


@pytest.mark.asyncio
async def test_the_bulk_route_reaches_the_search_index(http_client, auth_headers, monkeypatch) -> None:
    """The rows the takeoff page posts in one batch are indexed, through the batched worker."""
    from app.modules.boq import events as boq_events

    indexed: list[str] = []

    async def _many(_adapter: object, rows: list, **_kwargs: object) -> int:
        indexed.extend(str(row.id) for row in rows)
        return len(rows)

    monkeypatch.setattr(boq_events, "vector_index_many", _many, raising=False)

    boq = await _new_boq(http_client, auth_headers)
    items = [
        {"description": f"Takeoff wall {n}", "quantity": 2 + n, "unit": "m2", "unit_rate": 30, "source": "takeoff"}
        for n in range(12)
    ]
    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq}/positions/bulk/", json={"items": items}, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text[:300]
    ids = sorted(p["id"] for p in resp.json())
    assert len(ids) == 12
    for _ in range(100):
        drain = getattr(boq_events, "drain_pending", None)
        if drain is not None:
            await drain()
        if set(ids) <= set(indexed):
            break
        await asyncio.sleep(0.1)
    assert sorted(i for i in indexed if i in set(ids)) == ids
