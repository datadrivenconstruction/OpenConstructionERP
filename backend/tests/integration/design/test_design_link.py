"""R1 + link part of R2: module mounts, version negotiation, code -> token, scope, lock."""

from __future__ import annotations

import uuid

import pytest

from .conftest import LINK, make_project, make_user

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/design"


async def _token(client, headers, project_id) -> str:
    r = await client.post(
        f"{BASE}/link/code", json={"project_id": str(project_id), "action": "new"}, headers={**headers, **LINK}
    )
    assert r.status_code == 200, r.text
    link = r.json()
    assert link["schema"] == "ddc-link/1" and len(link["code"]) >= 32
    x = await client.post(
        f"{BASE}/link/exchange", json={"code": link["code"], "client": {"name": "test"}}, headers=LINK
    )
    assert x.status_code == 200, x.text
    assert x.json()["token"].startswith("ddcl_")
    return x.json()["token"]


async def test_module_mounted_and_versioned(client):
    r = await client.get(f"{BASE}/", headers=LINK)
    assert r.status_code == 200 and r.json()["link_versions"] == [1]
    bad = await client.get(f"{BASE}/", headers={"X-DDC-Link": "2"})
    assert bad.status_code == 426
    assert bad.json()["detail"]["supported"] == [1]


async def test_code_is_single_use_and_token_reads_context(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    r = await client.post(f"{BASE}/link/code", json={"project_id": str(pid), "action": "new"}, headers=h)
    code = r.json()["code"]
    first = await client.post(f"{BASE}/link/exchange", json={"code": code})
    second = await client.post(f"{BASE}/link/exchange", json={"code": code})
    assert first.status_code == 200 and second.status_code == 410
    tok = {"Authorization": f"Bearer {first.json()['token']}", **LINK}
    ctx = await client.get(f"{BASE}/projects/{pid}/context", headers=tok)
    assert ctx.status_code == 200, ctx.text
    body = ctx.json()
    assert body["schema"] == "ddc-context/1" and body["project"]["id"] == str(pid)
    assert body["permissions"]["can_accept"] is True  # owner
    assert body["latest_revision"] is None and body["lock"] is None


async def test_open_requires_revision(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    r = await client.post(f"{BASE}/link/code", json={"project_id": str(pid), "action": "open"}, headers=h)
    assert r.status_code == 422


async def test_token_is_bound_to_one_project(client):
    uid, h = await make_user(client)
    p1 = await make_project(uid)
    p2 = await make_project(uid, name="Other")
    tok = {"Authorization": f"Bearer {await _token(client, h, p1)}"}
    assert (await client.get(f"{BASE}/projects/{p2}/context", headers=tok)).status_code == 404
    assert (await client.get(f"{BASE}/projects/{p1}/context", headers=tok)).status_code == 200


async def test_no_code_for_foreign_project(client):
    owner, _ = await make_user(client)
    _, stranger = await make_user(client)
    pid = await make_project(owner)
    r = await client.post(f"{BASE}/link/code", json={"project_id": str(pid), "action": "new"}, headers=stranger)
    assert r.status_code == 404


async def test_bad_tokens_rejected(client):
    pid = uuid.uuid4()
    for auth in ("Bearer ddcl_nope", "Bearer garbage", None):
        headers = {"Authorization": auth} if auth else {}
        assert (await client.get(f"{BASE}/projects/{pid}/context", headers=headers)).status_code == 401


async def test_lock_blocks_second_user_and_heartbeat_renews(client):
    owner, h_owner = await make_user(client)
    other, h_other = await make_user(client)
    pid = await make_project(owner)
    from app.database import async_session_factory

    tok = {"Authorization": f"Bearer {await _token(client, h_owner, pid)}"}
    a = await client.post(f"{BASE}/projects/{pid}/lock", headers=tok)
    assert a.status_code == 200 and a.json()["mine"] is True
    hb = await client.post(f"{BASE}/projects/{pid}/lock/heartbeat", headers=tok)
    assert hb.status_code == 200 and hb.json()["expires_at"] >= a.json()["expires_at"]
    ctx = (await client.get(f"{BASE}/projects/{pid}/context", headers=tok)).json()
    assert ctx["lock"]["mine"] is True

    # A second user with access (admin bypasses ownership) cannot take it.
    async with async_session_factory() as s:
        from sqlalchemy import update

        from app.modules.users.models import User

        await s.execute(update(User).where(User.id == other).values(role="admin"))
        await s.commit()
    b = await client.post(f"{BASE}/projects/{pid}/lock", headers=h_other)
    assert b.status_code == 409, b.text

    rel = await client.delete(f"{BASE}/projects/{pid}/lock", headers=tok)
    assert rel.status_code == 204
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=h_other)).status_code == 200


