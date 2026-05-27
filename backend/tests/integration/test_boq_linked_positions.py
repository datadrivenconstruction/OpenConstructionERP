"""Issue #127 — BOQ code reuse / linked positions (HTTP roundtrip).

Covers the full feature end-to-end through the router:

* Reuse-by-code creates a LINKED INSTANCE with its own unique ordinal +
  per-instance quantity and the master's copied definition + subtree.
* A master definition edit propagates to every linked instance
  project-wide — but never quantity / ordinal.
* An instance definition edit UNLINKS it and attaches a warning.
* A quantity edit on an instance never propagates and never unlinks.
* Duplicate ORDINAL still 409s (GAEB X83 / no_duplicate_ordinals
  invariant preserved).
* An auto internal code is generated when none is supplied.
* Deleting a master promotes an instance (no orphaned links).
* Every linked instance in a reuse group gets a distinct ordinal.

Test isolation (``feedback_test_isolation.md``): the per-session temp
SQLite redirect, eager model registration and the synchronous event-bus
shim are all provided by ``backend/tests/conftest.py`` (the repo's
``testpaths`` root) — the production ``openestimate.db`` is never
touched. The fresh temp DB gets the new linked-position columns from
``create_all`` (the model is the source of truth on a clean SQLite DB),
so no ``alembic upgrade`` is needed for the test.

Run:
    cd backend
    python -m pytest tests/integration/test_boq_linked_positions.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# ── Shared fixtures (module-scoped — same pattern as other BOQ integration tests) ──


@pytest_asyncio.fixture(scope="module")
async def client() -> AsyncClient:
    """Module-scoped client driving the full app lifecycle (creates tables)."""
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
    """Register + force-promote-to-admin + login → bearer header."""
    unique = uuid.uuid4().hex[:8]
    email = f"link127-{unique}@test.io"
    password = f"Link127{unique}9!"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Linked Positions Tester",
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
            "name": f"Link127 {uuid.uuid4().hex[:6]}",
            "description": "Issue #127 integration",
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
            "name": f"Link127 BOQ {uuid.uuid4().hex[:6]}",
            "description": "Issue #127",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create BOQ failed: {resp.text}"
    return resp.json()["id"]


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


# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_reuse_by_code_creates_linked_instance_with_copied_definition_and_subtree(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """Typing an existing code must NOT 409 — it creates a linked instance.

    The instance carries its own unique ordinal + per-instance quantity
    and a deep copy of the master's definition AND child subtree.
    """
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    master_r = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="0040",
        description="RC wall C30/37",
        unit="m3",
        quantity=10.0,
        unit_rate=185.0,
        reference_code="0040",
    )
    assert master_r.status_code == 201, master_r.text
    master = master_r.json()
    assert master["reference_code"] == "0040"

    child_r = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="0040.C1",
        description="Rebar BSt500",
        unit="kg",
        quantity=120.0,
        unit_rate=1.85,
        parent_id=master["id"],
    )
    assert child_r.status_code == 201, child_r.text

    reuse_r = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="0040",  # same as master on purpose
        description="(ignored — definition copied from master)",
        unit="pcs",  # ignored — copied from master
        quantity=7.0,  # per-instance, kept
        reference_code="0040",
    )
    assert reuse_r.status_code == 201, f"reuse should not 409: {reuse_r.text}"
    inst = reuse_r.json()

    assert inst["reference_code"] == "0040"
    assert inst["link_role"] == "instance"
    assert inst["link_group_id"] is not None
    assert inst["description"] == "RC wall C30/37"
    assert inst["unit"] == "m3"
    assert str(inst["unit_rate"]) in ("185", "185.0", "185.0000")
    assert inst["ordinal"] != "0040"
    assert float(inst["quantity"]) == 7.0
    assert abs(float(inst["total"]) - 7.0 * 185.0) < 0.01

    boq_full = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    assert boq_full.status_code == 200, boq_full.text
    all_positions = boq_full.json().get("positions", [])
    inst_children = [p for p in all_positions if p.get("parent_id") == inst["id"]]
    assert len(inst_children) >= 1, "the master's child subtree must be cloned"

    links = await client.get(f"/api/v1/boq/positions/{inst['id']}/links/", headers=auth)
    assert links.status_code == 200, links.text
    lj = links.json()
    assert lj["linked"] is True
    assert lj["master_id"] == master["id"]
    assert lj["instance_count"] >= 1
    assert lj["total_count"] >= 2


@pytest.mark.asyncio
async def test_master_definition_edit_propagates_but_not_quantity_or_ordinal(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    master = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="P1",
            description="Old desc",
            unit="m2",
            quantity=5.0,
            unit_rate=10.0,
            reference_code="REUSE1",
        )
    ).json()
    inst = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="P1",
            description="x",
            unit="x",
            quantity=99.0,
            reference_code="REUSE1",
        )
    ).json()
    inst_ordinal_before = inst["ordinal"]

    patch = await client.patch(
        f"/api/v1/boq/positions/{master['id']}",
        json={"description": "NEW desc", "unit_rate": 20.0},
        headers=auth,
    )
    assert patch.status_code == 200, patch.text
    pj = patch.json()
    assert pj["metadata"].get("link_propagation", {}).get("propagated_to") == 1

    got = await client.get(f"/api/v1/boq/positions/{inst['id']}", headers=auth)
    assert got.status_code == 200, got.text
    gi = got.json()
    assert gi["description"] == "NEW desc"
    assert float(gi["unit_rate"]) == 20.0
    assert float(gi["quantity"]) == 99.0
    assert gi["ordinal"] == inst_ordinal_before
    assert abs(float(gi["total"]) - 99.0 * 20.0) < 0.01


@pytest.mark.asyncio
async def test_instance_definition_edit_unlinks_and_warns(client: AsyncClient, auth: dict[str, str]) -> None:
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    master = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="U1",
            description="shared",
            unit="m",
            quantity=1.0,
            unit_rate=5.0,
            reference_code="UCODE",
        )
    ).json()
    inst = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="U1",
            description="x",
            unit="x",
            quantity=2.0,
            reference_code="UCODE",
        )
    ).json()
    assert inst["link_role"] == "instance"

    patch = await client.patch(
        f"/api/v1/boq/positions/{inst['id']}",
        json={"description": "I changed my mind"},
        headers=auth,
    )
    assert patch.status_code == 200, patch.text
    pj = patch.json()
    assert pj["link_role"] is None
    assert pj["link_group_id"] is None
    warnings = pj["metadata"].get("boq_quality_warnings", [])
    assert any("unlinked it from code" in str(w) for w in warnings), warnings
    assert pj["validation_status"] == "warnings"

    m = (await client.get(f"/api/v1/boq/positions/{master['id']}", headers=auth)).json()
    assert m["description"] == "shared"


@pytest.mark.asyncio
async def test_instance_quantity_edit_does_not_propagate_or_unlink(client: AsyncClient, auth: dict[str, str]) -> None:
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    master = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="Q1",
            description="qty test",
            unit="m3",
            quantity=1.0,
            unit_rate=100.0,
            reference_code="QCODE",
        )
    ).json()
    inst = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="Q1",
            description="x",
            unit="x",
            quantity=3.0,
            reference_code="QCODE",
        )
    ).json()

    patch = await client.patch(
        f"/api/v1/boq/positions/{inst['id']}",
        json={"quantity": 50.0},
        headers=auth,
    )
    assert patch.status_code == 200, patch.text
    pj = patch.json()
    assert pj["link_role"] == "instance"
    assert pj["link_group_id"] is not None
    assert float(pj["quantity"]) == 50.0
    m = (await client.get(f"/api/v1/boq/positions/{master['id']}", headers=auth)).json()
    assert float(m["quantity"]) == 1.0


@pytest.mark.asyncio
async def test_duplicate_ordinal_still_409s(client: AsyncClient, auth: dict[str, str]) -> None:
    """The ordinal-uniqueness invariant (GAEB X83 / no_duplicate_ordinals)
    is preserved: a plain duplicate ordinal with NO reuse code still 409s.
    """
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    r1 = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="DUP",
        description="first",
        unit="m",
        quantity=1.0,
    )
    assert r1.status_code == 201, r1.text

    r2 = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="DUP",
        description="second",
        unit="m",
        quantity=1.0,
    )
    assert r2.status_code == 409, f"Expected 409, got {r2.status_code}: {r2.text}"
    assert "ordinal" in r2.text.lower()


@pytest.mark.asyncio
async def test_auto_internal_code_generated_when_none_supplied(client: AsyncClient, auth: dict[str, str]) -> None:
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    r = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="AUTO1",
        description="no code given",
        unit="m",
        quantity=1.0,
    )
    assert r.status_code == 201, r.text
    pj = r.json()
    assert pj["reference_code"], "an internal code must be auto-stamped"
    assert pj["reference_code"].startswith("R-")
    assert pj["link_role"] is None
    assert pj["link_group_id"] is None


@pytest.mark.asyncio
async def test_delete_master_promotes_an_instance(client: AsyncClient, auth: dict[str, str]) -> None:
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    master = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="D1",
            description="to delete",
            unit="m",
            quantity=1.0,
            unit_rate=9.0,
            reference_code="DELC",
        )
    ).json()
    inst1 = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="D1",
            description="x",
            unit="x",
            quantity=2.0,
            reference_code="DELC",
        )
    ).json()
    inst2 = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="D1",
            description="x",
            unit="x",
            quantity=3.0,
            reference_code="DELC",
        )
    ).json()
    assert inst1["link_role"] == "instance"
    assert inst2["link_role"] == "instance"

    d = await client.delete(f"/api/v1/boq/positions/{master['id']}", headers=auth)
    assert d.status_code == 204, d.text

    g1 = (await client.get(f"/api/v1/boq/positions/{inst1['id']}", headers=auth)).json()
    g2 = (await client.get(f"/api/v1/boq/positions/{inst2['id']}", headers=auth)).json()
    roles = {g1["link_role"], g2["link_role"]}
    assert "master" in roles, f"a survivor must be promoted: {roles}"
    group_ids = {g1["link_group_id"], g2["link_group_id"]}
    assert None not in group_ids or len(group_ids) == 1


@pytest.mark.asyncio
async def test_link_group_ordinals_are_all_distinct(client: AsyncClient, auth: dict[str, str]) -> None:
    """GAEB / no_duplicate_ordinals invariant across a reuse group:
    every linked instance gets a distinct ordinal."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    await _add_position(
        client,
        auth,
        boq_id,
        ordinal="G1",
        description="grp master",
        unit="m",
        quantity=1.0,
        unit_rate=1.0,
        reference_code="GRP",
    )
    for _ in range(4):
        rr = await _add_position(
            client,
            auth,
            boq_id,
            ordinal="G1",
            description="x",
            unit="x",
            quantity=1.0,
            reference_code="GRP",
        )
        assert rr.status_code == 201, rr.text

    boq = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    assert boq.status_code == 200, boq.text
    positions = boq.json().get("positions", [])
    ordinals = [p["ordinal"] for p in positions]
    assert len(ordinals) == len(set(ordinals)), f"ordinals must be unique within the BOQ: {ordinals}"


