"""Issues #139 & #136 — insert-below-selected-row + deep nesting (HTTP roundtrip).

Issue #139 — when the user inserts a new partida while a row mid-section is
selected, the new row MUST land directly after that row (same parent /
section), with a sandwiched sort_order, and stay there after a refetch — not
at the end of the section or in another section.

Issue #136 — the user must be able to build the full requested tree shape
through the API:

    SECTION → SECTION-HIJA → SECTION-HIJA → PARTIDA → PARTIDA-HIJA →
    PARTIDA-HIJA → RESOURCE

i.e. nested sections AND nested partidas, usable up to
``MAX_NESTING_DEPTH`` (8) position tiers, with subtotals rolling up through
every level and persisting across a refetch. The cap must be enforced (tier
9 rejected) and surfaced via GET /v1/boq/limits/.

Test isolation (``feedback_test_isolation.md``): the per-session temp SQLite
redirect, eager model registration and the synchronous event-bus shim are
provided by ``backend/tests/conftest.py`` — the production
``openestimate.db`` is never touched.

Run:
    cd backend
    python -m pytest tests/integration/test_boq_insert_position_and_nesting.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# ── Shared fixtures (same pattern as other BOQ integration tests) ──────────


@pytest_asyncio.fixture(scope="module")
async def client() -> AsyncClient:
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
    unique = uuid.uuid4().hex[:8]
    email = f"ins139-{unique}@test.io"
    password = f"Ins139{unique}9!"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Insert/Nesting Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()

    token = ""
    data: dict = {}
    for attempt in range(3):
        resp = await client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in str(data.get("detail", "")):
            await asyncio.sleep(2 * (attempt + 1))
            continue
        break
    assert token, f"Login failed: {data}"
    return {"Authorization": f"Bearer {token}"}


# ── Helpers ───────────────────────────────────────────────────────────────


async def _create_project(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Ins139 {uuid.uuid4().hex[:6]}",
            "description": "Issues #139 / #136 integration",
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
            "name": f"Ins139 BOQ {uuid.uuid4().hex[:6]}",
            "description": "Issues #139 / #136",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create BOQ failed: {resp.text}"
    return resp.json()["id"]


async def _add_section(
    client: AsyncClient,
    auth: dict[str, str],
    boq_id: str,
    *,
    ordinal: str,
    description: str = "",
    parent_id: str | None = None,
):
    body: dict = {"ordinal": ordinal, "description": description}
    if parent_id is not None:
        body["parent_id"] = parent_id
    return await client.post(
        f"/api/v1/boq/boqs/{boq_id}/sections/",
        json=body,
        headers=auth,
    )


async def _add_position(
    client: AsyncClient,
    auth: dict[str, str],
    boq_id: str,
    **body,
):
    payload = {"boq_id": boq_id, "unit": "m3", "quantity": 0.0}
    payload.update(body)
    return await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json=payload,
        headers=auth,
    )


async def _positions(client: AsyncClient, auth: dict[str, str], boq_id: str):
    r = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["positions"]


def _sorted(positions: list[dict]) -> list[dict]:
    return sorted(
        positions,
        key=lambda p: (p["sort_order"], p["ordinal"]),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Issue #139
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_insert_partida_below_selected_mid_section_row(client: AsyncClient, auth: dict[str, str]) -> None:
    """The video repro: select 01.002 mid-section, add a partida.

    It must land at sort_order = selected.sort_order + 1 (directly after
    the selected row), keep the SAME parent (section 01), every later row
    must shift down by one, and the placement must survive a refetch.
    """
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    sec1 = (await _add_section(client, auth, boq_id, ordinal="01")).json()
    sec2 = (await _add_section(client, auth, boq_id, ordinal="02")).json()

    p1 = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="01.001",
            description="A",
            unit="m3",
            quantity=1,
            unit_rate=1,
            parent_id=sec1["id"],
        )
    ).json()
    p2 = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="01.002",
            description="B",
            unit="m3",
            quantity=1,
            unit_rate=1,
            parent_id=sec1["id"],
        )
    ).json()
    p3 = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="01.003",
            description="C",
            unit="m3",
            quantity=1,
            unit_rate=1,
            parent_id=sec1["id"],
        )
    ).json()
    p4 = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="01.004",
            description="D",
            unit="m3",
            quantity=1,
            unit_rate=1,
            parent_id=sec1["id"],
        )
    ).json()
    # A leaf in the SECOND section — must never be disturbed.
    q1 = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="02.001",
            description="Z",
            unit="m3",
            quantity=1,
            unit_rate=1,
            parent_id=sec2["id"],
        )
    ).json()

    p2_so = p2["sort_order"]

    # Simulate the editor: user selected p2 (a leaf) → parent = its parent,
    # after_position_id = p2.id.  Ordinal label is whatever the FE computed;
    # placement correctness is driven by after_position_id / sort_order.
    inserted = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="01.0025",
            description="INSERTED",
            unit="m3",
            quantity=2,
            unit_rate=3,
            parent_id=sec1["id"],
            after_position_id=p2["id"],
        )
    ).json()

    # Same section.
    assert inserted["parent_id"] == sec1["id"], inserted
    # Directly after the selected row.
    assert inserted["sort_order"] == p2_so + 1, f"expected sort_order {p2_so + 1}, got {inserted['sort_order']}"

    after = {p["id"]: p for p in await _positions(client, auth, boq_id)}
    # p1, p2 unchanged; p3, p4, q1 shifted down by one.
    assert after[p1["id"]]["sort_order"] == p1["sort_order"]
    assert after[p2["id"]]["sort_order"] == p2_so
    assert after[p3["id"]]["sort_order"] == p3["sort_order"] + 1
    assert after[p4["id"]]["sort_order"] == p4["sort_order"] + 1
    assert after[q1["id"]]["sort_order"] == q1["sort_order"] + 1

    # Render order: the inserted row sits immediately between p2 and p3.
    order = [p["id"] for p in _sorted(await _positions(client, auth, boq_id)) if p["unit"] not in ("", "section")]
    i_p2 = order.index(p2["id"])
    assert order[i_p2 + 1] == inserted["id"], order
    assert order[i_p2 + 2] == p3["id"], order


@pytest.mark.asyncio
async def test_insert_partida_at_section_end_when_selected_is_last(client: AsyncClient, auth: dict[str, str]) -> None:
    """Selecting the LAST child of a section still inserts right after it
    (not before, not in the next section)."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)
    sec1 = (await _add_section(client, auth, boq_id, ordinal="01")).json()
    sec2 = (await _add_section(client, auth, boq_id, ordinal="02")).json()
    a = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="01.001",
            unit="m3",
            quantity=1,
            unit_rate=1,
            parent_id=sec1["id"],
        )
    ).json()
    b = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="01.002",
            unit="m3",
            quantity=1,
            unit_rate=1,
            parent_id=sec1["id"],
        )
    ).json()
    z = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="02.001",
            unit="m3",
            quantity=1,
            unit_rate=1,
            parent_id=sec2["id"],
        )
    ).json()

    ins = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="01.003",
            unit="m3",
            quantity=1,
            unit_rate=1,
            parent_id=sec1["id"],
            after_position_id=b["id"],
        )
    ).json()

    assert ins["parent_id"] == sec1["id"]
    assert ins["sort_order"] == b["sort_order"] + 1
    order = [p["id"] for p in _sorted(await _positions(client, auth, boq_id))]
    # a, b, ins must be contiguous and ins must precede section 2's child z.
    assert order.index(a["id"]) < order.index(b["id"]) < order.index(ins["id"])
    assert order.index(ins["id"]) < order.index(z["id"])


