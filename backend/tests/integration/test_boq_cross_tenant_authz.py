# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cross-tenant authorization regression for the BOQ analytics / enrichment
endpoints and the AI-estimator unfiltered run listing.

Locks in the just-shipped owner-gate fixes so a future refactor that drops a
``_verify_boq_owner`` call (or the ai-estimator ``accessible_to`` scope) fails
loudly. Each case stands up two real, separately-registered users through the
ASGI app:

* Owner A - promoted to admin so they can create a project (``projects.create``
  is EDITOR-gated) and the BOQ / positions under it.
* Outsider B - a freshly-registered default ``viewer`` who is neither the
  project owner nor a project member. The BOQ module deliberately grants
  ``boq.read`` AND ``boq.update`` to VIEWER (see
  ``app/modules/boq/permissions.py``), so B clears the ``RequirePermission``
  route dependency and is stopped *only* by the cross-tenant owner gate. That
  is the point: these tests exercise the IDOR guard itself, not the RBAC
  permission gate.

Guarded endpoints under test (all mounted under ``/api/v1/boq`` - the module
loader kebab-cases the ``boq`` slug, which has no underscore, so the prefix is
``/api/v1/boq``):

    GET  /boqs/{boq_id}/resource-summary/
    GET  /boqs/{boq_id}/cost-breakdown/
    GET  /boqs/{boq_id}/statistics/
    GET  /boqs/{boq_id}/sensitivity/
    GET  /boqs/{boq_id}/classification/
    GET  /boqs/{boq_id}/cost-risk/
    GET  /boqs/{boq_id}/sustainability/
    POST /boqs/{boq_id}/enrich-resources/   (write)
    POST /boqs/{boq_id}/enrich-co2/         (write)
    GET  /boqs/{boq_id}/columns/
    GET  /boqs/{boq_id}/variables/
    GET  /positions/{position_id}/similar/
    PUT  /positions/{position_id}/co2/      (write)

