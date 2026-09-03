# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Router-level tests: the wiring, the permission gates and the shapes.

Mounted as a bare app with the auth dependencies overridden, so no JWT is
minted and no module loader runs. The caller is a NON-admin on purpose:
admin bypasses every permission check, so an admin-run suite would pass
against a module that locked everybody else out.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.work_requests.router import router as wr_router
from tests._pg import isolated_engine

USER_ID = "00000000-0000-0000-0000-0000000000c1"
BASE = "/api/v1/work-requests"

EDITOR = {"role": "editor", "permissions": ["work_requests.read", "work_requests.create", "work_requests.update"]}
VIEWER = {"role": "viewer", "permissions": ["work_requests.read", "work_requests.create"]}
MANAGER = {"role": "manager", "permissions": [*EDITOR["permissions"], "work_requests.manage"]}


def _day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


@pytest_asyncio.fixture
async def ctx():
    """A live app, a non-admin caller, and a project they own."""
    async with isolated_engine() as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            user = User(
                id=uuid.UUID(USER_ID),
                email=f"rt-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                full_name="Alex Example",
                role="editor",
            )
            s.add(user)
            await s.flush()
            project = Project(
                name="Example Client Pty Ltd - MCC upgrade",
                owner_id=user.id,
                currency="AUD",
                project_code="25406",
                client_id="Acme Holdings",
            )
            s.add(project)
            await s.commit()
            project_id = str(project.id)

        state = {"payload": dict(EDITOR)}
        app = FastAPI()
        app.include_router(wr_router, prefix=BASE)
        app.dependency_overrides[get_current_user_id] = lambda: USER_ID
        app.dependency_overrides[get_current_user_payload] = lambda: {"sub": USER_ID, **state["payload"]}

        async def _session_override():
            async with maker() as s:
                yield s

        app.dependency_overrides[get_session] = _session_override
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield client, project_id, state