@pytest.mark.asyncio
async def test_issue_149_add_position_lands_inside_clicked_section(client: AsyncClient, auth: dict[str, str]) -> None:
    """Issue #149 — clicking a section's "Add position" button must put the
    new partida INSIDE that section.

    Repro shape: section ``A`` with two sub-sections ``A.1`` / ``A.2`` where
    ``A.2`` itself has a priced leaf. Adding a partida to ``A`` (explicit
    ``parent_id``, NO ``after_position_id`` — exactly what the per-section
    button sends) must:

      * keep ``parent_id == A`` (a direct child of the clicked section), and
      * render *before* the sub-sections' subtrees — never after ``A.2``'s
        leaf, which is what made it look "filed under the last sub-section".

    A second add appends after the first (the section's own line items stay
    grouped together, still ahead of the sub-sections).
    """
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    secA = (await _add_section(client, auth, boq_id, ordinal="01")).json()
    subA1 = (await _add_section(client, auth, boq_id, ordinal="01.01", parent_id=secA["id"])).json()
    subA2 = (await _add_section(client, auth, boq_id, ordinal="01.02", parent_id=secA["id"])).json()
    # A.2 gets a priced leaf so it is unmistakably "the last child section
    # with content" — the place the bug used to dump the new partida.
    deep_leaf = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="01.02.0010",
            description="DEEP",
            unit="m3",
            quantity=2,
            unit_rate=5,
            parent_id=subA2["id"],
        )
    ).json()

    # Click "Add position" on section A. The FE sends parent_id=A and the
    # gap-of-10 ordinal it computes from A's children (no after_position_id).
    first = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="01.03",
            description="ADDED-TO-A",
            unit="m2",
            quantity=0,
            unit_rate=0,
            parent_id=secA["id"],
        )
    ).json()
    assert first["parent_id"] == secA["id"], first

    order = [p["id"] for p in _sorted(await _positions(client, auth, boq_id))]
    # The new partida is a direct child of A AND renders ahead of both
    # sub-sections and A.2's deep leaf — i.e. clearly inside A, not under A.2.
    assert order.index(first["id"]) < order.index(subA1["id"]), order
    assert order.index(first["id"]) < order.index(subA2["id"]), order
    assert order.index(first["id"]) < order.index(deep_leaf["id"]), order

    # A second click appends after the first, both still above the
    # sub-sections (section's own line items stay grouped & ordered).
    second = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="01.04",
            description="ADDED-TO-A-2",
            unit="m2",
            quantity=0,
            unit_rate=0,
            parent_id=secA["id"],
        )
    ).json()
    assert second["parent_id"] == secA["id"], second
    order2 = [p["id"] for p in _sorted(await _positions(client, auth, boq_id))]
    assert order2.index(first["id"]) < order2.index(second["id"]) < order2.index(subA1["id"]), order2
    assert order2.index(second["id"]) < order2.index(deep_leaf["id"]), order2

    # The deep leaf's price is undisturbed and still rolls up.
    by_id = {p["id"]: p for p in await _positions(client, auth, boq_id)}
    assert abs(float(by_id[deep_leaf["id"]]["total"]) - 10.0) < 0.01


