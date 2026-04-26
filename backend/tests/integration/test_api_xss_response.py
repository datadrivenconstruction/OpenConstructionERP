"""End-to-end XSS response sanitisation (BUG-MATH04 fix).

Asserts that the JSON API never returns un-stripped HTML tags in BOQ /
project free-text fields, even when the database contains them.

Two threat models covered:

1. **Live input path** — caller posts ``<b>...</b>`` markup via the
   create API. Input validators strip *dangerous* tags only. Benign tags
   like ``<b>`` reach storage. The response strip then removes them on
   the way out, so a ``dangerouslySetInnerHTML`` consumer never sees a
   tag.

2. **Pre-existing storage** — simulated by writing directly to the DB
   via SQLAlchemy, bypassing the input pipeline entirely (legacy rows,
   raw migrations, bulk imports). The response strip catches these too.

The test mirrors ``test_boq_regression`` for fixture style — module
-scoped client, single user, single auth — so it's fast.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def client():
    """Module-scoped client with full app lifecycle."""
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> dict[str, str]:
    """Register + login a unique admin user once per module."""
    import asyncio

    unique = uuid.uuid4().hex[:8]
    email = f"xssresp-{unique}@test.io"
    password = f"XssResponse{unique}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "XSS Response Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    # Public /auth/register intentionally demotes to viewer (BUG-327/386).
    # Tests need admin to create projects/BOQs/positions, so we promote
    # via direct DB write — same pattern used by test_critical_flows.
    from ._auth_helpers import promote_to_admin
    await promote_to_admin(email)

    token = ""
    for attempt in range(3):
        resp = await client.post(
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


# ── Helpers ──────────────────────────────────────────────────────────────


def _assert_no_html_tags(value: str, *, label: str) -> None:
    """The serialised value must not contain any HTML opening tag.

    A literal ``<`` is allowed (e.g. ``"beam <200mm"``) — what's not
    allowed is the ``<tag-name`` pattern that would be parsed as HTML.
    """
    bad_markers = (
        "<script",
        "<img",
        "<iframe",
        "<svg",
        "<b>",
        "<b ",
        "<i>",
        "<u>",
        "<div",
        "<span",
        "onerror=",
        "onclick=",
        "javascript:",
    )
    lowered = value.lower()
    for marker in bad_markers:
        assert marker not in lowered, (
            f"{label} still contains '{marker}' in response: {value!r}"
        )


# ── Live-input path: input validator + output strip in series ────────────


@pytest.mark.asyncio
async def test_response_strips_html_from_live_input(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """End-to-end: POST with embedded HTML, GET shows tag-free output.

    Verifies the *dangerous* tag (``<img onerror=>``) is fully gone AND
    the *benign* tag (``<b>``) is also stripped — the latter only by
    the response-layer sanitiser, since input validators preserve it.
    """
    # Create a project with a benign HTML name and a benign description.
    proj_resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": "Mitte Tower Phase 1",  # plain — name validator rejects HTML
            "description": "5-story <b>residential</b> with underground parking",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth,
    )
    assert proj_resp.status_code == 201, proj_resp.text
    project = proj_resp.json()
    # Description: <b> stripped on output even though input only blocks dangerous tags.
    _assert_no_html_tags(project["description"], label="ProjectResponse.description")
    assert "residential" in project["description"]
    project_id = project["id"]

    # Create a BOQ — name allows benign tags through input; description likewise.
    boq_resp = await client.post(
        "/api/v1/boq/boqs/",
        json={
            "project_id": project_id,
            "name": "<b>Phase 1 Estimate</b>",
            "description": "Initial <i>draft</i> scope",
        },
        headers=auth,
    )
    assert boq_resp.status_code == 201, boq_resp.text
    boq = boq_resp.json()
    _assert_no_html_tags(boq["name"], label="BOQResponse.name")
    _assert_no_html_tags(boq["description"], label="BOQResponse.description")
    assert "Phase 1 Estimate" in boq["name"]
    assert "draft" in boq["description"]
    boq_id = boq["id"]

    # Position with an attacker payload — input validator strips the
    # dangerous tag, but we also confirm the response is clean.
    pos_resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "01.001",
            "description": "Concrete <b>C30/37</b> wall <img src=x onerror=alert(1)>",
            "unit": "m3",
            "quantity": 10.0,
            "unit_rate": 185.0,
        },
        headers=auth,
    )
    assert pos_resp.status_code == 201, pos_resp.text

    # GET the BOQ — every description / name field must be tag-free.
    full_resp = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    assert full_resp.status_code == 200
    full = full_resp.json()
    _assert_no_html_tags(full["name"], label="BOQ name (GET)")
    _assert_no_html_tags(full["description"], label="BOQ description (GET)")
    for pos in full.get("positions", []):
        _assert_no_html_tags(pos["description"], label=f"Position {pos['ordinal']}")
    for sect in full.get("sections", []):
        _assert_no_html_tags(sect["description"], label=f"Section {sect['ordinal']}")
        for pos in sect.get("positions", []):
            _assert_no_html_tags(pos["description"], label=f"Position {pos['ordinal']}")


# ── Stored-payload path: bypass input validators, write tags directly ────


@pytest.mark.asyncio
async def test_response_strips_html_from_pre_existing_storage(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """Pre-existing rows containing raw HTML must not leak through GET.

    Writes directly to the BOQ Position model via SQLAlchemy, bypassing
    the API and its input validators entirely. This is the realistic
    scenario for legacy data, raw migrations, or bulk-import paths.
    The response endpoint must still strip it.
    """
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.boq.models import Position

    # Bootstrap project + BOQ + section via API (so we have valid FKs).
    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"XSS Storage {uuid.uuid4().hex[:6]}",
            "description": "raw-storage XSS test",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    boq_resp = await client.post(
        "/api/v1/boq/boqs/",
        json={
            "project_id": project_id,
            "name": "Storage XSS BOQ",
            "description": "for storage payload",
        },
        headers=auth,
    )
    assert boq_resp.status_code == 201
    boq_id = boq_resp.json()["id"]

    section_resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/sections/",
        json={"ordinal": "01", "description": "Foundations"},
        headers=auth,
    )
    assert section_resp.status_code == 201, section_resp.text
    section_id = section_resp.json()["id"]

    # Now write a Position with raw HTML directly to storage.
    payload = "<img src=x onerror=alert(1)>BadConcrete"
    async with async_session_factory() as session:
        # Find an existing position to use as a template, or create a fresh one
        # by hand. Direct ORM write bypasses Pydantic input validators entirely.
        pos = Position(
            id=uuid.uuid4(),
            boq_id=uuid.UUID(boq_id),
            parent_id=uuid.UUID(section_id),
            ordinal="01.999",
            description=payload,
            unit="m3",
            quantity="1.0",
            unit_rate="100.0",
            classification={},
            source="manual",
            confidence=None,
            cad_element_ids=[],
            validation_status="pending",
            metadata_={},
            sort_order=999,
        )
        session.add(pos)
        await session.commit()

        # Sanity check: the DB really did keep the raw payload. Filter by
        # ``boq_id`` because earlier test runs may have left ordinal=01.999
        # rows in the shared dev DB.
        stmt = select(Position).where(
            Position.ordinal == "01.999",
            Position.boq_id == uuid.UUID(boq_id),
        )
        row = (await session.execute(stmt)).scalar_one()
        assert row.description == payload, (
            "Storage layer mutated the value — test assumption broken"
        )

    # GET the BOQ via API — response model must strip the tag.
    # ``GET /boqs/{id}`` returns ``BOQWithPositions`` with a flat
    # ``positions`` list (no section nesting). The structured view at
    # ``/boqs/{id}/structured/`` would group by section; either response
    # path goes through ``PositionResponse`` so both are equally good
    # for the assertion. We prefer the flat one — fewer moving parts.
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    target = next(
        (p for p in body.get("positions", []) if p["ordinal"] == "01.999"),
        None,
    )
    assert target is not None, (
        f"Position 01.999 not in flat positions list; "
        f"got ordinals={[p.get('ordinal') for p in body.get('positions', [])]}"
    )
    # Plain ``<img ...>`` is removed by the generic tag stripper. Its body
    # is just inert attribute soup, but the trailing literal "BadConcrete"
    # is outside the tag and survives intact. Documented choice — see
    # ``test_response_sanitisation`` for the unit-level contract.
    assert "<img" not in target["description"]
    assert "onerror" not in target["description"]
    assert "BadConcrete" in target["description"]