async def _raise(client, project_id: str, **over) -> dict:
    body = {
        "project_id": project_id,
        "department": over.pop("department", "workshop"),
        "request_type": over.pop("request_type", "switchboard"),
        "title": over.pop("title", "MSB-01 main switchboard"),
        **over,
    }
    r = await client.post(f"{BASE}/requests", json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_departments_self_seed_and_a_viewer_reads_and_raises(ctx) -> None:
    client, pid, state = ctx
    state["payload"] = dict(VIEWER)
    r = await client.get(f"{BASE}/departments")
    assert r.status_code == 200
    assert [d["key"] for d in r.json()["items"]] == [
        "engineering",
        "drafting",
        "workshop",
        "automation",
        "hazardous_area",
    ]
    assert r.json()["items"][2]["prefix"] == "WKS"
    assert r.json()["total"] == 5, "the envelope counts the whole taxonomy, not the page"

    made = await _raise(
        client,
        pid,
        due_date=_day(14),
        quoted_hours=40,
        fields={"custom_plinth": "Yes - stand", "factory_cost_centre": "CC-100"},
        links=[{"label": "SLD", "url": "https://example.com/sld.pdf"}],
    )
    assert made["reference"] == "WR-WKS-000001"
    assert made["status"] == "submitted"
    assert made["stage"] == "requested"
    assert made["project_code"] == "25406"
    assert made["client_name"] == "Acme Holdings"
    assert made["raised_by_name"] == "Alex Example"
    assert made["fields"]["custom_plinth"] == "Yes - stand"
    assert made["days_until_due"] == 14
    assert made["allowed_transitions"] == ["accepted", "cancelled"]

    listed = await client.get(f"{BASE}/requests", params={"project_id": pid, "department": "workshop"})
    assert [x["id"] for x in listed.json()["items"]] == [made["id"]]
    assert listed.json()["total"] == 1
    unscoped = await client.get(f"{BASE}/requests")
    assert [x["id"] for x in unscoped.json()["items"]] == [made["id"]], "no project_id = the caller's own jobs"
    found = await client.get(f"{BASE}/requests", params={"q": "msb-01"})
    assert len(found.json()["items"]) == 1
    nothing = await client.get(f"{BASE}/requests", params={"q": "%"})
    assert nothing.json()["items"] == [], "a LIKE metacharacter is a character, not a wildcard"
    assert nothing.json()["total"] == 0


@pytest.mark.asyncio
async def test_reference_lookup(ctx) -> None:
    client, pid, _ = ctx
    made = await _raise(client, pid)
    by_ref = await client.get(f"{BASE}/requests/wr-wks-000001")
    assert by_ref.status_code == 200 and by_ref.json()["id"] == made["id"]
    assert (await client.get(f"{BASE}/requests/WR-WKS-000099")).status_code == 404
    assert (await client.get(f"{BASE}/requests/{uuid.uuid4()}")).status_code == 404


@pytest.mark.asyncio
async def test_manage_is_refused_below_manager(ctx) -> None:
    client, pid, state = ctx
    body = {"key": "site_services", "name": "Site Services"}
    assert (await client.post(f"{BASE}/departments", json=body)).status_code == 403
    assert (
        await client.put(f"{BASE}/planner/capacity", params={"department": "workshop"}, json={_day(1): 3})
    ).status_code == 403
    assert (await client.patch(f"{BASE}/departments/workshop", json={"name": "Factory"})).status_code == 403
    state["payload"] = dict(VIEWER)
    made = await _raise(client, pid)
    assert (await client.patch(f"{BASE}/requests/{made['id']}", json={"title": "x"})).status_code == 403, (
        "a viewer raises but does not update"
    )
    state["payload"] = dict(MANAGER)
    r = await client.post(f"{BASE}/departments", json=body)
    assert r.status_code == 201 and r.json()["prefix"] == "SIT"
    r = await client.put(f"{BASE}/planner/capacity", params={"department": "workshop"}, json={_day(1): 3})
    assert r.status_code == 200 and r.json()["capacity"] == {_day(1): 3.0}
    r = await client.patch(f"{BASE}/departments/workshop", json={"hourly_rate": "150", "name": "Factory"})
    assert r.status_code == 200 and r.json()["hourly_rate"] == "150.00"


@pytest.mark.asyncio
async def test_illegal_transition_is_a_409_with_the_allowed_list(ctx) -> None:
    client, pid, _ = ctx
    made = await _raise(client, pid)
    r = await client.patch(f"{BASE}/requests/{made['id']}", json={"status": "complete"})
    assert r.status_code == 409
    assert r.json()["detail"]["allowed"] == ["accepted", "cancelled"]
    assert "cannot move to complete" in r.json()["detail"]["error"]
    ok = await client.patch(f"{BASE}/requests/{made['id']}", json={"status": "accepted"})
    assert ok.status_code == 200 and ok.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_the_board_hours_and_handoff_over_http(ctx) -> None:
    client, pid, _ = ctx
    made = await _raise(client, pid, quoted_hours=10)
    rid = made["id"]
    r = await client.post(f"{BASE}/requests/{rid}/stage", json={"stage": "build", "note": "started"})
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    r = await client.post(f"{BASE}/requests/{rid}/hours", json={"date": _day(0), "hours": 4})
    assert r.status_code == 201 and r.json()["request"]["hours_logged"] == 4
    log_id = r.json()["id"]
    assert [h["id"] for h in (await client.get(f"{BASE}/requests/{rid}/hours")).json()["items"]] == [log_id]
    r = await client.post(
        f"{BASE}/requests/{rid}/handoff",
        json={"department": "drafting", "request_type": "drafting_only", "title": "GA for MSB-01", "due_date": _day(7)},
    )
    assert r.status_code == 201
    child = r.json()
    assert child["reference"] == "WR-DRF-000001" and child["parent_reference"] == "WR-WKS-000001"
    parent = (await client.get(f"{BASE}/requests/{rid}")).json()
    assert [d["reference"] for d in parent["depends_on"]] == ["WR-DRF-000001"]
    r = await client.post(f"{BASE}/requests/{rid}/needs-info", json={"question": "Which fault level?"})
    assert r.status_code == 200 and r.json()["ball_in_court"] == "requester"
    r = await client.post(f"{BASE}/requests/{rid}/answer", json={"answer": "36kA"})
    assert r.status_code == 200 and r.json()["ball_in_court"] == "department"
    r = await client.post(f"{BASE}/requests/{rid}/comments", json={"body": "Thanks", "mention_ids": []})
    assert r.status_code == 201 and r.json()["kind"] == "comment"
    comments = (await client.get(f"{BASE}/requests/{rid}/comments")).json()["items"]
    assert [c["kind"] for c in comments] == ["needs_info", "answer", "comment"]
    activity = (await client.get(f"{BASE}/requests/{rid}/activity")).json()["items"]
    assert activity[0]["what"] == "Raised"
    assert any(a["what"].startswith("Logged 4h") for a in activity)
    assert (await client.delete(f"{BASE}/requests/{rid}/hours/{log_id}")).status_code == 204
    grid = (
        await client.get(f"{BASE}/planner", params={"department": "workshop", "from": _day(0), "to": _day(2)})
    ).json()
    assert [row["reference"] for row in grid["rows"]] == ["WR-WKS-000001"]
    r = await client.put(f"{BASE}/planner/{rid}", json={"alloc": {_day(1): 2}})
    assert r.status_code == 200 and r.json()["alloc"] == {_day(1): 2.0}
    summary = (await client.get(f"{BASE}/summary", params={"project_id": pid})).json()
    assert {d["key"]: d["open"] for d in summary["departments"]}["workshop"] == 1
    queue = (await client.get(f"{BASE}/my-queue")).json()
    assert [x["reference"] for x in queue["raised"]] == ["WR-DRF-000001", "WR-WKS-000001"]


@pytest.mark.asyncio
async def test_attachments_land_and_serve_from_the_data_dir(ctx) -> None:
    client, pid, _ = ctx
    made = await _raise(client, pid)
    r = await client.post(
        f"{BASE}/requests/{made['id']}/attachments",
        files={"file": ("../../MSB-01 GA.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["attachment"]["filename"] == "MSB-01 GA.pdf", "traversal stripped, name kept"
    assert r.json()["request"]["attachments"][0]["size"] == 10
    again = await client.post(
        f"{BASE}/requests/{made['id']}/attachments",
        files={"file": ("MSB-01 GA.pdf", io.BytesIO(b"%PDF-1.4 y"), "application/pdf")},
    )
    assert again.json()["attachment"]["filename"] == "MSB-01 GA-1.pdf", "never overwritten"
    got = await client.get(f"{BASE}/requests/{made['id']}/attachments/MSB-01 GA.pdf")
    assert got.status_code == 200 and got.content == b"%PDF-1.4 x"
    assert got.headers["content-type"].startswith("application/pdf")
    assert (await client.get(f"{BASE}/requests/{made['id']}/attachments/nope.pdf")).status_code == 404
    empty = await client.post(
        f"{BASE}/requests/{made['id']}/attachments", files={"file": ("e.txt", io.BytesIO(b""), "text/plain")}
    )
    assert empty.status_code == 400


@pytest.mark.asyncio
async def test_deadline_sweep_rings_once(ctx) -> None:
    client, pid, _ = ctx
    await _raise(client, pid, due_date=_day(-1))
    first = await client.post(f"{BASE}/deadline-sweep")
    assert first.status_code == 200 and first.json()["published"] == 1
    second = await client.post(f"{BASE}/deadline-sweep")
    assert second.json()["published"] == 0


@pytest.mark.asyncio
async def test_bad_input_is_a_400_with_a_reason(ctx) -> None:
    client, pid, _ = ctx
    r = await client.post(
        f"{BASE}/requests",
        json={"project_id": pid, "department": "workshop", "request_type": "painting", "title": "x"},
    )
    assert r.status_code == 400 and "painting" in r.json()["detail"]
    r = await client.post(
        f"{BASE}/requests",
        json={
            "project_id": pid,
            "department": "workshop",
            "request_type": "switchboard",
            "title": "x",
            "fields": {"custom_plinth": "Maybe"},
        },
    )
    assert r.status_code == 400 and "Custom plinth" in r.json()["detail"]
    r = await client.post(
        f"{BASE}/requests",
        json={"project_id": str(uuid.uuid4()), "department": "workshop", "request_type": "switchboard", "title": "x"},
    )
    assert r.status_code == 404, "an unknown job is a 404, not a 500"
