# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v2.8.2 — per-project CWICR catalogue binding.

Coverage:

* ``_resolve_catalog_status`` returns the right envelope state for each
  combination of (binding present?, rows present?, vectors present?).
* The match endpoint short-circuits with a structured ``status`` field
  whenever the gate is closed.
* ``vector_count_with_payload_substring`` whitelist rejects junk inputs
  (SQL-injection-shaped strings, lowercase, empty) without hitting
  LanceDB at all.
* ``GET /v1/costs/loaded-databases/`` reports SQL row count + vectorised
  count + the ready boolean per region.
"""

from __future__ import annotations

import tempfile
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


def _register_models() -> None:
    """Pull every ORM model the catalogue gate touches into Base.metadata."""
    import app.core.audit  # noqa: F401
    import app.modules.costs.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def engine_factory():
    tmp_db = Path(tempfile.mkdtemp()) / "match_catalog_binding.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_models()

    from app.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    yield engine, factory, tmp_db

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


async def _add_cost_items(factory, region: str, count: int) -> None:
    """Seed N rows in ``oe_costs_item`` tagged with ``region``."""
    from app.modules.costs.models import CostItem

    async with factory() as session:
        for i in range(count):
            session.add(
                CostItem(
                    code=f"TEST-{region}-{i:03d}",
                    description=f"Sample row {i} for {region}",
                    unit="m3",
                    rate="10.00",
                    currency="EUR",
                    source="cwicr",
                    region=region,
                    is_active=True,
                )
            )
        await session.commit()


_current_user_payload: dict[str, str] = {}


@pytest_asyncio.fixture
async def client_app(engine_factory) -> AsyncGenerator[FastAPI, None]:
    """FastAPI client with the costs router mounted + DB overridden."""
    _engine, factory, _tmp = engine_factory

    from app.dependencies import (
        get_current_user_id,
        get_current_user_payload,
        get_session,
    )
    from app.modules.costs.router import router as costs_router

    app = FastAPI()
    app.include_router(costs_router, prefix="/api/v1/costs")

    async def _session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    async def _payload() -> dict[str, str]:
        return dict(_current_user_payload)

    async def _user_id() -> str:
        return _current_user_payload.get("sub", "")

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_payload] = _payload
    app.dependency_overrides[get_current_user_id] = _user_id

    yield app


@pytest_asyncio.fixture
async def http_client(client_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=client_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _set_user(role: str = "admin") -> None:
    _current_user_payload.clear()
    _current_user_payload["sub"] = str(uuid.uuid4())
    _current_user_payload["role"] = role


# ── _resolve_catalog_status ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_catalog_no_rows_returns_no_catalogs_loaded(
    engine_factory,
) -> None:
    """Empty DB + no binding → ``no_catalogs_loaded``."""
    _engine, factory, _tmp = engine_factory

    from app.core.match_service.ranker import _resolve_catalog_status

    async with factory() as session:
        status, count, vec = await _resolve_catalog_status(session, None)

    assert status == "no_catalogs_loaded"
    assert count == 0
    assert vec == 0


@pytest.mark.asyncio
async def test_no_catalog_with_rows_returns_no_catalog_selected(
    engine_factory,
) -> None:
    """Catalogues loaded but no binding → ``no_catalog_selected``."""
    _engine, factory, _tmp = engine_factory
    await _add_cost_items(factory, "RU_STPETERSBURG", 3)

    from app.core.match_service.ranker import _resolve_catalog_status

    async with factory() as session:
        status, _count, _vec = await _resolve_catalog_status(session, None)

    assert status == "no_catalog_selected"


@pytest.mark.asyncio
async def test_picked_unknown_catalog_with_others_loaded_falls_to_no_catalog_selected(
    engine_factory,
) -> None:
    """v2.8.2 fix: if user picked a stale id but other catalogues exist,
    don't claim "no catalogues loaded" — degrade to ``no_catalog_selected``
    so the picker can recover the user with one click."""
    _engine, factory, _tmp = engine_factory
    await _add_cost_items(factory, "RU_STPETERSBURG", 3)

    from app.core.match_service.ranker import _resolve_catalog_status

    async with factory() as session:
        status, count, vec = await _resolve_catalog_status(session, "USA_USD")

    assert status == "no_catalog_selected"
    assert count == 0
    assert vec == 0


@pytest.mark.asyncio
async def test_picked_unknown_catalog_with_no_others_returns_no_catalogs_loaded(
    engine_factory,
) -> None:
    """Pure-empty DB + binding to a non-loaded id → ``no_catalogs_loaded``."""
    _engine, factory, _tmp = engine_factory

    from app.core.match_service.ranker import _resolve_catalog_status

    async with factory() as session:
        status, _count, _vec = await _resolve_catalog_status(session, "USA_USD")

    assert status == "no_catalogs_loaded"


@pytest.mark.asyncio
async def test_picked_loaded_catalog_no_vectors_returns_catalog_not_vectorized(
    engine_factory, monkeypatch,
) -> None:
    """SQL rows present but LanceDB empty for this region → not_vectorized."""
    _engine, factory, _tmp = engine_factory
    await _add_cost_items(factory, "DE_BERLIN", 5)

    monkeypatch.setattr(
        "app.core.vector.vector_count_with_payload_substring",
        lambda _coll, _sub: 0,
    )

    from app.core.match_service.ranker import _resolve_catalog_status

    async with factory() as session:
        status, count, vec = await _resolve_catalog_status(session, "DE_BERLIN")

    assert status == "catalog_not_vectorized"
    assert count == 5
    assert vec == 0


@pytest.mark.asyncio
async def test_picked_loaded_catalog_with_vectors_returns_ok(
    engine_factory, monkeypatch,
) -> None:
    """Happy path: SQL rows + vectors → ``ok``."""
    _engine, factory, _tmp = engine_factory
    await _add_cost_items(factory, "DE_BERLIN", 5)

    monkeypatch.setattr(
        "app.core.vector.vector_count_with_payload_substring",
        lambda _coll, _sub: 12,
    )

    from app.core.match_service.ranker import _resolve_catalog_status

    async with factory() as session:
        status, count, vec = await _resolve_catalog_status(session, "DE_BERLIN")

    assert status == "ok"
    assert count == 5
    assert vec == 12


# ── vector_count_with_payload_substring whitelist ────────────────────────


def test_vector_count_rejects_empty_substring() -> None:
    from app.core.vector import vector_count_with_payload_substring

    assert vector_count_with_payload_substring("oe_cost_items", "") == 0


def test_vector_count_rejects_sql_injection() -> None:
    """Anything outside ``[A-Z0-9_]{1,32}`` short-circuits to 0."""
    from app.core.vector import vector_count_with_payload_substring

    bad_inputs = [
        "X' OR 1=1 --",
        "ru_stpetersburg",  # lowercase
        "DE BERLIN",  # space
        "DE-BERLIN",  # dash
        "A" * 33,  # too long
        "DE'; DROP TABLE x; --",
    ]
    for bad in bad_inputs:
        assert vector_count_with_payload_substring("oe_cost_items", bad) == 0, bad


def test_vector_count_accepts_valid_cwicr_ids(monkeypatch) -> None:
    """Whitelisted ids are passed through to the backend (which we stub
    to make sure the call actually reaches it)."""
    from app.core import vector as vector_mod

    calls: list[str] = []

    class _StubTbl:
        def count_rows(self, filter: str) -> int:  # noqa: A002
            calls.append(filter)
            return 7

    class _StubDB:
        def table_names(self) -> list[str]:
            return ["oe_cost_items"]

        def open_table(self, _name: str) -> _StubTbl:
            return _StubTbl()

    monkeypatch.setattr(vector_mod, "_backend", lambda: "lancedb")
    monkeypatch.setattr(vector_mod, "_get_lancedb", lambda: _StubDB())

    out = vector_mod.vector_count_with_payload_substring(
        "oe_cost_items", "RU_STPETERSBURG",
    )
    assert out == 7
    assert any("RU_STPETERSBURG" in c for c in calls)


# ── /v1/costs/loaded-databases/ endpoint ─────────────────────────────────


@pytest.mark.asyncio
async def test_loaded_databases_returns_one_entry_per_region(
    http_client: AsyncClient, engine_factory, monkeypatch,
) -> None:
    """Every distinct region with at least one active row gets one entry."""
    _engine, factory, _tmp = engine_factory
    await _add_cost_items(factory, "RU_STPETERSBURG", 3)
    await _add_cost_items(factory, "BG_SOFIA", 2)

    # Stub the vector counter so the endpoint doesn't try to open LanceDB.
    # The router imports this lazily from ``app.core.vector`` inside the
    # handler body (PLC0415-tagged), so we must patch the source module —
    # not a re-exported alias on the router.
    monkeypatch.setattr(
        "app.core.vector.vector_count_with_payload_substring",
        lambda _coll, sub: 10 if sub == "RU_STPETERSBURG" else 0,
    )

    _set_user()
    resp = await http_client.get("/api/v1/costs/loaded-databases/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    by_id = {row["id"]: row for row in body}
    assert set(by_id.keys()) == {"RU_STPETERSBURG", "BG_SOFIA"}

    ru = by_id["RU_STPETERSBURG"]
    assert ru["count"] == 3
    assert ru["vectorized_count"] == 10
    assert ru["ready"] is True

    bg = by_id["BG_SOFIA"]
    assert bg["count"] == 2
    assert bg["vectorized_count"] == 0
    assert bg["ready"] is False


@pytest.mark.asyncio
async def test_loaded_databases_empty_when_no_rows(
    http_client: AsyncClient,
) -> None:
    """No rows in the DB → empty list (not 404 / not 500)."""
    _set_user()
    resp = await http_client.get("/api/v1/costs/loaded-databases/")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_loaded_databases_skips_inactive_rows(
    http_client: AsyncClient, engine_factory, monkeypatch,
) -> None:
    """Soft-deleted rows are ignored — they shouldn't count toward the badge."""
    _engine, factory, _tmp = engine_factory
    from app.modules.costs.models import CostItem

    async with factory() as session:
        session.add(
            CostItem(
                code="INACTIVE-001",
                description="Inactive row",
                unit="m",
                rate="1.00",
                currency="EUR",
                source="cwicr",
                region="UK_GBP",
                is_active=False,
            )
        )
        await session.commit()

    monkeypatch.setattr(
        "app.core.vector.vector_count_with_payload_substring",
        lambda _coll, _sub: 0,
    )
    _set_user()
    resp = await http_client.get("/api/v1/costs/loaded-databases/")
    assert resp.status_code == 200
    assert resp.json() == []
