"""Link status in the ERP: which editors hold a token, when they last called, what waits for a decision; revoke."""

from __future__ import annotations

import uuid

import pytest

from .conftest import LINK, make_project, make_user
from .ddcrev import example_rows, package, sha

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/design"


async def _token(client, headers, pid, name="desk") -> dict[str, str]:
    r = await client.post(f"{BASE}/link/code", json={"project_id": str(pid), "action": "new"}, headers=headers)
    x = await client.post(
        f"{BASE}/link/exchange", json={"code": r.json()["code"], "client": {"name": name, "version": "1.2"}}
    )
    assert x.status_code == 200, x.text
    return {"Authorization": f"Bearer {x.json()['token']}", **LINK}


async def test_status_lists_editors_last_call_and_pending_revision(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    empty = await client.get(f"{BASE}/projects/{pid}/link/status", headers=h)
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"editors": [], "pending_revisions": 0, "last_revision_at": None, "last_revision": None}

    tok = await _token(client, h, pid)
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=tok)).status_code == 200
    data, _ = package(pid, example_rows())
    up = await client.post(f"{BASE}/projects/{pid}/revisions", headers=tok, files={"package": ("m.ddcrev", data)})
    assert up.status_code == 201, up.text

    body = (await client.get(f"{BASE}/projects/{pid}/link/status", headers=h)).json()
    assert body["pending_revisions"] == 1 and body["last_revision_at"] is not None
    trace = body["last_revision"]
    assert trace["revision_id"] == up.json()["revision_id"] and trace["number"] == 1 and trace["status"] == "shared"
    assert trace["package_sha256"] == sha(data) and trace["author"] and trace["source_kind"]
    [ed] = body["editors"]
    assert ed["client_name"] == "desk" and ed["client_version"] == "1.2" and ed["mine"] is True
    assert ed["last_used_at"] is not None and ed["expires_at"]
    assert "token_hash" not in ed


async def test_a_link_token_cannot_read_or_revoke_link_status(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    tok = await _token(client, h, pid)
    assert (await client.get(f"{BASE}/projects/{pid}/link/status", headers=tok)).status_code == 403
    eid = (await client.get(f"{BASE}/projects/{pid}/link/status", headers=h)).json()["editors"][0]["id"]
    assert (await client.delete(f"{BASE}/projects/{pid}/link/editors/{eid}", headers=tok)).status_code == 403


async def test_revoke_cuts_the_editor_off_and_stays_in_its_project(client):
    owner, h_owner = await make_user(client)
    stranger, h_stranger = await make_user(client)
    pid = await make_project(owner)
    p_other = await make_project(stranger, name="Other")
    tok = await _token(client, h_owner, pid)
    eid = (await client.get(f"{BASE}/projects/{pid}/link/status", headers=h_owner)).json()["editors"][0]["id"]
    # Another tenant's user cannot see or revoke, not even through their own project id (IDOR).
    assert (await client.get(f"{BASE}/projects/{pid}/link/status", headers=h_stranger)).status_code in (403, 404)
    assert (await client.delete(f"{BASE}/projects/{p_other}/link/editors/{eid}", headers=h_stranger)).status_code == 404
    assert (await client.get(f"{BASE}/projects/{pid}/context", headers=tok)).status_code == 200

    gone = await client.delete(f"{BASE}/projects/{pid}/link/editors/{eid}", headers=h_owner)
    assert gone.status_code == 204, gone.text
    assert (await client.get(f"{BASE}/projects/{pid}/context", headers=tok)).status_code == 401
    after = (await client.get(f"{BASE}/projects/{pid}/link/status", headers=h_owner)).json()
    assert after["editors"] == []


async def test_a_member_sees_only_their_own_editor_a_manager_sees_all(client):
    from .test_drafts import _member

    owner, h_owner = await make_user(client)
    member, h_member = await make_user(client)
    pid = await make_project(owner)
    await _member(pid, member)
    await _token(client, h_owner, pid, name="owner-desk")
    await _token(client, h_member, pid, name="member-desk")
    mine = (await client.get(f"{BASE}/projects/{pid}/link/status", headers=h_member)).json()["editors"]
    assert [e["client_name"] for e in mine] == ["member-desk"]
    every = (await client.get(f"{BASE}/projects/{pid}/link/status", headers=h_owner)).json()["editors"]
    assert {e["client_name"] for e in every} == {"owner-desk", "member-desk"}
    # A member cannot unlink the owner's editor; the error names a code the UI translates.
    owners = next(e["id"] for e in every if e["client_name"] == "owner-desk")
    denied = await client.delete(f"{BASE}/projects/{pid}/link/editors/{owners}", headers=h_member)
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "unlink_not_allowed"


async def test_link_status_errors_are_coded(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    tok = await _token(client, h, pid)
    r = await client.get(f"{BASE}/projects/{pid}/link/status", headers=tok)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "link_status_erp_only"
    gone = await client.delete(f"{BASE}/projects/{pid}/link/editors/{uuid.uuid4()}", headers=h)
    assert gone.status_code == 404 and gone.json()["detail"]["code"] == "editor_link_not_found"
