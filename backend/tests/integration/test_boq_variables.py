"""Per-BOQ named variables (Phase B of the v2.7.0 BOQ formula bundle).

Variables live on ``boq.metadata_["variables"]`` and are accessed via two
endpoints:

* ``GET  /api/v1/boq/boqs/{id}/variables/`` — list
* ``PUT  /api/v1/boq/boqs/{id}/variables/`` — replace whole list

Covered:

* Empty default — fresh BOQ has no variables.
* Round-trip a small set of mixed-type variables (number / text / date).
* Type coercion: ``type=number`` with a numeric string is stored as float.
* Validation errors: bad name (lowercase), too long, leading digit, dup name.
* Cap at 50 variables.
* Stripping a leading ``$`` from the submitted name.

Run:
    cd backend
    python -m pytest tests/integration/test_boq_variables.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def shared_client() -> AsyncClient:
    app = create_app()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def shared_auth(shared_client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"boqvars-{unique}@test.io"
    password = f"BoqVars{unique}9!"

    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "BOQ Variables Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(
            sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True),
        )
        await session.commit()

    token = ""
    for attempt in range(3):
        resp = await shared_client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in data.get("detail", ""):
            await asyncio.sleep(5 * (attempt + 1))
            continue
        break
    assert token, f"Login failed: {data}"
    return {"Authorization": f"Bearer {token}"}


async def _create_project(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"VarsTest {uuid.uuid4().hex[:6]}",
            "description": "BOQ variables integration",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create project failed: {resp.text}"
    return resp.json()["id"]


async def _create_boq(client: AsyncClient, auth: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={
            "project_id": project_id,
            "name": f"VarsBOQ {uuid.uuid4().hex[:6]}",
            "description": "BOQ variables integration",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create BOQ failed: {resp.text}"
    return resp.json()["id"]


# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fresh_boq_has_no_variables(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    resp = await shared_client.get(
        f"/api/v1/boq/boqs/{boq_id}/variables/",
        headers=shared_auth,
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_round_trip_mixed_types(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    payload = [
        {"name": "GFA", "type": "number", "value": "1500", "description": "Gross floor area"},
        {"name": "PROJECT_CODE", "type": "text", "value": "P-2026-04", "description": None},
        {"name": "START", "type": "date", "value": "2026-05-01", "description": "Tender open"},
    ]
    put = await shared_client.put(
        f"/api/v1/boq/boqs/{boq_id}/variables/",
        json=payload,
        headers=shared_auth,
    )
    assert put.status_code == 200, put.text
    saved = put.json()
    assert len(saved) == 3
    by_name = {v["name"]: v for v in saved}
    # number coerced to float
    assert by_name["GFA"]["value"] == 1500.0
    assert isinstance(by_name["GFA"]["value"], float)
    assert by_name["PROJECT_CODE"]["value"] == "P-2026-04"
    assert by_name["START"]["value"] == "2026-05-01"

    # GET round-trips identically
    got = await shared_client.get(
        f"/api/v1/boq/boqs/{boq_id}/variables/",
        headers=shared_auth,
    )
    assert got.status_code == 200
    assert got.json() == saved


@pytest.mark.asyncio
async def test_leading_dollar_is_stripped(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    resp = await shared_client.put(
        f"/api/v1/boq/boqs/{boq_id}/variables/",
        json=[{"name": "$LABOR_RATE", "type": "number", "value": 65.5}],
        headers=shared_auth,
    )
    assert resp.status_code == 200, resp.text
    saved = resp.json()
    assert saved[0]["name"] == "LABOR_RATE"


@pytest.mark.asyncio
async def test_invalid_names_rejected(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    bad_names = [
        "lowercase",  # not uppercase
        "1LEAD_DIGIT",  # leading digit
        "WITH SPACE",  # space
        "X" * 33,  # too long (> 32)
        "BAD-DASH",  # disallowed char
        "",  # empty
    ]
    for bad in bad_names:
        resp = await shared_client.put(
            f"/api/v1/boq/boqs/{boq_id}/variables/",
            json=[{"name": bad, "type": "number", "value": 1}],
            headers=shared_auth,
        )
        assert resp.status_code in (400, 422), f"name={bad!r} unexpectedly accepted"


@pytest.mark.asyncio
async def test_duplicate_name_rejected(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    resp = await shared_client.put(
        f"/api/v1/boq/boqs/{boq_id}/variables/",
        json=[
            {"name": "GFA", "type": "number", "value": 1500},
            {"name": "GFA", "type": "number", "value": 1600},
        ],
        headers=shared_auth,
    )
    assert resp.status_code == 400
    assert "Duplicate" in resp.text or "$GFA" in resp.text


@pytest.mark.asyncio
async def test_cap_enforced(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    # 51 valid variables — over the cap of 50
    payload = [{"name": f"VAR_{i:03d}", "type": "number", "value": i} for i in range(51)]
    resp = await shared_client.put(
        f"/api/v1/boq/boqs/{boq_id}/variables/",
        json=payload,
        headers=shared_auth,
    )
    assert resp.status_code == 400
    assert "Too many" in resp.text


@pytest.mark.asyncio
async def test_replace_truncates_old_list(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    """PUT replaces the whole list — not a merge."""
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    await shared_client.put(
        f"/api/v1/boq/boqs/{boq_id}/variables/",
        json=[
            {"name": "A", "type": "number", "value": 1},
            {"name": "B", "type": "number", "value": 2},
        ],
        headers=shared_auth,
    )
    # Replace with a single variable
    resp = await shared_client.put(
        f"/api/v1/boq/boqs/{boq_id}/variables/",
        json=[{"name": "C", "type": "text", "value": "hello"}],
        headers=shared_auth,
    )
    assert resp.status_code == 200
    names = [v["name"] for v in resp.json()]
    assert names == ["C"]


@pytest.mark.asyncio
async def test_non_numeric_value_rejected_for_number_type(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    resp = await shared_client.put(
        f"/api/v1/boq/boqs/{boq_id}/variables/",
        json=[{"name": "GFA", "type": "number", "value": "not a number"}],
        headers=shared_auth,
    )
    assert resp.status_code == 400
    assert "numeric" in resp.text.lower()


@pytest.mark.asyncio
async def test_empty_value_normalised_to_null(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    resp = await shared_client.put(
        f"/api/v1/boq/boqs/{boq_id}/variables/",
        json=[
            {"name": "EMPTY_NUM", "type": "number", "value": None},
            {"name": "EMPTY_STR", "type": "text", "value": ""},
        ],
        headers=shared_auth,
    )
    assert resp.status_code == 200
    saved = {v["name"]: v["value"] for v in resp.json()}
    assert saved["EMPTY_NUM"] is None
    assert saved["EMPTY_STR"] is None


@pytest.mark.asyncio
async def test_boundary_50_variables_accepted(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    payload = [{"name": f"VAR_{i:03d}", "type": "number", "value": float(i)} for i in range(50)]
    resp = await shared_client.put(
        f"/api/v1/boq/boqs/{boq_id}/variables/",
        json=payload,
        headers=shared_auth,
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 50