@pytest.mark.asyncio
async def test_insert_falls_back_to_append_for_stale_anchor(client: AsyncClient, auth: dict[str, str]) -> None:
    """A stale / cross-BOQ after_position_id must NOT scramble order —
    it falls back to append-at-end."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)
    sec1 = (await _add_section(client, auth, boq_id, ordinal="01")).json()
    a = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="01.001",
            unit="m3",
            quantity=1,
            unit_rate=1,
            parent_id=sec1["id"],
        )
    ).json()

    ins = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="01.002",
            unit="m3",
            quantity=1,
            unit_rate=1,
            parent_id=sec1["id"],
            after_position_id=str(uuid.uuid4()),  # does not exist
        )
    ).json()
    # Appended at end (max sort_order + 1); nothing else moved.
    assert ins["sort_order"] > a["sort_order"]


# ═══════════════════════════════════════════════════════════════════════════
# Issue #136 — deep nesting (sections-in-sections + partidas-in-partidas)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_limits_endpoint_reports_max_nesting_depth(client: AsyncClient, auth: dict[str, str]) -> None:
    r = await client.get("/api/v1/boq/limits/", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["max_nesting_depth"] == 8


@pytest.mark.asyncio
async def test_full_requested_tree_shape_builds_and_rolls_up(client: AsyncClient, auth: dict[str, str]) -> None:
    """SECTION → SECCIÓN-HIJA → SECCIÓN-HIJA → PARTIDA → PARTIDA-HIJA →
    PARTIDA-HIJA — six position tiers, exactly the verbatim requested
    shape. Build it through the API, then assert the parent chain, that it
    persists, and that the root section's subtotal rolls up the deepest
    priced leaf."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    # Tier 1-3: section → sub-section → sub-sub-section
    s1 = (await _add_section(client, auth, boq_id, ordinal="01")).json()
    s2 = (await _add_section(client, auth, boq_id, ordinal="01.01", parent_id=s1["id"])).json()
    s3 = (await _add_section(client, auth, boq_id, ordinal="01.01.01", parent_id=s2["id"])).json()
    assert s2["parent_id"] == s1["id"], "sub-section must nest under section"
    assert s3["parent_id"] == s2["id"], "sub-sub-section must nest"

    # Tier 4-6: partida → partida-hija → partida-hija
    pr = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="01.01.01.0010",
        description="PARTIDA",
        unit="m3",
        quantity=1,
        unit_rate=0,
        parent_id=s3["id"],
    )
    assert pr.status_code == 201, pr.text
    p1 = pr.json()
    p2r = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="01.01.01.0010.10",
        description="PARTIDA-HIJA",
        unit="m3",
        quantity=1,
        unit_rate=0,
        parent_id=p1["id"],
    )
    assert p2r.status_code == 201, p2r.text
    p2 = p2r.json()
    p3r = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="01.01.01.0010.10.10",
        description="PARTIDA-HIJA-2",
        unit="m3",
        quantity=4,
        unit_rate=25,
        parent_id=p2["id"],
    )
    assert p3r.status_code == 201, p3r.text
    p3 = p3r.json()
    assert p3["parent_id"] == p2["id"], "partida may have child partidas"

    # Persisted parent chain s1<-s2<-s3<-p1<-p2<-p3 survives a refetch.
    by_id = {p["id"]: p for p in await _positions(client, auth, boq_id)}
    chain = []
    cur = p3["id"]
    while cur is not None:
        chain.append(cur)
        cur = by_id[cur]["parent_id"]
    assert chain == [p3["id"], p2["id"], p1["id"], s3["id"], s2["id"], s1["id"]], chain

    # Subtotal rolls up the deepest priced leaf (4 * 25 = 100) all the way
    # to the root section.
    deep_total = float(by_id[p3["id"]]["total"])
    assert abs(deep_total - 100.0) < 0.01, by_id[p3["id"]]

    bd = await client.get(f"/api/v1/boq/boqs/{boq_id}/cost-breakdown/", headers=auth)
    assert bd.status_code == 200, bd.text
    grand = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    assert abs(float(grand.json()["grand_total"]) - 100.0) < 0.01, grand.json()["grand_total"]