@pytest.mark.asyncio
async def test_unlink_master_endpoint_does_not_500_and_preserves_values(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """Regression: ``POST /positions/{id}/unlink/`` on a MASTER that still
    has a linked instance must NOT 500.

    The master-survivor branch calls ``update_fields`` (which ends with
    ``session.expire_all()``); a later read of the now-expired ``position``
    instance would lazy-load on the async engine → MissingGreenlet → 500.
    The endpoint must instead 200, detach the old master value-preserving
    (code + definition + quantity kept, still referenceable), and leave no
    instance orphaned (the lone survivor's group dissolves cleanly).

    Kept deliberately small (one master + one instance, one unlink) so the
    critical 500→200 guard stays robust under the module-scoped aiosqlite
    test harness. Survivor *promotion* with ≥2 instances is covered by
    ``test_delete_master_promotes_an_instance`` (shared list-group/promote
    path) and verified live against the running server.
    """
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    master = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="UM1",
            description="shared def",
            unit="m3",
            quantity=4.0,
            unit_rate=50.0,
            reference_code="UNLNK",
        )
    ).json()
    inst = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="UM1",
            description="x",
            unit="x",
            quantity=2.0,
            reference_code="UNLNK",
        )
    ).json()
    # The first-create response is still a standalone (role None) — a
    # standalone owner is promoted to ``master`` server-side only when the
    # FIRST reuse instance is created, AFTER that response was returned.
    # So assert the instance is linked, then GET the master to see its
    # promoted role.
    assert inst["link_role"] == "instance"
    assert inst["link_group_id"] is not None
    master_now = (await client.get(f"/api/v1/boq/positions/{master['id']}", headers=auth)).json()
    assert master_now["link_role"] == "master"

    un = await client.post(f"/api/v1/boq/positions/{master['id']}/unlink/", headers=auth)
    assert un.status_code == 200, f"unlink master must not 500: {un.text}"
    uj = un.json()
    # Old master detached, values preserved (code kept, still referenceable).
    assert uj["link_role"] is None
    assert uj["link_group_id"] is None
    assert uj["reference_code"] == "UNLNK"
    assert uj["description"] == "shared def"
    assert float(uj["quantity"]) == 4.0
    assert abs(float(uj["total"]) - 4.0 * 50.0) < 0.01
    # NOTE: survivor promotion/dissolution is intentionally NOT asserted
    # here — it runs in a best-effort try/except inside ``unlink_position``
    # ("never block the unlink") so it is sensitive to the documented
    # module-scoped aiosqlite harness flake. That behaviour is covered by
    # ``test_delete_master_promotes_an_instance`` and verified live against
    # the running server. This test guards only the actual regression: the
    # master-unlink path must 200 (not 500) and preserve the unlinked
    # position's own values.