async def test_access_reports_role_and_foreign_lock(client):
    owner, h_owner = await make_user(client)
    editor, h_editor = await make_user(client, role="editor")
    pid = await make_project(owner)
    mine = await client.get(f"{BASE}/projects/{pid}/access", headers={**h_owner, **LINK})
    assert mine.status_code == 200, mine.text
    assert mine.json() == {"can_accept": True, "currency": "EUR", "lock": None}
    # Not a member: the project is not visible to a plain editor.
    assert (await client.get(f"{BASE}/projects/{pid}/access", headers={**h_editor, **LINK})).status_code in (403, 404)
    tok = {"Authorization": f"Bearer {await _token(client, h_owner, pid)}"}
    await client.post(f"{BASE}/projects/{pid}/lock", headers=tok)
    seen = (await client.get(f"{BASE}/projects/{pid}/access", headers={**h_owner, **LINK})).json()
    assert seen["lock"]["mine"] is True
    # Through a link token nobody can accept, whatever their role.
    via = (await client.get(f"{BASE}/projects/{pid}/access", headers=tok)).json()
    assert via["can_accept"] is False


async def test_open_in_editor_carries_the_project_and_revision_and_stays_in_scope(client):
    from .ddcrev import example_rows, package

    uid, h = await make_user(client)
    pid = await make_project(uid, name="Haus Nord")
    stranger, h_stranger = await make_user(client)
    other = await make_project(stranger, name="Fremd")
    tok = await _token(client, h, pid)
    auth = {"Authorization": f"Bearer {tok}", **LINK}
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=auth)).status_code == 200
    data, m = package(pid, example_rows())
    up = await client.post(f"{BASE}/projects/{pid}/revisions", headers=auth, files={"package": ("m.ddcrev", data)})
    assert up.status_code == 201, up.text
    rid = up.json()["revision_id"]

    r = await client.post(
        f"{BASE}/link/code", json={"project_id": str(pid), "action": "open", "revision_id": rid}, headers=h
    )
    assert r.status_code == 200, r.text
    link = r.json()
    assert (link["action"], link["project_id"], link["project_name"], link["revision_id"]) == (
        "open",
        str(pid),
        "Haus Nord",
        rid,
    )
    assert link["erp_url"].startswith("http")
    x = await client.post(f"{BASE}/link/exchange", json={"code": link["code"], "client": {"name": "desk"}})
    opened = {"Authorization": f"Bearer {x.json()['token']}", **LINK}
    assert x.json()["project_id"] == str(pid)
    ctx = (await client.get(f"{BASE}/projects/{pid}/context", headers=opened)).json()
    assert ctx["latest_revision"] == {"revision_id": rid, "number": 1, "status": "shared"}
    listed = (await client.get(f"{BASE}/revisions/{rid}", headers=opened)).json()["manifest"]["files"]
    path = next(f["path"] for f in listed if f["path"].endswith(".parquet"))
    assert (await client.get(f"{BASE}/revisions/{rid}/files/{path}", headers=opened)).status_code == 200

    # A revision of this project cannot be opened from another project, nor by someone without access.
    wrong = await client.post(
        f"{BASE}/link/code", json={"project_id": str(other), "action": "open", "revision_id": rid}, headers=h_stranger
    )
    assert wrong.status_code == 404
    foreign = await client.post(
        f"{BASE}/link/code", json={"project_id": str(pid), "action": "open", "revision_id": rid}, headers=h_stranger
    )
    assert foreign.status_code in (403, 404)
    assert (await client.get(f"{BASE}/projects/{other}/context", headers=opened)).status_code == 404
