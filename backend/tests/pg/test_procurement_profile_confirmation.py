# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Per-instance confirmation of procurement profile values on PostgreSQL: revision v3340 and the API.

Confirming needs the profiles permission, binds to the exact value the person
saw (path + hash), is visible only to the confirming company, and revoking
makes the value advisory again.
"""

from __future__ import annotations

import importlib.util
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.procurement_concept.models import ProfileConfirmation
from app.modules.procurement_concept.permissions import register_procurement_concept_permissions
from app.modules.procurement_concept.router import router
from tests._pg import isolated_engine

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

BASE = "/api/v1/procurement-concept"
TABLE = ProfileConfirmation.__tablename__


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(sync_conn, direction) -> None:
    with Operations.context(MigrationContext.configure(sync_conn)):
        direction()


def _reflect(sync_conn) -> dict:
    insp = sa.inspect(sync_conn)
    if TABLE not in insp.get_table_names():
        return {}
    return {
        "columns": {c["name"]: (str(c["type"]), c["nullable"]) for c in insp.get_columns(TABLE)},
        "indexes": {i["name"] for i in insp.get_indexes(TABLE) if (i.get("name") or "").startswith("ix_oe_pcc_")},
        "unique": {u["name"] for u in insp.get_unique_constraints(TABLE)},
    }


async def test_revision_builds_the_model_schema_up_down_up() -> None:
    rev = _load("v3340_procurement_profile_confirmation")
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            from_models = await conn.run_sync(_reflect)
            await conn.run_sync(_run, rev.upgrade)  # no-op over create_all
            assert await conn.run_sync(_reflect) == from_models
            await conn.run_sync(_run, rev.downgrade)
            assert await conn.run_sync(_reflect) == {}
            await conn.run_sync(_run, rev.upgrade)
            assert await conn.run_sync(_reflect) == from_models
    assert from_models["unique"] == {"uq_oe_pcc_profile_confirmation"}


@pytest_asyncio.fixture
async def factory():
    register_procurement_concept_permissions()
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def client_as(factory, user_id: uuid.UUID, role: str):
    from app.dependencies import get_current_user_id, get_current_user_payload, get_session

    app = FastAPI()
    app.include_router(router, prefix=BASE)

    async def _session():
        async with factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": str(user_id), "role": role, "permissions": []}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://pc-test") as c:
        yield c


def _first_unconfirmed(body: dict) -> dict:
    return next(v for v in body["values"] if v["status"] == "unconfirmed")


async def test_confirm_and_revoke_a_value_for_this_company_only(factory) -> None:
    manager, other, editor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with client_as(factory, editor, "editor") as c:
        listed = await c.get(f"{BASE}/profiles/DE/values")
        assert listed.status_code == 200
        body = listed.json()
        assert body["chain"] == ["EU", "DE"]
        assert body["can"]["confirm"]["allowed"] is False
        assert all(v["source_url"] and v["effective_from"] for v in body["values"])
        row = _first_unconfirmed(body)
        payload = {"path": row["path"], "value_hash": row["value_hash"], "source_checked": row["source_url"]}
        assert (await c.post(f"{BASE}/profiles/DE/confirmations", json=payload)).status_code == 403

    async with client_as(factory, manager, "manager") as c:
        stale_hash = await c.post(f"{BASE}/profiles/DE/confirmations", json={**payload, "value_hash": "0" * 64})
        assert stale_hash.status_code == 409
        assert stale_hash.json()["detail"]["code"] == "profile_value_changed"
        # The legacy v1 code resolves to the same profile.
        made = await c.post(f"{BASE}/profiles/de_national/confirmations", json=payload)
        assert made.status_code == 201, made.text
        assert (await c.post(f"{BASE}/profiles/DE/confirmations", json=payload)).status_code == 409
        mine = {v["path"]: v for v in (await c.get(f"{BASE}/profiles/DE/values")).json()["values"]}
        assert mine[row["path"]]["status"] == "confirmed"
        assert mine[row["path"]]["confirmation"]["id"] == made.json()["id"]
        assert (await c.get(f"{BASE}/profiles/XX/values")).status_code == 404

    async with client_as(factory, other, "manager") as c:
        theirs = {v["path"]: v for v in (await c.get(f"{BASE}/profiles/DE/values")).json()["values"]}
        assert theirs[row["path"]]["status"] == "unconfirmed"
        assert (await c.delete(f"{BASE}/profiles/confirmations/{made.json()['id']}")).status_code == 404

    async with client_as(factory, manager, "manager") as c:
        assert (await c.delete(f"{BASE}/profiles/confirmations/{made.json()['id']}")).status_code == 204
        again = {v["path"]: v for v in (await c.get(f"{BASE}/profiles/DE/values")).json()["values"]}
        assert again[row["path"]]["status"] == "unconfirmed"
        assert again[row["path"]]["confirmation"] is None