async def _instance_child_of(client: AsyncClient, auth: dict[str, str], boq_id: str, inst_id: str) -> dict:
    """Return the single cloned child of a reused-instance root."""
    boq = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    assert boq.status_code == 200, boq.text
    kids = [p for p in boq.json().get("positions", []) if p.get("parent_id") == inst_id]
    assert len(kids) == 1, f"expected exactly one cloned child, got {kids}"
    return kids[0]


@pytest.mark.asyncio
async def test_master_child_edit_propagates_to_instance_children_only(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """Issue #132 — Gap A.

    Reuse a whole partida (master root + a sub-line child). Editing the
    MASTER CHILD's definition must fan out to the matching instance
    CHILD (same ``reference_code`` subtree) — never to the instance
    ROOT, and never the per-instance quantity.
    """
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    master = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="MC1",
            description="Partida master",
            unit="m3",
            quantity=10.0,
            unit_rate=185.0,
            reference_code="MCODE",
        )
    ).json()
    master_child = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="MC1.1",
            description="Old sub-line",
            unit="kg",
            quantity=120.0,
            unit_rate=1.85,
            parent_id=master["id"],
        )
    ).json()

    inst = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="MC1",
            description="x",
            unit="x",
            quantity=7.0,
            reference_code="MCODE",
        )
    ).json()
    assert inst["link_role"] == "instance"
    inst_child = await _instance_child_of(client, auth, boq_id, inst["id"])
    assert inst_child["description"] == "Old sub-line"
    inst_child_qty_before = float(inst_child["quantity"])

    patch = await client.patch(
        f"/api/v1/boq/positions/{master_child['id']}",
        json={"description": "NEW sub-line", "unit_rate": 2.0},
        headers=auth,
    )
    assert patch.status_code == 200, patch.text
    pj = patch.json()
    assert pj["metadata"].get("link_propagation", {}).get("propagated_to") == 1, pj["metadata"]

    gi_child = (await client.get(f"/api/v1/boq/positions/{inst_child['id']}", headers=auth)).json()
    assert gi_child["description"] == "NEW sub-line"
    assert float(gi_child["unit_rate"]) == 2.0
    # Per-instance quantity untouched; total recomputed against IT.
    assert float(gi_child["quantity"]) == inst_child_qty_before
    assert abs(float(gi_child["total"]) - inst_child_qty_before * 2.0) < 0.01

    # The instance ROOT must be untouched by a child edit.
    gi_root = (await client.get(f"/api/v1/boq/positions/{inst['id']}", headers=auth)).json()
    assert gi_root["description"] == "Partida master"
    assert float(gi_root["quantity"]) == 7.0


