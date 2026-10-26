# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate branches through the HTTP API.

* An editor may fork, compare, preview and cherry-pick between branches, but
  writing into the main estimate (merge, or a cherry-pick whose target is main)
  needs ``boq.branch_merge``, which a manager has.
* The merge needs an explicit confirmation.
* The tree, the compare and both export formats answer.
* Another tenant reads 404 on every branch route.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


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


async def _register(client: AsyncClient, *, role: str) -> tuple[dict[str, str], str]:
    unique = uuid.uuid4().hex[:8]
    email = f"branch-{unique}@test.io"
    password = f"Br{unique}9!x"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Branch {role}"},
    )
    assert reg.status_code == 201, reg.text

    from sqlalchemy import select
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(is_active=True, role=role))
        await session.commit()
        user_id = (await session.execute(select(User.id).where(User.email == email.lower()))).scalar_one()

    token = ""
    data: dict = {}
    for attempt in range(3):
        resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in str(data.get("detail", "")):
            await asyncio.sleep(2 * (attempt + 1))
            continue
        break
    assert token, f"Login failed: {data}"
    return {"Authorization": f"Bearer {token}"}, str(user_id)


async def _setup(client: AsyncClient, auth: dict[str, str]) -> tuple[str, str, dict[str, str]]:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": f"Branch {uuid.uuid4().hex[:6]}", "description": "", "currency": "EUR"},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["id"]
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": "Main", "description": ""},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    boq_id = resp.json()["id"]
    ids: dict[str, str] = {}
    for ordinal, desc, qty, rate in (("1", "Slab", 100, 120), ("2", "Walls", 40, 200)):
        resp = await client.post(
            f"/api/v1/boq/boqs/{boq_id}/positions/",
            json={
                "boq_id": boq_id,
                "ordinal": ordinal,
                "description": desc,
                "unit": "m3",
                "quantity": qty,
                "unit_rate": rate,
            },
            headers=auth,
        )
        assert resp.status_code == 201, resp.text
        ids[ordinal] = resp.json()["id"]
    return project_id, boq_id, ids


async def _positions(client: AsyncClient, auth: dict[str, str], boq_id: str) -> dict[str, dict]:
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    return {p["ordinal"]: p for p in resp.json()["positions"]}


@pytest.mark.asyncio
async def test_branch_lifecycle_and_merge_permission(client: AsyncClient) -> None:
    editor, _ = await _register(client, role="editor")
    manager, manager_id = await _register(client, role="manager")
    project_id, main_id, _ = await _setup(client, editor)

    resp = await client.post(f"/api/v1/boq/boqs/{main_id}/branches/", json={"name": "Precast"}, headers=editor)
    assert resp.status_code == 201, resp.text
    branch = resp.json()
    assert branch["branch_of_id"] == main_id

    listing = await client.get(f"/api/v1/boq/boqs/?project_id={project_id}", headers=editor)
    assert listing.status_code == 200, listing.text
    body = listing.json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    assert [b["id"] for b in items] == [main_id], "a branch is not a bill of the project register"

    lines = await _positions(client, editor, branch["id"])
    resp = await client.patch(
        f"/api/v1/boq/positions/{lines['1']['id']}",
        json={"unit_rate": 100},
        headers=editor,
    )
    assert resp.status_code == 200, resp.text

    tree = await client.get(f"/api/v1/boq/boqs/{branch['id']}/branches/", headers=editor)
    assert tree.status_code == 200, tree.text
    assert tree.json()["can_merge"] is False
    nodes = {n["boq_id"]: n for n in tree.json()["nodes"]}
    assert float(nodes[branch["id"]]["delta_vs_parent"]) == -2000.0

    compare = await client.get(f"/api/v1/boq/boqs/{main_id}/branches/compare/{branch['id']}", headers=editor)
    assert compare.status_code == 200, compare.text
    assert compare.json()["summary"]["changed"] == 1
    for fmt, magic in (("xlsx", b"PK"), ("pdf", b"%PDF")):
        exp = await client.get(
            f"/api/v1/boq/boqs/{main_id}/branches/compare/{branch['id']}/export?format={fmt}&view=sections",
            headers=editor,
        )
        assert exp.status_code == 200, exp.text
        assert exp.content[:4].startswith(magic)
        assert "attachment" in exp.headers["content-disposition"]

    plan = await client.post(
        f"/api/v1/boq/boqs/{main_id}/branches/plan/", json={"source_boq_id": branch["id"]}, headers=editor
    )
    assert plan.status_code == 200, plan.text
    assert len(plan.json()["items"]) == 1

    pick = await client.post(
        f"/api/v1/boq/boqs/{main_id}/branches/cherry-pick/", json={"source_boq_id": branch["id"]}, headers=editor
    )
    assert pick.status_code == 403, pick.text
    merge = await client.post(f"/api/v1/boq/boqs/{branch['id']}/branch/merge/", json={"confirm": True}, headers=editor)
    assert merge.status_code == 403, merge.text

    # The manager needs project access: make them a member through the owner's project.
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    async with async_session_factory() as session:
        project = await session.get(Project, uuid.UUID(project_id))
        project.owner_id = uuid.UUID(manager_id)
        await session.commit()

    unconfirmed = await client.post(f"/api/v1/boq/boqs/{branch['id']}/branch/merge/", json={}, headers=manager)
    assert unconfirmed.status_code == 400, unconfirmed.text
    merged = await client.post(
        f"/api/v1/boq/boqs/{branch['id']}/branch/merge/", json={"confirm": True}, headers=manager
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["status"] == "merged" and merged.json()["updated"] == 1
    main_lines = await _positions(client, manager, main_id)
    assert float(main_lines["1"]["unit_rate"]) == 100.0


@pytest.mark.asyncio
async def test_branch_routes_are_tenant_scoped(client: AsyncClient) -> None:
    owner, _ = await _register(client, role="editor")
    stranger, _ = await _register(client, role="editor")
    _, main_id, _ = await _setup(client, owner)
    resp = await client.post(f"/api/v1/boq/boqs/{main_id}/branches/", json={"name": "Mine"}, headers=owner)
    assert resp.status_code == 201, resp.text
    branch_id = resp.json()["id"]

    for method, url, body in (
        ("get", f"/api/v1/boq/boqs/{main_id}/branches/", None),
        ("post", f"/api/v1/boq/boqs/{main_id}/branches/", {"name": "Theirs"}),
        ("get", f"/api/v1/boq/boqs/{main_id}/branches/compare/{branch_id}", None),
        ("post", f"/api/v1/boq/boqs/{branch_id}/branches/plan/", {"source_boq_id": main_id}),
        ("post", f"/api/v1/boq/boqs/{branch_id}/branches/cherry-pick/", {"source_boq_id": main_id}),
    ):
        resp = await getattr(client, method)(url, headers=stranger, **({"json": body} if body else {}))
        assert resp.status_code == 404, (url, resp.status_code, resp.text)