And the ai-estimator cross-tenant listing fix (``/api/v1/ai-estimator``):

    GET  /runs   (no project_id -> must NOT return another tenant's runs)

The expected denial status is 403 (``_verify_boq_owner`` raises 403 for an
authenticated non-owner / non-member / non-admin); we accept 404 as well since
some guards close the existence oracle with 404. The owner A always gets a 2xx.

No network, no AI key, no Qdrant: the BOQ owner gate fires before any heavy
work, and the ai-estimator listing is a pure DB query.

Run:
    cd backend
    python -m pytest tests/integration/test_boq_cross_tenant_authz.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Eager-import the model namespaces this suite touches so Base.metadata sees a
# coherent table set when create_all runs (mirrors the ai_estimator + costs
# IDOR baselines).
import app.modules.ai_estimator.models  # noqa: E402,F401
import app.modules.boq.models  # noqa: E402,F401
import app.modules.costs.models  # noqa: E402,F401
import app.modules.projects.models  # noqa: E402,F401
import app.modules.teams.models  # noqa: E402,F401
import app.modules.users.models  # noqa: E402,F401

# Every test in this file has identity as the variable under test.
pytestmark = pytest.mark.tenant_isolation

# Statuses that count as "denied" for an outsider. 403 is what the BOQ owner
# gate raises for an authenticated non-owner; 404 is accepted because some
# guards prefer to keep the id's existence opaque.
DENIED = (403, 404)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module and create all tables.

    The lifespan runs the module loader's on_startup hooks, which register the
    boq + ai_estimator permissions and validation rules.
    """
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


async def _activate_user(email: str) -> None:
    """Force ``is_active=True`` so login works regardless of registration mode."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await s.commit()


async def _register_login(
    client: AsyncClient,
    *,
    tenant: str,
    role: str | None = None,
) -> tuple[str, str, dict[str, str]]:
    """Register, activate, optionally promote, log in.

    Returns ``(user_id, email, auth_headers)``. When ``role`` is None the user
    keeps the default registration role (``viewer`` under the open-registration
    test mode) - that is what the outsider needs to still hold ``boq.read`` /
    ``boq.update`` while failing the owner gate.
    """
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@boq-authz.io"
    password = f"BoqAuthz{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), f"register failed for {tenant}: {reg.status_code} {reg.text}"
    user_id = reg.json()["id"]

    await _activate_user(email)

    if role is not None:
        from sqlalchemy import update

        from app.database import async_session_factory
        from app.modules.users.models import User

        async with async_session_factory() as s:
            await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
            await s.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed for {tenant}: {login.text}"
    token = login.json()["access_token"]
    return user_id, email, {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def owner_a(http_client):
    """Owner A - admin so they can create projects/BOQs/positions."""
    uid, email, headers = await _register_login(http_client, tenant="owner-a", role="admin")
    return {"user_id": uid, "email": email, "headers": headers}


@pytest_asyncio.fixture(scope="module")
async def outsider_b(http_client):
    """Outsider B - a default viewer with no relationship to A's project.

    A viewer still holds boq.read / boq.update (granted to VIEWER by the boq
    module), so B passes the RequirePermission gate and is rejected purely by
    the cross-tenant owner gate.
    """
    uid, email, headers = await _register_login(http_client, tenant="outsider-b", role=None)
    return {"user_id": uid, "email": email, "headers": headers}


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"AuthzProj {uuid.uuid4().hex[:6]}",
            "description": "BOQ cross-tenant authz regression",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert resp.status_code == 201, f"create project failed: {resp.text}"
    return resp.json()["id"]


async def _create_boq(client: AsyncClient, headers: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={
            "project_id": project_id,
            "name": f"AuthzBOQ {uuid.uuid4().hex[:6]}",
            "description": "BOQ cross-tenant authz regression",
        },
        headers=headers,
    )
    assert resp.status_code == 201, f"create BOQ failed: {resp.text}"
    return resp.json()["id"]


async def _add_position(
    client: AsyncClient,
    headers: dict[str, str],
    boq_id: str,
    *,
    description: str = "RC wall C30/37",
    ordinal: str = "0010",
) -> str:
    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": ordinal,
            "description": description,
            "unit": "m3",
            "quantity": 10.0,
            "unit_rate": 185.0,
        },
        headers=headers,
    )
    assert resp.status_code == 201, f"add position failed: {resp.text}"
    return resp.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def a_boq(http_client, owner_a):
    """A project + BOQ + one position, all owned by A. Module-scoped: the owner
    gate is read-only for these resources so all cases can share one fixture."""
    project_id = await _create_project(http_client, owner_a["headers"])
    boq_id = await _create_boq(http_client, owner_a["headers"], project_id)
    position_id = await _add_position(http_client, owner_a["headers"], boq_id)
    return {"project_id": project_id, "boq_id": boq_id, "position_id": position_id}


# ── BOQ read endpoints: outsider denied, owner allowed ───────────────────────

# (path-suffix, denied-status-also-allows-200?) - all GET, all owner gated.
_BOQ_GET_ENDPOINTS = [
    "resource-summary",
    "cost-breakdown",
    "statistics",
    "sensitivity",
    "classification",
    "cost-risk",
    "sustainability",
    "columns",
    "variables",
]


