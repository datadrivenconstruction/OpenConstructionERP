# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A project team member reaches property_dev data as their role allows.

Every other module gates project data through ``verify_project_access``:
the owner passes and so does anyone on one of the project's teams. The
property_dev gates compared ``project.owner_id`` to the caller and nothing
else, so a sales team member could not see the condo sales of a project
they were staffed on unless they happened to own it.

The matrix below pins the four cells that matter:

* an EDITOR team member reads and writes,
* a VIEWER team member reads and is refused (403) on every write,
* an outsider gets 404, the same answer as for a missing object,
* list endpoints that scope by "my projects" include team projects.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

from .conftest import _register_user

API = "/api/v1/property-dev"


@pytest_asyncio.fixture(scope="module")
async def estate(client: AsyncClient):
    """An editor-owned project with a development, a plot and a buyer, plus
    an editor member, a viewer member, a manager member and an outsider."""
    _oid, _oe, owner = await _register_user(client, role="editor", tag=f"tmo{uuid.uuid4().hex[:4]}")
    editor_id, _ee, editor = await _register_user(client, role="editor", tag=f"tme{uuid.uuid4().hex[:4]}")
    viewer_id, _ve, viewer = await _register_user(client, role="viewer", tag=f"tmv{uuid.uuid4().hex[:4]}")
    manager_id, _me, manager = await _register_user(client, role="manager", tag=f"tmm{uuid.uuid4().hex[:4]}")
    _xid, _xe, outsider = await _register_user(client, role="editor", tag=f"tmx{uuid.uuid4().hex[:4]}")

    proj = await client.post(
        "/api/v1/projects/",
        json={"name": f"TM-{uuid.uuid4().hex[:6]}", "description": "team access", "currency": "EUR"},
        headers=owner,
    )
    assert proj.status_code in (200, 201), proj.text
    project_id = proj.json()["id"]

    for uid in (editor_id, viewer_id, manager_id):
        add = await client.post(
            f"/api/v1/projects/{project_id}/members/",
            json={"user_id": uid, "role": "member"},
            headers=owner,
        )
        assert add.status_code == 201, add.text

    dev = await client.post(
        f"{API}/developments/",
        json={
            "project_id": project_id,
            "code": f"TM-{uuid.uuid4().hex[:6]}",
            "name": "Team Gardens",
            "total_plots": 4,
            "currency": "EUR",
        },
        headers=owner,
    )
    assert dev.status_code == 201, dev.text
    dev_id = dev.json()["id"]

    plot = await client.post(
        f"{API}/plots/",
        json={
            "development_id": dev_id,
            "plot_number": f"TM-{uuid.uuid4().hex[:4]}",
            "area_m2": "100.0",
            "price_base": "300000.00",
            "currency": "EUR",
            "status": "planned",
        },
        headers=owner,
    )
    assert plot.status_code == 201, plot.text

    buyer = await client.post(
        f"{API}/buyers/",
        json={"development_id": dev_id, "full_name": "Team Buyer", "currency": "EUR"},
        headers=owner,
    )
    assert buyer.status_code == 201, buyer.text

    return {
        "project_id": project_id,
        "dev_id": dev_id,
        "plot_id": plot.json()["id"],
        "buyer_id": buyer.json()["id"],
        "owner": owner,
        "editor": editor,
        "viewer": viewer,
        "manager": manager,
        "outsider": outsider,
    }


# ── Editor team member: read and write ─────────────────────────────────


