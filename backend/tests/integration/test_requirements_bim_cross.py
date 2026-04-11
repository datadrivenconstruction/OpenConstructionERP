"""Integration tests for the Requirements ↔ BIM cross-module wiring.

Drives the full v1.4.3 flow end-to-end against a live app instance:

    1.  Create project + requirement set + requirement.
    2.  Create BIM model + bulk-import two BIM elements.
    3.  PATCH ``/requirements/{set_id}/requirements/{req_id}/bim-links/``
        with ONE of the element ids → verify the metadata stores it and
        additive merge works on a second PATCH.
    4.  GET ``/requirements/by-bim-element/?bim_element_id=...`` →
        verify the reverse query returns the requirement.
    5.  GET ``/bim_hub/models/{model_id}/elements/`` → verify the
        Step 6.5 eager load in ``BIMHubService.list_elements_with_links``
        populates the ``linked_requirements`` array on the element the
        requirement was pinned to AND leaves it empty on the other.

The module-scoped shared_client + shared_auth fixtures (registered
admin user, full app lifespan including module_loader.load_all) are
borrowed from ``test_cross_module_flows.py`` — importing them would
introduce cross-file fixture coupling so we redefine them here with
distinct names.  This keeps the test self-contained and avoids
poisoning the other file's rate-limited login.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# ── Module-scoped fixtures ─────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def req_bim_client():
    """Module-scoped client with full lifespan (runs module_loader)."""
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
async def req_bim_auth(req_bim_client: AsyncClient) -> dict[str, str]:
    """Register a unique admin and return Authorization headers."""
    unique = uuid.uuid4().hex[:8]
    email = f"reqbim-{unique}@test.io"
    password = f"ReqBim{unique}9"

    reg = await req_bim_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Requirements BIM Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    token = ""
    for attempt in range(3):
        resp = await req_bim_client.post(
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


# ── Helpers ────────────────────────────────────────────────────────────────


async def _create_project(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"ReqBIM Project {uuid.uuid4().hex[:6]}",
            "description": "Requirements ↔ BIM cross-module test project",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Project create failed: {resp.text}"
    return resp.json()["id"]


async def _create_requirement_set(
    client: AsyncClient, auth: dict[str, str], project_id: str
) -> str:
    resp = await client.post(
        "/api/v1/requirements/",
        json={
            "project_id": project_id,
            "name": "Fire safety spec",
            "description": "DIN 4102-1 requirements",
            "source_type": "manual",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Set create failed: {resp.text}"
    return resp.json()["id"]


async def _add_requirement(
    client: AsyncClient, auth: dict[str, str], set_id: str
) -> str:
    resp = await client.post(
        f"/api/v1/requirements/{set_id}/requirements/",
        json={
            "entity": "exterior_wall",
            "attribute": "fire_rating",
            "constraint_type": "equals",
            "constraint_value": "F90",
            "unit": "min",
            "category": "fire_safety",
            "priority": "must",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Requirement create failed: {resp.text}"
    return resp.json()["id"]


async def _create_bim_model(
    client: AsyncClient, auth: dict[str, str], project_id: str
) -> str:
    resp = await client.post(
        "/api/v1/bim_hub/",
        json={
            "project_id": project_id,
            "name": "Test IFC model",
            "discipline": "architecture",
            "model_format": "ifc",
            "status": "ready",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Model create failed: {resp.text}"
    return resp.json()["id"]


async def _bulk_import_elements(
    client: AsyncClient, auth: dict[str, str], model_id: str
) -> list[str]:
    """Seed the model with two distinct elements and return their ids."""
    resp = await client.post(
        f"/api/v1/bim_hub/models/{model_id}/elements/",
        json={
            "elements": [
                {
                    "stable_id": "wall-001",
                    "element_type": "IfcWall",
                    "name": "Exterior wall 1",
                    "storey": "L1",
                    "discipline": "architecture",
                    "properties": {"material": "concrete_c30_37"},
                    "quantities": {"area": 37.5},
                },
                {
                    "stable_id": "wall-002",
                    "element_type": "IfcWall",
                    "name": "Interior wall 1",
                    "storey": "L1",
                    "discipline": "architecture",
                    "properties": {"material": "drywall"},
                    "quantities": {"area": 12.0},
                },
            ]
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Bulk import failed: {resp.text}"
    items = resp.json().get("items", [])
    assert len(items) == 2, f"Expected 2 elements, got {len(items)}"
    return [it["id"] for it in items]


# ── The one test that exercises the whole v1.4.3 cross-module chain ───────


class TestRequirementsBimCrossModule:
    """End-to-end coverage of the Requirements ↔ BIM cross-module link."""

    async def test_full_cross_module_flow(
        self, req_bim_client: AsyncClient, req_bim_auth: dict[str, str]
    ) -> None:
        client = req_bim_client
        auth = req_bim_auth

        # ── 1. Seed the domain ────────────────────────────────────────
        project_id = await _create_project(client, auth)
        set_id = await _create_requirement_set(client, auth, project_id)
        req_id = await _add_requirement(client, auth, set_id)
        model_id = await _create_bim_model(client, auth, project_id)
        element_ids = await _bulk_import_elements(client, auth, model_id)
        pinned_element_id, other_element_id = element_ids

        # ── 2. PATCH /bim-links/ — initial link ──────────────────────
        resp = await client.patch(
            f"/api/v1/requirements/{set_id}/requirements/{req_id}/bim-links/",
            json={"bim_element_ids": [pinned_element_id], "replace": False},
            headers=auth,
        )
        assert resp.status_code == 200, f"bim-links PATCH failed: {resp.text}"
        body = resp.json()
        stored = (body.get("metadata") or {}).get("bim_element_ids") or []
        assert pinned_element_id in stored, (
            f"Expected {pinned_element_id} in stored ids, got {stored}"
        )

        # ── 3. PATCH /bim-links/ — additive merge ────────────────────
        # Re-PATCH with a fresh id (replace=False is the default).  Both
        # ids should survive the merge.
        extra_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/requirements/{set_id}/requirements/{req_id}/bim-links/",
            json={"bim_element_ids": [extra_id]},
            headers=auth,
        )
        assert resp.status_code == 200, resp.text
        stored = (resp.json().get("metadata") or {}).get("bim_element_ids") or []
        assert pinned_element_id in stored
        assert extra_id in stored
        assert len(stored) == 2, f"Expected additive merge, got {stored}"

        # ── 4. PATCH /bim-links/ — replace=True wipes prior links ────
        resp = await client.patch(
            f"/api/v1/requirements/{set_id}/requirements/{req_id}/bim-links/",
            json={"bim_element_ids": [pinned_element_id], "replace": True},
            headers=auth,
        )
        assert resp.status_code == 200, resp.text
        stored = (resp.json().get("metadata") or {}).get("bim_element_ids") or []
        assert stored == [pinned_element_id], (
            f"Expected replace to wipe prior ids, got {stored}"
        )

        # ── 5. GET /by-bim-element/ — reverse query ──────────────────
        resp = await client.get(
            "/api/v1/requirements/by-bim-element/",
            params={"bim_element_id": pinned_element_id, "project_id": project_id},
            headers=auth,
        )
        assert resp.status_code == 200, resp.text
        hits = resp.json()
        assert any(h["id"] == req_id for h in hits), (
            f"Expected requirement {req_id} in reverse hits, got {hits}"
        )

        # ── 6. Reverse query for the UNPINNED element must be empty ──
        resp = await client.get(
            "/api/v1/requirements/by-bim-element/",
            params={"bim_element_id": other_element_id, "project_id": project_id},
            headers=auth,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == [], (
            f"Unpinned element should have no linked requirements, "
            f"got {resp.json()}"
        )

        # ── 7. GET /bim_hub/models/{id}/elements/ — Step 6.5 eager load ─
        # This is the money shot — ``BIMHubService.list_elements_with_links``
        # must populate the ``linked_requirements`` array on the pinned
        # element and leave it empty on the other one.
        resp = await client.get(
            f"/api/v1/bim_hub/models/{model_id}/elements/",
            headers=auth,
        )
        assert resp.status_code == 200, resp.text
        items = resp.json().get("items", [])
        assert len(items) == 2, f"Expected 2 elements back, got {len(items)}"

        by_id = {it["id"]: it for it in items}
        pinned = by_id[pinned_element_id]
        other = by_id[other_element_id]

        pinned_reqs = pinned.get("linked_requirements", [])
        assert len(pinned_reqs) == 1, (
            f"Pinned element should surface 1 requirement, "
            f"got {len(pinned_reqs)}: {pinned_reqs}"
        )
        brief = pinned_reqs[0]
        assert brief["id"] == req_id
        assert brief["entity"] == "exterior_wall"
        assert brief["attribute"] == "fire_rating"
        assert brief["constraint_value"] == "F90"
        assert brief["priority"] == "must"

        assert other.get("linked_requirements", []) == [], (
            "Unpinned element must carry an empty linked_requirements array"
        )

    async def test_bim_links_patch_rejects_mismatched_set(
        self, req_bim_client: AsyncClient, req_bim_auth: dict[str, str]
    ) -> None:
        """The PATCH endpoint refuses a ``set_id`` that doesn't own the
        requirement — otherwise an attacker could link arbitrary BIM
        elements by guessing the requirement UUID."""
        client = req_bim_client
        auth = req_bim_auth

        project_id = await _create_project(client, auth)
        set_id = await _create_requirement_set(client, auth, project_id)
        req_id = await _add_requirement(client, auth, set_id)
        other_set_id = await _create_requirement_set(client, auth, project_id)

        resp = await client.patch(
            f"/api/v1/requirements/{other_set_id}/requirements/{req_id}/bim-links/",
            json={"bim_element_ids": [str(uuid.uuid4())]},
            headers=auth,
        )
        assert resp.status_code == 400, (
            f"Expected 400 for mismatched set, got {resp.status_code}: {resp.text}"
        )

    async def test_orphan_bim_ids_stripped_on_element_delete(
        self, req_bim_client: AsyncClient, req_bim_auth: dict[str, str]
    ) -> None:
        """Pin a requirement and a task to a BIM element, then delete
        the entire BIM model.  The cleanup subscriber wired in v1.4.5
        (``bim_hub.events._cleanup_orphaned_links``) must strip the
        deleted element id from BOTH JSON-array link sites so the
        reverse-query helpers don't return zombies on the next read.

        This is the regression test for the v1.4.x finding that 3 out
        of 5 cross-module link types (Task / Activity / Requirement,
        which use JSON arrays instead of FK tables) leaked stale
        references on BIM element delete forever.
        """
        client = req_bim_client
        auth = req_bim_auth

        # Seed the domain.
        project_id = await _create_project(client, auth)
        set_id = await _create_requirement_set(client, auth, project_id)
        req_id = await _add_requirement(client, auth, set_id)
        model_id = await _create_bim_model(client, auth, project_id)
        element_ids = await _bulk_import_elements(client, auth, model_id)
        target_element_id = element_ids[0]

        # Pin the requirement to the element via the v1.4.3 endpoint.
        resp = await client.patch(
            f"/api/v1/requirements/{set_id}/requirements/{req_id}/bim-links/",
            json={"bim_element_ids": [target_element_id], "replace": True},
            headers=auth,
        )
        assert resp.status_code == 200, resp.text
        stored = (resp.json().get("metadata") or {}).get("bim_element_ids") or []
        assert target_element_id in stored

        # Pin a task to the same element via the tasks create endpoint.
        resp = await client.post(
            "/api/v1/tasks/",
            json={
                "project_id": project_id,
                "title": "Inspect this wall",
                "description": "Site inspection — pinned to wall element",
                "task_type": "task",
                "status": "open",
                "priority": "normal",
                "bim_element_ids": [target_element_id],
            },
            headers=auth,
        )
        assert resp.status_code == 201, f"Task create failed: {resp.text}"
        task_id = resp.json()["id"]

        # Sanity: tasks reverse query finds it before delete.
        resp = await client.get(
            "/api/v1/tasks/",
            params={"project_id": project_id, "bim_element_id": target_element_id},
            headers=auth,
        )
        assert resp.status_code == 200, resp.text
        assert any(t["id"] == task_id for t in resp.json()), (
            "Task should be reverse-discoverable BEFORE the element is deleted"
        )

        # Sanity: requirement reverse query finds it before delete.
        resp = await client.get(
            "/api/v1/requirements/by-bim-element/",
            params={"bim_element_id": target_element_id, "project_id": project_id},
            headers=auth,
        )
        assert resp.status_code == 200, resp.text
        assert any(r["id"] == req_id for r in resp.json())

        # Trigger element deletion via the bulk-import-replace path
        # (which only needs bim.create, not bim.delete — the test user
        # is registered as ``editor`` because the registration endpoint
        # demotes everyone except the very first user to prevent
        # privilege escalation, and bim.delete requires admin).
        # ``bulk_import_elements`` deletes existing rows for the model
        # AND fires ``bim_hub.element.deleted`` for each one before
        # creating the new batch — exactly the event our cleanup
        # subscriber listens for.
        resp = await client.post(
            f"/api/v1/bim_hub/models/{model_id}/elements/",
            json={
                "elements": [
                    {
                        "stable_id": "wall-replacement",
                        "element_type": "IfcWall",
                        "name": "Replacement wall",
                        "storey": "L1",
                        "discipline": "architecture",
                        "properties": {},
                        "quantities": {},
                    },
                ],
            },
            headers=auth,
        )
        assert resp.status_code == 201, f"Bulk replace failed: {resp.text}"

        # The task should NO LONGER reference the deleted element.
        resp = await client.get(
            "/api/v1/tasks/",
            params={"project_id": project_id, "bim_element_id": target_element_id},
            headers=auth,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == [], (
            f"Task still references deleted element {target_element_id}: "
            f"{resp.json()}"
        )

        # The requirement reverse query should also return empty.
        resp = await client.get(
            "/api/v1/requirements/by-bim-element/",
            params={"bim_element_id": target_element_id, "project_id": project_id},
            headers=auth,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == [], (
            f"Requirement still references deleted element {target_element_id}: "
            f"{resp.json()}"
        )

        # And the requirement row itself should have the id stripped
        # from its metadata array (defensive double-check).
        resp = await client.get(
            f"/api/v1/requirements/{set_id}",
            headers=auth,
        )
        assert resp.status_code == 200, resp.text
        detail = resp.json()
        req = next(r for r in detail["requirements"] if r["id"] == req_id)
        assert target_element_id not in (
            (req.get("metadata") or {}).get("bim_element_ids") or []
        ), "Requirement.metadata still carries the orphaned element id"