@pytest.mark.parametrize("suffix", _BOQ_GET_ENDPOINTS)
@pytest.mark.asyncio
async def test_outsider_denied_on_boq_get_endpoint(http_client, a_boq, outsider_b, suffix):
    """An outsider must not read A's BOQ analytics/enrichment surface."""
    boq_id = a_boq["boq_id"]
    resp = await http_client.get(
        f"/api/v1/boq/boqs/{boq_id}/{suffix}/",
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, (
        f"LEAK: outsider B read /boqs/{{id}}/{suffix}/ (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.parametrize("suffix", _BOQ_GET_ENDPOINTS)
@pytest.mark.asyncio
async def test_owner_allowed_on_boq_get_endpoint(http_client, a_boq, owner_a, suffix):
    """The legitimate owner A must be allowed (2xx) on every guarded GET."""
    boq_id = a_boq["boq_id"]
    resp = await http_client.get(
        f"/api/v1/boq/boqs/{boq_id}/{suffix}/",
        headers=owner_a["headers"],
    )
    assert 200 <= resp.status_code < 300, (
        f"REGRESSION: owner A blocked on /boqs/{{id}}/{suffix}/ (status {resp.status_code}). Body: {resp.text!r}"
    )


# ── BOQ write endpoints (enrich): outsider denied ────────────────────────────


@pytest.mark.asyncio
async def test_outsider_denied_enrich_resources(http_client, a_boq, outsider_b):
    """POST enrich-resources is a write on A's BOQ - outsider must be denied."""
    boq_id = a_boq["boq_id"]
    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq_id}/enrich-resources/",
        json={},
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, (
        f"LEAK: outsider B ran enrich-resources on A's BOQ (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_owner_allowed_enrich_resources(http_client, a_boq, owner_a):
    """Owner A can run enrich-resources on their own BOQ."""
    boq_id = a_boq["boq_id"]
    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq_id}/enrich-resources/",
        json={},
        headers=owner_a["headers"],
    )
    assert 200 <= resp.status_code < 300, (
        f"REGRESSION: owner A blocked on enrich-resources (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_outsider_denied_enrich_co2(http_client, a_boq, outsider_b):
    """POST enrich-co2 is a write on A's BOQ - outsider must be denied."""
    boq_id = a_boq["boq_id"]
    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq_id}/enrich-co2/",
        json={},
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, (
        f"LEAK: outsider B ran enrich-co2 on A's BOQ (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_owner_allowed_enrich_co2(http_client, a_boq, owner_a):
    """Owner A can run enrich-co2 on their own BOQ."""
    boq_id = a_boq["boq_id"]
    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq_id}/enrich-co2/",
        json={},
        headers=owner_a["headers"],
    )
    assert 200 <= resp.status_code < 300, (
        f"REGRESSION: owner A blocked on enrich-co2 (status {resp.status_code}). Body: {resp.text!r}"
    )


# ── Position endpoints: similar (read) + co2 (write) ─────────────────────────