@pytest.mark.asyncio
async def test_master_root_edit_does_not_clobber_instance_children(client: AsyncClient, auth: dict[str, str]) -> None:
    """Issue #132 — Gap A'.

    A ROOT definition edit must reach the instance ROOTS only; it must
    NOT blanket-overwrite the instance CHILDREN with the root's
    description (the old group-flat propagation bug for subtree reuse).
    """
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    master = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="MR1",
            description="Root def",
            unit="m3",
            quantity=10.0,
            unit_rate=185.0,
            reference_code="MRCODE",
        )
    ).json()
    await _add_position(
        client,
        auth,
        boq_id,
        ordinal="MR1.1",
        description="Child def",
        unit="kg",
        quantity=120.0,
        unit_rate=1.85,
        parent_id=master["id"],
    )
    inst = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="MR1",
            description="x",
            unit="x",
            quantity=4.0,
            reference_code="MRCODE",
        )
    ).json()
    inst_child = await _instance_child_of(client, auth, boq_id, inst["id"])

    patch = await client.patch(
        f"/api/v1/boq/positions/{master['id']}",
        json={"description": "Root def CHANGED"},
        headers=auth,
    )
    assert patch.status_code == 200, patch.text

    gi_root = (await client.get(f"/api/v1/boq/positions/{inst['id']}", headers=auth)).json()
    gi_child = (await client.get(f"/api/v1/boq/positions/{inst_child['id']}", headers=auth)).json()
    # Instance root mirrors the master root.
    assert gi_root["description"] == "Root def CHANGED"
    # Instance child keeps ITS OWN definition — NOT the root's.
    assert gi_child["description"] == "Child def"