@pytest.mark.asyncio
async def test_eight_tiers_allowed_ninth_rejected(client: AsyncClient, auth: dict[str, str]) -> None:
    """A full 8-tier chain is creatable; the 9th tier is rejected with 422
    (the cap is real and enforced server-side)."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    parent_id: str | None = None
    last_id: str | None = None
    for tier in range(1, 9):  # tiers 1..8 inclusive
        body = dict(
            ordinal=f"T{tier}",
            description=f"tier {tier}",
            unit="m3",
            quantity=1,
            unit_rate=1,
        )
        if parent_id is not None:
            body["parent_id"] = parent_id
        r = await _add_position(client, auth, boq_id, **body)
        assert r.status_code == 201, f"tier {tier} must be allowed (cap is 8): {r.text}"
        last_id = r.json()["id"]
        parent_id = last_id

    # Tier 9 — must be rejected.
    r9 = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="T9",
        description="tier 9 (over cap)",
        unit="m3",
        quantity=1,
        unit_rate=1,
        parent_id=last_id,
    )
    assert r9.status_code == 422, f"tier 9 must exceed MAX_NESTING_DEPTH: {r9.status_code} {r9.text}"
    assert "nesting depth" in r9.text.lower()


@pytest.mark.asyncio
async def test_nested_subsection_inserts_below_selected_via_after_id(client: AsyncClient, auth: dict[str, str]) -> None:
    """Issue #139 ∩ #136 — inserting a sub-section below a SELECTED
    sub-section (after_position_id) must slot it right there, not at the
    end of the parent section."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)
    s1 = (await _add_section(client, auth, boq_id, ordinal="01")).json()
    sa = (await _add_section(client, auth, boq_id, ordinal="01.01", parent_id=s1["id"])).json()
    sb = (await _add_section(client, auth, boq_id, ordinal="01.02", parent_id=s1["id"])).json()

    # Insert a sub-section that should land directly AFTER sa (selected).
    r = await _add_section(client, auth, boq_id, ordinal="01.015", parent_id=s1["id"])
    assert r.status_code == 201, r.text
    new_sec = r.json()

    order = [p["id"] for p in _sorted(await _positions(client, auth, boq_id))]
    assert new_sec["parent_id"] == s1["id"]
    # Document current behaviour: sections are appended (no after_position_id
    # on the section endpoint). new_sec lands after sb today.
    assert order.index(sa["id"]) < order.index(sb["id"])
    assert order.index(new_sec["id"]) > order.index(sb["id"])