@pytest.mark.asyncio
async def test_editor_member_reads_the_development(client: AsyncClient, estate) -> None:
    resp = await client.get(f"{API}/developments/{estate['dev_id']}", headers=estate["editor"])
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_editor_member_reads_condo_sales(client: AsyncClient, estate) -> None:
    """The reported bug: a sales team member could not list the sales contracts."""
    resp = await client.get(
        f"{API}/sales-contracts/",
        params={"development_id": estate["dev_id"]},
        headers=estate["editor"],
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_editor_member_reads_the_plot(client: AsyncClient, estate) -> None:
    resp = await client.get(f"{API}/plots/{estate['plot_id']}", headers=estate["editor"])
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_editor_member_updates_the_plot(client: AsyncClient, estate) -> None:
    resp = await client.patch(
        f"{API}/plots/{estate['plot_id']}",
        json={"bedrooms": 3},
        headers=estate["editor"],
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_editor_member_updates_the_buyer(client: AsyncClient, estate) -> None:
    resp = await client.patch(
        f"{API}/buyers/{estate['buyer_id']}",
        json={"full_name": "Renamed By Member"},
        headers=estate["editor"],
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_editor_member_creates_a_plot(client: AsyncClient, estate) -> None:
    resp = await client.post(
        f"{API}/plots/",
        json={
            "development_id": estate["dev_id"],
            "plot_number": f"TMC-{uuid.uuid4().hex[:4]}",
            "area_m2": "90.0",
            "price_base": "250000.00",
            "currency": "EUR",
            "status": "planned",
        },
        headers=estate["editor"],
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_editor_member_creates_a_development_on_the_team_project(client: AsyncClient, estate) -> None:
    resp = await client.post(
        f"{API}/developments/",
        json={
            "project_id": estate["project_id"],
            "code": f"TMD-{uuid.uuid4().hex[:6]}",
            "name": "Member Phase",
            "total_plots": 1,
            "currency": "EUR",
        },
        headers=estate["editor"],
    )
    assert resp.status_code == 201, resp.text


# ── Viewer team member: read only ──────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_member_reads_the_plot(client: AsyncClient, estate) -> None:
    resp = await client.get(f"{API}/plots/{estate['plot_id']}", headers=estate["viewer"])
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_viewer_member_cannot_update_the_plot(client: AsyncClient, estate) -> None:
    resp = await client.patch(
        f"{API}/plots/{estate['plot_id']}",
        json={"bedrooms": 3},
        headers=estate["viewer"],
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_viewer_member_cannot_create_a_plot(client: AsyncClient, estate) -> None:
    resp = await client.post(
        f"{API}/plots/",
        json={
            "development_id": estate["dev_id"],
            "plot_number": f"TMV-{uuid.uuid4().hex[:4]}",
            "area_m2": "90.0",
            "price_base": "250000.00",
            "currency": "EUR",
            "status": "planned",
        },
        headers=estate["viewer"],
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_viewer_member_cannot_update_the_buyer(client: AsyncClient, estate) -> None:
    resp = await client.patch(
        f"{API}/buyers/{estate['buyer_id']}",
        json={"full_name": "Viewer Write"},
        headers=estate["viewer"],
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_viewer_member_cannot_delete_the_plot(client: AsyncClient, estate) -> None:
    resp = await client.delete(f"{API}/plots/{estate['plot_id']}", headers=estate["viewer"])
    assert resp.status_code == 403, resp.text


# ── Outsider: 404, same as a missing object ────────────────────────────


@pytest.mark.asyncio
async def test_outsider_gets_404_on_read(client: AsyncClient, estate) -> None:
    resp = await client.get(f"{API}/developments/{estate['dev_id']}", headers=estate["outsider"])
    assert resp.status_code == 404, resp.text
    missing = await client.get(f"{API}/developments/{uuid.uuid4()}", headers=estate["outsider"])
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_outsider_gets_404_on_sales_listing(client: AsyncClient, estate) -> None:
    resp = await client.get(
        f"{API}/sales-contracts/",
        params={"development_id": estate["dev_id"]},
        headers=estate["outsider"],
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_outsider_gets_404_on_write(client: AsyncClient, estate) -> None:
    plot = await client.patch(
        f"{API}/plots/{estate['plot_id']}",
        json={"bedrooms": 3},
        headers=estate["outsider"],
    )
    assert plot.status_code == 404, plot.text
    buyer = await client.patch(
        f"{API}/buyers/{estate['buyer_id']}",
        json={"full_name": "Outsider Write"},
        headers=estate["outsider"],
    )
    assert buyer.status_code == 404, buyer.text


@pytest.mark.asyncio
async def test_outsider_cannot_attach_a_development_to_the_project(client: AsyncClient, estate) -> None:
    resp = await client.post(
        f"{API}/developments/",
        json={
            "project_id": estate["project_id"],
            "code": f"TMX-{uuid.uuid4().hex[:6]}",
            "name": "Hijack",
            "total_plots": 1,
            "currency": "EUR",
        },
        headers=estate["outsider"],
    )
    assert resp.status_code == 404, resp.text


# ── Lists include team projects ────────────────────────────────────────


@pytest.mark.asyncio
async def test_development_list_includes_team_projects(client: AsyncClient, estate) -> None:
    for who in ("editor", "viewer"):
        resp = await client.get(f"{API}/developments/", params={"limit": 200}, headers=estate[who])
        assert resp.status_code == 200, resp.text
        ids = {row["id"] for row in resp.json()}
        assert estate["dev_id"] in ids, f"{who} team member does not see the team development"


@pytest.mark.asyncio
async def test_development_list_excludes_foreign_projects(client: AsyncClient, estate) -> None:
    resp = await client.get(f"{API}/developments/", params={"limit": 200}, headers=estate["outsider"])
    assert resp.status_code == 200, resp.text
    assert estate["dev_id"] not in {row["id"] for row in resp.json()}


@pytest.mark.asyncio
async def test_bulk_batch_processes_team_project_rows(client: AsyncClient, estate) -> None:
    """The sales-ops batch console skips rows of projects the caller cannot
    reach. A manager on the team must not have the team's plots skipped."""
    resp = await client.post(
        f"{API}/bulk/plots/bulk-status-change/?dry_run=true",
        json={"plot_ids": [estate["plot_id"]], "target_status": "reserved", "reason": "team batch"},
        headers=estate["manager"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["skipped"] == [], body
    assert body["succeeded"] == 1, body


@pytest.mark.asyncio
async def test_bulk_batch_skips_rows_for_an_outsider_manager(client: AsyncClient, estate) -> None:
    _uid, _e, foreign_manager = await _register_user(client, role="manager", tag=f"tmfm{uuid.uuid4().hex[:4]}")
    resp = await client.post(
        f"{API}/bulk/plots/bulk-status-change/?dry_run=true",
        json={"plot_ids": [estate["plot_id"]], "target_status": "reserved", "reason": "foreign batch"},
        headers=foreign_manager,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["succeeded"] == 0, body
    assert len(body["skipped"]) == 1, body