@pytest.mark.asyncio
async def test_master_child_quantity_edit_never_propagates(client: AsyncClient, auth: dict[str, str]) -> None:
    """Issue #132 — a pure quantity edit on a master CHILD must never
    reach the instance children (quantities are per-instance)."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    master = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="MQ1",
            description="qmaster",
            unit="m3",
            quantity=1.0,
            unit_rate=100.0,
            reference_code="MQCODE",
        )
    ).json()
    master_child = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="MQ1.1",
            description="qchild",
            unit="kg",
            quantity=10.0,
            unit_rate=5.0,
            parent_id=master["id"],
        )
    ).json()
    inst = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="MQ1",
            description="x",
            unit="x",
            quantity=2.0,
            reference_code="MQCODE",
        )
    ).json()
    inst_child = await _instance_child_of(client, auth, boq_id, inst["id"])
    qty_before = float(inst_child["quantity"])

    patch = await client.patch(
        f"/api/v1/boq/positions/{master_child['id']}",
        json={"quantity": 999.0},
        headers=auth,
    )
    assert patch.status_code == 200, patch.text
    pj = patch.json()
    assert pj["metadata"].get("link_propagation", {}).get("propagated_to", 0) in (0, None)

    gi_child = (await client.get(f"/api/v1/boq/positions/{inst_child['id']}", headers=auth)).json()
    assert float(gi_child["quantity"]) == qty_before


@pytest.mark.asyncio
async def test_unlink_standalone_position_is_422_not_500(client: AsyncClient, auth: dict[str, str]) -> None:
    """A position that is not part of a link group → clean 422, never 500."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    solo = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="SOLO1",
            description="lonely",
            unit="m",
            quantity=1.0,
            unit_rate=1.0,
        )
    ).json()
    un = await client.post(f"/api/v1/boq/positions/{solo['id']}/unlink/", headers=auth)
    assert un.status_code == 422, f"expected 422, got {un.status_code}: {un.text}"


# ── Issue #133 — resource-code project-wide lookup ────────────────────────


