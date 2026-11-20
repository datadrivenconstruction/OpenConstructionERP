"""A bundle belongs to the company that made it: a manager of another company gets 404 on every
route that takes a bundle id, and the list shows only the bundles the caller may open."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from tests.modules.central_purchasing.conftest import register_user

API = "/api/v1/central-purchasing"


async def test_another_companys_manager_cannot_open_touch_or_list_a_bundle(client: AsyncClient) -> None:
    _, owner = await register_user(client, "manager", "own")
    _, rival = await register_user(client, "manager", "riv")
    made = await client.post(f"{API}/", json={"title": "Own bundle", "currency": "EUR"}, headers=owner)
    assert made.status_code == 201, made.text
    bid = made.json()["id"]

    assert (await client.get(f"{API}/{bid}", headers=owner)).status_code == 200
    missing = await client.get(f"{API}/{uuid.uuid4()}", headers=rival)
    other = await client.get(f"{API}/{bid}", headers=rival)
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()

    line = {"description": "x", "unit": "m2", "quantity": "1"}
    calls = [
        ("patch", f"{API}/{bid}", {"title": "hijack"}),
        ("delete", f"{API}/{bid}", None),
        ("post", f"{API}/{bid}/preview", {}),
        ("post", f"{API}/{bid}/lines", line),
        ("patch", f"{API}/{bid}/lines/{uuid.uuid4()}", {"description": "y"}),
        ("delete", f"{API}/{bid}/lines/{uuid.uuid4()}", None),
        ("patch", f"{API}/{bid}/projects/{uuid.uuid4()}", {}),
        ("delete", f"{API}/{bid}/projects/{uuid.uuid4()}", None),
        ("post", f"{API}/{bid}/publish", None),
        ("post", f"{API}/{bid}/award", {"vendor_name": "X"}),
    ]
    for method, url, body in calls:
        resp = await client.request(method, url, json=body, headers=rival)
        assert resp.status_code == 404, (method, url, resp.status_code, resp.text)

    assert bid in {b["id"] for b in (await client.get(f"{API}/", headers=owner)).json()}
    assert bid not in {b["id"] for b in (await client.get(f"{API}/", headers=rival)).json()}
    assert (await client.get(f"{API}/{bid}", headers=owner)).json()["title"] == "Own bundle"


async def test_a_member_of_one_project_is_kept_out_of_the_bundle_and_sees_only_that_share(client: AsyncClient) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.projects.models import Project

    _, buyer = await register_user(client, "admin", "ob")
    member_id, member = await register_user(client, "manager", "pm")
    ids = []
    for name in ("Own A", "Other B"):
        made = await client.post("/api/v1/projects/", json={"name": name, "currency": "EUR"}, headers=buyer)
        assert made.status_code in (200, 201), made.text
        ids.append(made.json()["id"])
    pa, pb = ids
    async with async_session_factory() as session:
        await session.execute(update(Project).where(Project.id == uuid.UUID(pa)).values(owner_id=uuid.UUID(member_id)))
        await session.commit()

    bid = (await client.post(f"{API}/", json={"title": "Drywall", "currency": "EUR"}, headers=buyer)).json()["id"]
    for pid in ids:
        resp = await client.post(f"{API}/{bid}/projects", json={"project_id": pid}, headers=buyer)
        assert resp.status_code == 200, resp.text
    bps = {p["project_id"]: p["id"] for p in resp.json()["projects"]}
    line = {
        "code": "L1",
        "description": "Partition",
        "unit": "m2",
        "quantity": "300",
        "unit_rate": "10",
        "shares": [
            {"bundle_project_id": bps[pa], "quantity": "100"},
            {"bundle_project_id": bps[pb], "quantity": "200"},
        ],
    }
    assert (await client.post(f"{API}/{bid}/lines", json=line, headers=buyer)).status_code == 200
    pub = await client.post(f"{API}/{bid}/publish", headers=buyer)
    assert pub.status_code == 200, pub.text

    assert (await client.get(f"{API}/{bid}", headers=member)).status_code == 404
    assert bid not in {b["id"] for b in (await client.get(f"{API}/", headers=member)).json()}
    assert (await client.post(f"{API}/{bid}/award", json={"vendor_name": "X"}, headers=member)).status_code == 404

    mine = (await client.get(f"{API}/my-shares", params={"project_id": pa}, headers=member)).json()
    assert [m["gross"] for m in mine] == ["1000.00"]
    assert [ln["quantity"] for ln in mine[0]["lines"]] == ["100.0000"]
    assert "3000" not in str(mine)
    assert (await client.get(f"{API}/my-shares", params={"project_id": pb}, headers=member)).status_code == 404
