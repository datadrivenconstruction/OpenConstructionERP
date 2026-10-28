# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠API-level regression tests for the production-norm library (issue #442).

Two faults, both reachable from a plain request body.

The first is a serialization-time lazy load. ``create_norm`` only touched
``norm.materials`` from inside the loop over the request's material list, so a
body without materials left that collection *unloaded* on the freshly inserted
instance. ``NormResponse.model_validate`` then read it from the router's
synchronous serialization step, the ``selectin`` loader tried to emit its SELECT
outside the async greenlet, and the resulting ``MissingGreenlet`` surfaced as a
pydantic ``ValidationError`` -> HTTP 500. The distinguishing symptom is not the
status code but the rollback: the session dependency rolls the request back, so
the norm the client was told about never existed. These tests therefore assert
the row is in the database, not merely that the response looked right.

The second is the nullability disagreement. Every ``NormUpdate`` field is typed
``| None`` purely as the "field omitted" sentinel, but every column behind it is
NOT NULL, and ``model_dump(exclude_unset=True)`` cannot tell an omitted field
from one the client explicitly set to ``null``. An explicit null therefore
reached ``setattr`` and the flush raised ``IntegrityError``. The database is
right (a null productivity coefficient has no meaning - the expansion math
multiplies it), so the schema rejects an explicit null with a 422.

The tests drive the module's own router over ASGI with the database dependency
pointed at the shared, transaction-isolated ``oe_test_unit`` session, the same
fixture style the other norm-expansion tests use. The override reproduces
``app.dependencies.get_session`` exactly - commit on success, rollback on
exception - because the rollback is the behaviour under test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.dependencies import get_current_user_payload, get_session
from app.modules.norm_expansion.models import ProductionNorm
from app.modules.norm_expansion.router import router as norm_expansion_router
from tests._pg import transactional_session

_PREFIX = "/api/v1/norm-expansion"
_USER_ID = "3f0f2f9a-2d4a-4a55-9c2f-7d5f9c8b1e40"


@pytest_asyncio.fixture
async def session() -> AsyncIterator[Any]:
    async with transactional_session() as s:
        yield s


@pytest_asyncio.fixture
async def client(session) -> AsyncIterator[AsyncClient]:
    """The norm-expansion router over ASGI, bound to the test session."""

    async def _session_override():
        # Mirrors app.dependencies.get_session: the request commits on success
        # and rolls back on failure. Under join_transaction_mode="create_savepoint"
        # that is a savepoint release / rollback, so a failed request undoes its
        # own writes while the fixture's outer transaction survives.
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    async def _payload_override() -> dict[str, Any]:
        return {"sub": _USER_ID, "role": "admin", "permissions": []}

    app = FastAPI()
    app.include_router(norm_expansion_router, prefix=_PREFIX)
    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_payload] = _payload_override

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _rows_with_key(session, work_key: str) -> int:
    """Count the persisted norms carrying ``work_key`` (a real DB round-trip)."""
    return await session.scalar(
        select(func.count()).select_from(ProductionNorm).where(ProductionNorm.work_key == work_key)
    )


# ── Fault one: creating a norm must persist it ───────────────────────────────


async def test_creating_a_norm_without_materials_persists_the_row(client, session) -> None:
    """The reporter's minimal body: no materials, so nothing ever touched the collection."""
    body = {
        "work_key": "sc-mo-038",
        "name": "Test norm",
        "unit": "m2",
        "category": "Test",
        "labor_hours_per_unit": 1.5,
        "notes": "test",
        "is_active": True,
    }

    response = await client.post(f"{_PREFIX}/norms/", json=body)

    assert response.status_code == 201, response.text
    assert response.json()["materials"] == []
    # The status code alone proves nothing here: the fault rolled the request
    # back, so the row is the assertion that distinguishes fixed from broken.
    assert await _rows_with_key(session, "sc-mo-038") == 1


async def test_creating_a_norm_with_materials_persists_the_row(client, session) -> None:
    """The path that always worked stays working - the fix must not trade one for the other."""
    body = {
        "work_key": "sc-mo-039",
        "name": "Test norm with materials",
        "unit": "m2",
        "labor_hours_per_unit": 1.5,
        "materials": [
            {"name": "Gypsum plaster", "unit": "kg", "qty_per_unit": 12},
            {"name": "Water", "unit": "l", "qty_per_unit": 6},
        ],
    }

    response = await client.post(f"{_PREFIX}/norms/", json=body)

    assert response.status_code == 201, response.text
    assert [m["name"] for m in response.json()["materials"]] == ["Gypsum plaster", "Water"]
    assert await _rows_with_key(session, "sc-mo-039") == 1


# ── Fault two: an explicit null never reaches a NOT NULL column ──────────────


async def test_patching_a_coefficient_to_null_is_refused_by_the_schema(client, session) -> None:
    """``machine_hours_per_unit: null`` is a 422, not an IntegrityError-driven 500."""
    created = await client.post(
        f"{_PREFIX}/norms/",
        json={"work_key": "sc-mo-040", "unit": "m2", "machine_hours_per_unit": 0.25},
    )
    assert created.status_code == 201, created.text
    norm_id = created.json()["id"]

    response = await client.patch(f"{_PREFIX}/norms/{norm_id}", json={"machine_hours_per_unit": None})

    assert response.status_code == 422, response.text
    # The norm survives the refused patch with its coefficient untouched.
    readback = await client.get(f"{_PREFIX}/norms/{norm_id}")
    assert readback.status_code == 200, readback.text
    assert readback.json()["machine_hours_per_unit"] == "0.250000"
    assert await _rows_with_key(session, "sc-mo-040") == 1


async def test_patching_a_string_field_to_null_is_refused_by_the_schema(client) -> None:
    """Every NormUpdate field is NOT NULL underneath, so the whole model refuses null.

    ``work_key`` is the field that made this worth generalising: its
    ``min_length=1`` constraint does not apply to ``None``, so an explicit null
    passed validation and hit the same NOT NULL column as the coefficients.
    """
    created = await client.post(f"{_PREFIX}/norms/", json={"work_key": "sc-mo-041", "unit": "m2"})
    assert created.status_code == 201, created.text
    norm_id = created.json()["id"]

    for field in ("work_key", "name", "unit", "category", "notes", "is_active", "labor_hours_per_unit"):
        response = await client.patch(f"{_PREFIX}/norms/{norm_id}", json={field: None})
        assert response.status_code == 422, f"{field}: {response.status_code} {response.text}"


async def test_omitting_a_field_still_leaves_it_unchanged(client) -> None:
    """The null guard must not break the partial-update semantics it protects."""
    created = await client.post(
        f"{_PREFIX}/norms/",
        json={"work_key": "sc-mo-042", "name": "Before", "unit": "m2", "labor_hours_per_unit": 2},
    )
    assert created.status_code == 201, created.text
    norm_id = created.json()["id"]

    response = await client.patch(f"{_PREFIX}/norms/{norm_id}", json={"name": "After"})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["name"] == "After"
    assert payload["unit"] == "m2"
    assert payload["labor_hours_per_unit"] == "2.000000"


@pytest.mark.parametrize("work_key", ["sc-mo-043"])
async def test_a_duplicate_work_key_is_still_a_conflict(client, work_key: str) -> None:
    """Guard the create path's other branch while we are rewriting its collection handling."""
    first = await client.post(f"{_PREFIX}/norms/", json={"work_key": work_key, "unit": "m2"})
    assert first.status_code == 201, first.text

    second = await client.post(f"{_PREFIX}/norms/", json={"work_key": work_key, "unit": "m2"})
    assert second.status_code == 409, second.text