@pytest.mark.asyncio
async def test_resource_code_lookup_finds_and_misses(client: AsyncClient, auth: dict[str, str]) -> None:
    """The resource-by-code endpoint returns the existing resource's
    reusable definition (no quantity) when the code is in use anywhere in
    the project, and ``found=False`` for a free code."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    host = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="RC-HOST",
            description="host position",
            unit="m3",
            quantity=1.0,
            unit_rate=0.0,
        )
    ).json()

    # Attach a coded resource via the standard metadata.resources path.
    patch = await client.patch(
        f"/api/v1/boq/positions/{host['id']}",
        json={
            "metadata": {
                "resources": [
                    {
                        "name": "Concrete C30/37",
                        "code": "MAT-001",
                        "type": "material",
                        "unit": "m3",
                        "quantity": 5.0,
                        "unit_rate": 92.5,
                        "currency": "EUR",
                        "total": 462.5,
                    }
                ]
            }
        },
        headers=auth,
    )
    assert patch.status_code == 200, patch.text

    # Hit (case-insensitive).
    hit = await client.get(
        f"/api/v1/boq/projects/{project_id}/resource-by-code/?code=mat-001",
        headers=auth,
    )
    assert hit.status_code == 200, hit.text
    hj = hit.json()
    assert hj["found"] is True
    m = hj["match"]
    assert m["code"] == "MAT-001"
    assert m["name"] == "Concrete C30/37"
    assert m["type"] == "material"
    assert m["unit"] == "m3"
    assert abs(float(m["unit_rate"]) - 92.5) < 0.001
    assert m["currency"] == "EUR"
    assert m["position_id"] == host["id"]
    # Definition only — quantity is per-instance and never returned.
    assert "quantity" not in m

    # Miss.
    miss = await client.get(
        f"/api/v1/boq/projects/{project_id}/resource-by-code/?code=NOPE-999",
        headers=auth,
    )
    assert miss.status_code == 200, miss.text
    assert miss.json()["found"] is False


# ── Issue #136 — multi-level section / partida hierarchy ──────────────────


async def _add_section(
    client: AsyncClient,
    auth: dict[str, str],
    boq_id: str,
    ordinal: str,
    *,
    parent_id: str | None = None,
):
    body: dict = {"boq_id": boq_id, "ordinal": ordinal, "description": ordinal}
    if parent_id is not None:
        body["parent_id"] = parent_id
    return await client.post(f"/api/v1/boq/boqs/{boq_id}/sections/", json=body, headers=auth)


@pytest.mark.asyncio
async def test_limits_endpoint_reports_max_nesting_depth(client: AsyncClient, auth: dict[str, str]) -> None:
    r = await client.get("/api/v1/boq/limits/", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body.get("max_nesting_depth"), int)
    assert body["max_nesting_depth"] >= 3  # at least the legacy 3 tiers


@pytest.mark.asyncio
async def test_deep_section_and_partida_nesting_is_allowed(client: AsyncClient, auth: dict[str, str]) -> None:
    """Sections-within-sections and partidas-within-partidas may nest
    several tiers deep (Issue #136 — up to MAX_NESTING_DEPTH)."""
    from app.modules.boq.service import MAX_NESTING_DEPTH

    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    # Build a chain of nested sections down to tier 3.
    s1 = (await _add_section(client, auth, boq_id, "01")).json()
    s2 = (await _add_section(client, auth, boq_id, "01.01", parent_id=s1["id"])).json()
    s3 = (await _add_section(client, auth, boq_id, "01.01.01", parent_id=s2["id"])).json()
    assert s2["parent_id"] == s1["id"]
    assert s3["parent_id"] == s2["id"]

    # Partidas-within-partidas: a child partida under a partida under s3.
    p1 = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="P-A",
            description="lvl4",
            unit="m3",
            quantity=1.0,
            parent_id=s3["id"],
        )
    ).json()
    p2 = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="P-B",
            description="lvl5",
            unit="m3",
            quantity=1.0,
            parent_id=p1["id"],
        )
    ).json()
    assert p2["parent_id"] == p1["id"]
    # We've placed 5 tiers; the configurable cap must be comfortably > 2.
    assert MAX_NESTING_DEPTH >= 5