@pytest.mark.asyncio
async def test_outsider_denied_position_similar(http_client, a_boq, outsider_b):
    """Seeding a similarity search from A's position must be denied for B.

    Without the guard any caller could probe arbitrary position ids and
    trigger a vector search keyed off another tenant's row.
    """
    position_id = a_boq["position_id"]
    resp = await http_client.get(
        f"/api/v1/boq/positions/{position_id}/similar/",
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, (
        f"LEAK: outsider B seeded similar-search from A's position (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_owner_allowed_position_similar(http_client, a_boq, owner_a):
    """Owner A can run the similarity search from their own position."""
    position_id = a_boq["position_id"]
    resp = await http_client.get(
        f"/api/v1/boq/positions/{position_id}/similar/",
        headers=owner_a["headers"],
    )
    assert 200 <= resp.status_code < 300, (
        f"REGRESSION: owner A blocked on position similar (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_outsider_denied_position_co2(http_client, a_boq, outsider_b):
    """PUT position co2 is a write on A's position - outsider must be denied.

    A valid (existing) EPD id is sent so the request would otherwise succeed;
    the owner gate must stop it.
    """
    position_id = a_boq["position_id"]
    resp = await http_client.put(
        f"/api/v1/boq/positions/{position_id}/co2/",
        json={"epd_id": "c30-37"},
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, (
        f"LEAK: outsider B assigned CO2 to A's position (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_owner_allowed_position_co2(http_client, a_boq, owner_a):
    """Owner A can assign CO2 to their own position with a valid EPD id.

    ``c30-37`` is a real material in the EPD index, so the request resolves to
    a clean 2xx for the legitimate owner - no ownership block.
    """
    position_id = a_boq["position_id"]
    resp = await http_client.put(
        f"/api/v1/boq/positions/{position_id}/co2/",
        json={"epd_id": "c30-37"},
        headers=owner_a["headers"],
    )
    assert 200 <= resp.status_code < 300, (
        f"REGRESSION: owner A blocked on their own position co2 (status {resp.status_code}). Body: {resp.text!r}"
    )


# ── Newly-guarded BOQ endpoints (Wave 2 security sweep) ──────────────────────
#
# These endpoints take a ``{boq_id}`` path param and were missing the
# ``_verify_boq_owner`` owner gate (they relied only on the VIEWER-granted
# ``boq.read`` / ``boq.update`` RequirePermission dependency, which an outsider
# clears). The owner gate fires before any AI / file / DB-heavy work, so these
# cases need no AI key, no Qdrant and no real upload payload - the outsider is
# rejected at the gate. We assert the security property (outsider -> denied) for
# every endpoint, and additionally assert owner-allowed for the ones that resolve
# to a clean 2xx without any external dependency.


# POST/PATCH endpoints that mutate or analyse A's BOQ via a JSON body.
# (suffix, http-method, json-body)
_BOQ_WRITE_JSON_ENDPOINTS = [
    ("recalculate-rates", "post", {}),
    ("validate", "post", {}),
    ("renumber", "post", {}),
    ("check-anomalies", "post", {}),
    ("ai-chat", "post", {"message": "add a position", "context": {}}),
    (
        "check-scope",
        "post",
        {"project_type": "general", "region": "DACH", "currency": "EUR", "locale": "en"},
    ),
]


@pytest.mark.parametrize("suffix,method,body", _BOQ_WRITE_JSON_ENDPOINTS)
@pytest.mark.asyncio
async def test_outsider_denied_on_boq_write_json_endpoint(http_client, a_boq, outsider_b, suffix, method, body):
    """An outsider must be owner-gated out of every BOQ write/analyse endpoint."""
    boq_id = a_boq["boq_id"]
    resp = await getattr(http_client, method)(
        f"/api/v1/boq/boqs/{boq_id}/{suffix}/",
        json=body,
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, (
        f"LEAK: outsider B reached /boqs/{{id}}/{suffix}/ (status {resp.status_code}). Body: {resp.text!r}"
    )


# Endpoints that resolve to a clean 2xx for the legitimate owner with no AI key /
# network (pure DB work). ai-chat / check-anomalies / check-scope are excluded
# here because they need a configured AI provider or the vector DB to return 2xx.
_BOQ_OWNER_OK_JSON_ENDPOINTS = [
    ("recalculate-rates", "post", {}),
    ("validate", "post", {}),
    ("renumber", "post", {}),
]


@pytest.mark.parametrize("suffix,method,body", _BOQ_OWNER_OK_JSON_ENDPOINTS)
@pytest.mark.asyncio
async def test_owner_allowed_on_boq_write_json_endpoint(http_client, a_boq, owner_a, suffix, method, body):
    """Owner A is allowed (2xx) on the DB-only write endpoints they own."""
    boq_id = a_boq["boq_id"]
    resp = await getattr(http_client, method)(
        f"/api/v1/boq/boqs/{boq_id}/{suffix}/",
        json=body,
        headers=owner_a["headers"],
    )
    assert 200 <= resp.status_code < 300, (
        f"REGRESSION: owner A blocked on /boqs/{{id}}/{suffix}/ (status {resp.status_code}). Body: {resp.text!r}"
    )


# Import endpoints: multipart uploads. The owner gate fires before the file is
# parsed, so a tiny dummy payload is enough to prove the outsider is rejected.
_BOQ_IMPORT_ENDPOINTS = [
    ("import/excel", "data.csv", b"Pos,Description\n0010,Wall\n", "text/csv"),
    ("import/auto", "data.csv", b"Pos,Description\n0010,Wall\n", "text/csv"),
    ("import/gaeb", "boq.x83", b"<GAEB></GAEB>", "application/xml"),
    ("import/smart", "data.csv", b"Pos,Description\n0010,Wall\n", "text/csv"),
]


@pytest.mark.parametrize("suffix,fname,blob,ctype", _BOQ_IMPORT_ENDPOINTS)
@pytest.mark.asyncio
async def test_outsider_denied_on_boq_import_endpoint(http_client, a_boq, outsider_b, suffix, fname, blob, ctype):
    """An outsider must not import positions into A's BOQ (owner gate first)."""
    boq_id = a_boq["boq_id"]
    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq_id}/{suffix}/",
        files={"file": (fname, blob, ctype)},
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, (
        f"LEAK: outsider B imported into A's BOQ via {suffix} (status {resp.status_code}). Body: {resp.text!r}"
    )


# Custom-column + variable mutations: an outsider must not alter A's BOQ schema.
@pytest.mark.asyncio
async def test_outsider_denied_add_custom_column(http_client, a_boq, outsider_b):
    """POST columns mutates A's BOQ metadata - outsider must be denied."""
    boq_id = a_boq["boq_id"]
    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq_id}/columns/",
        json={"name": "supplier", "column_type": "text"},
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, (
        f"LEAK: outsider B added a custom column to A's BOQ (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_outsider_denied_delete_custom_column(http_client, a_boq, outsider_b):
    """DELETE columns mutates A's BOQ metadata - outsider must be denied."""
    boq_id = a_boq["boq_id"]
    resp = await http_client.delete(
        f"/api/v1/boq/boqs/{boq_id}/columns/supplier",
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, (
        f"LEAK: outsider B deleted a custom column on A's BOQ (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_outsider_denied_replace_variables(http_client, a_boq, outsider_b):
    """PUT variables replaces A's BOQ variable table - outsider must be denied."""
    boq_id = a_boq["boq_id"]
    resp = await http_client.put(
        f"/api/v1/boq/boqs/{boq_id}/variables/",
        json=[{"name": "GFA", "type": "number", "value": 1000}],
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, (
        f"LEAK: outsider B replaced A's BOQ variables (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_owner_allowed_column_and_variable_writes(http_client, a_boq, owner_a):
    """Owner A can add a column, replace variables, then delete the column (2xx)."""
    boq_id = a_boq["boq_id"]
    add = await http_client.post(
        f"/api/v1/boq/boqs/{boq_id}/columns/",
        json={"name": "supplier", "column_type": "text"},
        headers=owner_a["headers"],
    )
    assert add.status_code == 201, f"owner add column failed: {add.text}"

    put_vars = await http_client.put(
        f"/api/v1/boq/boqs/{boq_id}/variables/",
        json=[{"name": "GFA", "type": "number", "value": 1000}],
        headers=owner_a["headers"],
    )
    assert 200 <= put_vars.status_code < 300, f"owner replace variables failed: {put_vars.text}"

    delete = await http_client.delete(
        f"/api/v1/boq/boqs/{boq_id}/columns/supplier",
        headers=owner_a["headers"],
    )
    assert delete.status_code == 204, f"owner delete column failed: {delete.text}"


# ── ai-estimator: unfiltered /runs must not leak another tenant's runs ────────


@pytest.mark.asyncio
async def test_ai_estimator_unfiltered_runs_excludes_other_tenant(http_client, owner_a, outsider_b):
    """GET /ai-estimator/runs with NO project_id must scope to the caller.

    A run is created under a project owned by A. Outsider B's unfiltered
    listing must not contain A's run id (the pre-fix behaviour returned every
    tenant's runs). A's own unfiltered listing must contain it.
    """
    # A creates a project + a run under it.
    project_id = await _create_project(http_client, owner_a["headers"])
    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={"project_id": project_id, "source": "text", "text_input": "Brick wall, 24cm"},
        headers=owner_a["headers"],
    )
    assert create.status_code == 201, create.text
    run_id = create.json()["id"]

    # B lists runs with no project filter -> must not see A's run.
    b_list = await http_client.get("/api/v1/ai-estimator/runs", headers=outsider_b["headers"])
    assert b_list.status_code == 200, b_list.text
    b_run_ids = {r["id"] for r in b_list.json()["runs"]}
    assert run_id not in b_run_ids, (
        f"LEAK: outsider B's unfiltered /runs listing contains A's run {run_id}. Returned ids: {sorted(b_run_ids)}"
    )

    # A's own unfiltered listing DOES contain it (sanity: the scope is not
    # accidentally empty-for-everyone).
    a_list = await http_client.get("/api/v1/ai-estimator/runs", headers=owner_a["headers"])
    assert a_list.status_code == 200, a_list.text
    a_run_ids = {r["id"] for r in a_list.json()["runs"]}
    assert run_id in a_run_ids, (
        f"REGRESSION: owner A's own unfiltered /runs listing is missing their run {run_id}. "
        f"Returned ids: {sorted(a_run_ids)}"
    )
