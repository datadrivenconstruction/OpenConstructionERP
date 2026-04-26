# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""T08 integration tests — Compliance DSL API.

Stands up a minimal FastAPI app with just the compliance router mounted
plus session/auth dependencies overridden to point at a per-test temp
SQLite file (``feedback_test_isolation.md``).
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.dependencies import get_current_user_payload, get_session


def _register_minimal_models() -> None:
    """Pull compliance models into Base.metadata."""
    import app.modules.compliance.models  # noqa: F401


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    tmp_db = Path(tempfile.mkdtemp()) / "compliance_api.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_minimal_models()

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


_current_user_payload: dict[str, str] = {}


@pytest_asyncio.fixture
async def app(temp_engine_and_factory) -> AsyncGenerator[FastAPI, None]:
    _engine, factory, _tmp = temp_engine_and_factory

    from app.modules.compliance.router import router as compliance_router

    app = FastAPI()
    app.include_router(compliance_router, prefix="/api/v1/compliance")

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _override_payload() -> dict[str, str]:
        return dict(_current_user_payload)

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user_payload] = _override_payload

    yield app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def user_a() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def user_b() -> uuid.UUID:
    return uuid.uuid4()


def _set_acting_user(user_id: uuid.UUID, tenant_id: str | None = None) -> None:
    _current_user_payload.clear()
    _current_user_payload["sub"] = str(user_id)
    _current_user_payload["tenant_id"] = tenant_id or str(user_id)


_GOOD_DSL = (
    "rule_id: custom.boq.no_zero_quantities_{suffix}\n"
    "name: BOQ positions must have non-zero quantities\n"
    "severity: error\n"
    "scope: positions\n"
    "expression:\n"
    "  forEach: position\n"
    "  assert: position.quantity > 0\n"
)


def _make_dsl(suffix: str = "alpha") -> str:
    return _GOOD_DSL.format(suffix=suffix)


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_syntax_happy_path(
    client: AsyncClient, user_a: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    resp = await client.post(
        "/api/v1/compliance/dsl/validate-syntax",
        json={"definition_yaml": _make_dsl("v1")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is True
    assert body["rule_id"] == "custom.boq.no_zero_quantities_v1"
    assert body["severity"] == "error"


@pytest.mark.asyncio
async def test_validate_syntax_rejects_bad_doc(
    client: AsyncClient, user_a: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    resp = await client.post(
        "/api/v1/compliance/dsl/validate-syntax",
        json={"definition_yaml": "rule_id: x\nname: X\n"},  # no expression
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is False
    assert body["error"] is not None


@pytest.mark.asyncio
async def test_compile_persists_and_returns_rule(
    client: AsyncClient, user_a: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    resp = await client.post(
        "/api/v1/compliance/dsl/compile",
        json={"definition_yaml": _make_dsl("compile1"), "activate": True},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rule_id"] == "custom.boq.no_zero_quantities_compile1"
    assert body["is_active"] is True
    assert body["owner_user_id"] == str(user_a)
    assert body["severity"] == "error"


@pytest.mark.asyncio
async def test_compile_duplicate_rule_id_returns_409(
    client: AsyncClient, user_a: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    payload = {"definition_yaml": _make_dsl("dup"), "activate": True}
    first = await client.post("/api/v1/compliance/dsl/compile", json=payload)
    assert first.status_code == 201, first.text
    second = await client.post("/api/v1/compliance/dsl/compile", json=payload)
    assert second.status_code == 409, second.text


@pytest.mark.asyncio
async def test_compile_invalid_dsl_returns_422(
    client: AsyncClient, user_a: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    resp = await client.post(
        "/api/v1/compliance/dsl/compile",
        json={"definition_yaml": "rule_id: x\nname: X\n", "activate": True},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_list_rules_returns_only_caller_tenant(
    client: AsyncClient, user_a: uuid.UUID, user_b: uuid.UUID,
) -> None:
    # User A creates one rule.
    _set_acting_user(user_a)
    await client.post(
        "/api/v1/compliance/dsl/compile",
        json={"definition_yaml": _make_dsl("a1")},
    )

    # User B (different tenant_id) creates another.
    _set_acting_user(user_b)
    await client.post(
        "/api/v1/compliance/dsl/compile",
        json={"definition_yaml": _make_dsl("b1")},
    )

    # User A only sees their own.
    _set_acting_user(user_a)
    resp = await client.get("/api/v1/compliance/dsl/rules")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["rule_id"] == "custom.boq.no_zero_quantities_a1"


@pytest.mark.asyncio
async def test_get_rule_returns_404_for_other_tenant(
    client: AsyncClient, user_a: uuid.UUID, user_b: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    create = await client.post(
        "/api/v1/compliance/dsl/compile",
        json={"definition_yaml": _make_dsl("priv")},
    )
    rule_pk = create.json()["id"]

    _set_acting_user(user_b)
    resp = await client.get(f"/api/v1/compliance/dsl/rules/{rule_pk}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_rule_owner_only(
    client: AsyncClient, user_a: uuid.UUID, user_b: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    create = await client.post(
        "/api/v1/compliance/dsl/compile",
        json={"definition_yaml": _make_dsl("del")},
    )
    rule_pk = create.json()["id"]

    # User B has a different tenant — they can't even see it.
    _set_acting_user(user_b)
    resp_other = await client.delete(f"/api/v1/compliance/dsl/rules/{rule_pk}")
    assert resp_other.status_code == 404

    # Owner can delete.
    _set_acting_user(user_a)
    resp_ok = await client.delete(f"/api/v1/compliance/dsl/rules/{rule_pk}")
    assert resp_ok.status_code == 204

    # And subsequent GET is 404.
    resp_after = await client.get(f"/api/v1/compliance/dsl/rules/{rule_pk}")
    assert resp_after.status_code == 404