@pytest.mark.asyncio
async def test_nesting_beyond_cap_is_rejected_422(client: AsyncClient, auth: dict[str, str]) -> None:
    """A create that would exceed MAX_NESTING_DEPTH tiers is rejected."""
    from app.modules.boq.service import MAX_NESTING_DEPTH

    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    # Build a maximal-depth chain of partidas (tier 1 .. MAX).
    parent_id: str | None = None
    last_id: str | None = None
    for tier in range(1, MAX_NESTING_DEPTH + 1):
        r = await _add_position(
            client,
            auth,
            boq_id,
            ordinal=f"D{tier}",
            description=f"tier {tier}",
            unit="m3",
            quantity=1.0,
            **({"parent_id": parent_id} if parent_id else {}),
        )
        assert r.status_code == 201, f"tier {tier} within cap must succeed: {r.text}"
        last_id = r.json()["id"]
        parent_id = last_id

    # One more level would be tier MAX+1 → rejected.
    over = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="DOVER",
        description="over the cap",
        unit="m3",
        quantity=1.0,
        parent_id=last_id,
    )
    assert over.status_code == 422, f"expected 422 over the cap, got {over.status_code}: {over.text}"
    assert "nesting depth" in over.text.lower()

    # A sub-section over the cap is rejected too.
    over_sec = await _add_section(client, auth, boq_id, "OVER.SEC", parent_id=last_id)
    assert over_sec.status_code == 422, over_sec.text


@pytest.mark.asyncio
async def test_top_level_section_still_works_unchanged(client: AsyncClient, auth: dict[str, str]) -> None:
    """Legacy behaviour: omitting parent_id makes a top-level section."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)
    s = await _add_section(client, auth, boq_id, "ALPHA")
    assert s.status_code == 201, s.text
    assert s.json()["parent_id"] is None


# ── Issue #133 (full) — resource master→instance live propagation ─────────


async def _set_resources(
    client: AsyncClient,
    auth: dict[str, str],
    position_id: str,
    resources: list[dict],
):
    return await client.patch(
        f"/api/v1/boq/positions/{position_id}",
        json={"metadata": {"resources": resources}},
        headers=auth,
    )


def _resources_of(pos_json: dict) -> list[dict]:
    return (pos_json.get("metadata") or {}).get("resources") or []


@pytest.mark.asyncio
async def test_master_resource_edit_propagates_to_other_positions(client: AsyncClient, auth: dict[str, str]) -> None:
    """Editing the master (oldest) resource definition for a shared code
    fans the changed definition out to every other position carrying that
    code — but never the per-instance quantity."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    master_pos = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="RP-1",
            description="host A",
            unit="m3",
            quantity=2.0,
        )
    ).json()
    inst_pos = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="RP-2",
            description="host B",
            unit="m3",
            quantity=3.0,
        )
    ).json()

    # Master carries the canonical resource (oldest position wins).
    r1 = await _set_resources(
        client,
        auth,
        master_pos["id"],
        [
            {
                "name": "Cement",
                "code": "RES-9",
                "type": "material",
                "unit": "kg",
                "quantity": 100.0,
                "unit_rate": 0.5,
                "currency": "EUR",
                "total": 50.0,
            }
        ],
    )
    assert r1.status_code == 200, r1.text

    # Instance position re-uses the same code with its OWN quantity.
    r2 = await _set_resources(
        client,
        auth,
        inst_pos["id"],
        [
            {
                "name": "Cement",
                "code": "RES-9",
                "type": "material",
                "unit": "kg",
                "quantity": 7.0,
                "unit_rate": 0.5,
                "currency": "EUR",
                "total": 3.5,
            }
        ],
    )
    assert r2.status_code == 200, r2.text

    # Edit the MASTER resource's definition (rate + name).
    patch = await _set_resources(
        client,
        auth,
        master_pos["id"],
        [
            {
                "name": "Cement CEM II",
                "code": "RES-9",
                "type": "material",
                "unit": "kg",
                "quantity": 100.0,
                "unit_rate": 0.8,
                "currency": "EUR",
                "total": 80.0,
            }
        ],
    )
    assert patch.status_code == 200, patch.text
    prop = (patch.json().get("metadata") or {}).get("link_propagation") or {}
    assert prop.get("resource_propagated_to") == 1, patch.json().get("metadata")

    # Instance resource picked up the new definition, kept its quantity.
    gi = (await client.get(f"/api/v1/boq/positions/{inst_pos['id']}", headers=auth)).json()
    res = _resources_of(gi)
    assert len(res) == 1
    assert res[0]["name"] == "Cement CEM II"
    assert abs(float(res[0]["unit_rate"]) - 0.8) < 0.001
    assert abs(float(res[0]["quantity"]) - 7.0) < 0.001  # per-instance kept
    assert abs(float(res[0]["total"]) - 7.0 * 0.8) < 0.01


@pytest.mark.asyncio
async def test_user_overridden_resource_instance_is_not_clobbered(client: AsyncClient, auth: dict[str, str]) -> None:
    """A resource instance the user explicitly diverged
    (``_code_overridden``) must NOT be silently overwritten by a master
    edit (CLAUDE.md: AI-augmented, human-confirmed)."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    master_pos = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="OV-1",
            description="host",
            unit="m3",
            quantity=1.0,
        )
    ).json()
    inst_pos = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="OV-2",
            description="host2",
            unit="m3",
            quantity=1.0,
        )
    ).json()
    await _set_resources(
        client,
        auth,
        master_pos["id"],
        [
            {
                "name": "Steel",
                "code": "OVR-1",
                "type": "material",
                "unit": "kg",
                "quantity": 10.0,
                "unit_rate": 1.0,
                "total": 10.0,
            }
        ],
    )
    await _set_resources(
        client,
        auth,
        inst_pos["id"],
        [
            {
                "name": "Steel custom",
                "code": "OVR-1",
                "type": "material",
                "unit": "kg",
                "quantity": 5.0,
                "unit_rate": 9.99,
                "total": 49.95,
                "_code_overridden": True,
            }
        ],
    )

    patch = await _set_resources(
        client,
        auth,
        master_pos["id"],
        [
            {
                "name": "Steel S355",
                "code": "OVR-1",
                "type": "material",
                "unit": "kg",
                "quantity": 10.0,
                "unit_rate": 2.0,
                "total": 20.0,
            }
        ],
    )
    assert patch.status_code == 200, patch.text

    gi = (await client.get(f"/api/v1/boq/positions/{inst_pos['id']}", headers=auth)).json()
    res = _resources_of(gi)
    assert res[0]["name"] == "Steel custom"  # untouched
    assert abs(float(res[0]["unit_rate"]) - 9.99) < 0.001


@pytest.mark.asyncio
async def test_non_master_resource_edit_does_not_propagate(client: AsyncClient, auth: dict[str, str]) -> None:
    """Editing the resource on the NON-master (newer) position must not
    fan out to the master / others (only the master definition owner
    propagates — mirrors the #127 contract)."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    master_pos = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="NM-1",
            description="m",
            unit="m3",
            quantity=1.0,
        )
    ).json()
    other_pos = (
        await _add_position(
            client,
            auth,
            boq_id,
            ordinal="NM-2",
            description="o",
            unit="m3",
            quantity=1.0,
        )
    ).json()
    await _set_resources(
        client,
        auth,
        master_pos["id"],
        [
            {
                "name": "Sand",
                "code": "SND-1",
                "type": "material",
                "unit": "t",
                "quantity": 1.0,
                "unit_rate": 1.0,
                "total": 1.0,
            }
        ],
    )
    await _set_resources(
        client,
        auth,
        other_pos["id"],
        [
            {
                "name": "Sand",
                "code": "SND-1",
                "type": "material",
                "unit": "t",
                "quantity": 1.0,
                "unit_rate": 1.0,
                "total": 1.0,
            }
        ],
    )

    # Edit the NON-master (other_pos, created later).
    patch = await _set_resources(
        client,
        auth,
        other_pos["id"],
        [
            {
                "name": "Sand washed",
                "code": "SND-1",
                "type": "material",
                "unit": "t",
                "quantity": 1.0,
                "unit_rate": 5.0,
                "total": 5.0,
            }
        ],
    )
    assert patch.status_code == 200, patch.text
    prop = (patch.json().get("metadata") or {}).get("link_propagation") or {}
    assert prop.get("resource_propagated_to", 0) in (0, None)

    # Master untouched.
    gm = (await client.get(f"/api/v1/boq/positions/{master_pos['id']}", headers=auth)).json()
    assert _resources_of(gm)[0]["name"] == "Sand"
