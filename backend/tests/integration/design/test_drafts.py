"""Browser editor drafts: autosave per person, quantities and estimate at once, one action to a revision, rights."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from .conftest import make_project, make_user
from .ddcrev import example_rows, package, sha
from .test_design_revisions import BASE, WALL, _rev2_rows, _token, _upload

pytestmark = pytest.mark.asyncio


def _none(r) -> bool:
    """No draft: 200 with null."""
    return r.status_code == 200 and r.json() is None


async def _member(pid: uuid.UUID, uid: uuid.UUID) -> None:
    from app.database import async_session_factory
    from app.modules.teams.models import Team, TeamMembership

    async with async_session_factory() as s:
        team = Team(project_id=pid, name="Design")
        s.add(team)
        await s.flush()
        s.add(TeamMembership(team_id=team.id, user_id=uid))
        await s.commit()


async def _put(client, pid, headers, data: bytes):
    return await client.put(
        f"{BASE}/projects/{pid}/draft", headers=headers, files={"package": ("draft.ddcrev", data, "application/zip")}
    )


async def _project_with_estimate(client):
    owner, h = await make_user(client)
    pid = await make_project(owner)
    tok = await _token(client, h, pid)
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=tok)).status_code == 200
    rev1 = (await _upload(client, pid, tok, package(pid, example_rows())[0])).json()
    assert (await client.post(f"{BASE}/revisions/{rev1['revision_id']}/accept", headers=h)).status_code == 200
    assert (await client.delete(f"{BASE}/projects/{pid}/lock", headers=tok)).status_code == 204
    est = f"{BASE}/projects/{pid}/estimate"
    assert (await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=h)).status_code == 201
    assert (await client.post(f"{est}/run", headers=h)).status_code == 200
    return owner, h, pid, rev1


async def test_draft_shows_its_quantities_and_becomes_one_revision(client):
    owner, h, pid, rev1 = await _project_with_estimate(client)
    member, hm = await make_user(client)
    await _member(pid, member)
    rows = _rev2_rows()
    data, manifest = package(pid, rows, parent_id=rev1["revision_id"], parent_rows=example_rows())

    assert _none(await client.get(f"{BASE}/projects/{pid}/draft", headers=hm))
    r = await _put(client, pid, hm, data)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["revision_id"] == manifest["revision_id"] and d["package_sha256"] == sha(data)
    assert d["element_count"] == len(rows)
    lines = {ln["rule"]: ln for ln in d["estimate"]["lines"]}
    current = {
        p["rule"]: p for p in (await client.get(f"{BASE}/projects/{pid}/estimate", headers=h)).json()["positions"]
    }
    assert set(lines) == {c for c, p in current.items() if p["kind"] == "model"}  # derived rules stay in the ERP
    wall = lines["wall_ext"]
    assert WALL in wall["element_keys"] and wall["position_id"] == current["wall_ext"]["position_id"]
    assert Decimal(wall["current_quantity"]) == Decimal(current["wall_ext"]["quantity"])
    assert Decimal(wall["quantity"]) != Decimal(wall["current_quantity"])  # the longer wall is seen at once
    assert "rate_missing" in wall["flags"] and wall["total"] is None  # unpriced: no invented total
    assert Decimal(d["estimate"]["model_total"]) == 0

    got = await client.get(f"{BASE}/projects/{pid}/draft/package", headers=hm)
    assert got.content == data and got.headers["x-package-sha256"] == sha(data)
    # one draft per person: the owner sees none, the member's is kept and replaced on the next save
    assert _none(await client.get(f"{BASE}/projects/{pid}/draft", headers=h))
    assert (await _put(client, pid, hm, data)).json()["package_sha256"] == d["package_sha256"]

    made = await client.post(f"{BASE}/projects/{pid}/draft/revision", headers=hm)
    assert made.status_code == 201, made.text
    rev2 = made.json()
    assert rev2["number"] == 2 and rev2["status"] == "shared" and rev2["parent_revision_id"] == rev1["revision_id"]
    assert rev2["revision_id"] == manifest["revision_id"] and rev2["package_sha256"] == sha(data)
    assert _none(await client.get(f"{BASE}/projects/{pid}/draft", headers=hm))
    assert (await client.get(f"{BASE}/projects/{pid}/access", headers=hm)).json()["lock"] is None  # released
    # accepting stays with the manager
    assert (await client.post(f"{BASE}/revisions/{rev2['revision_id']}/accept", headers=hm)).status_code == 403
    assert (await client.post(f"{BASE}/revisions/{rev2['revision_id']}/accept", headers=h)).status_code == 200


async def test_rights_per_project_and_bad_drafts(client):
    owner, h, pid, rev1 = await _project_with_estimate(client)
    member, hm = await make_user(client)
    viewer, hv = await make_user(client, role="viewer")
    for u in (member, viewer):
        await _member(pid, u)
    data, _ = package(pid, _rev2_rows(), parent_id=rev1["revision_id"], parent_rows=example_rows())
    rights = f"{BASE}/projects/{pid}/design-rights"

    assert (await client.get(rights, headers=hm)).json() == {"edit": "members", "can_edit": True, "can_accept": False}
    assert (await _put(client, pid, hv, data)).status_code == 403  # read-only role
    assert (await client.put(rights, json={"edit": "managers"}, headers=hm)).status_code == 403
    assert (await client.put(rights, json={"edit": "anyone"}, headers=h)).status_code == 422
    assert (await client.put(rights, json={"edit": "managers"}, headers=h)).status_code == 200
    assert (await client.get(rights, headers=hm)).json()["can_edit"] is False
    assert (await _put(client, pid, hm, data)).status_code == 403
    # the desktop intake honours the same choice
    tok = await _token(client, hm, pid)
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=tok)).status_code == 200
    assert (await _upload(client, pid, tok, data)).status_code == 403
    assert (await client.delete(f"{BASE}/projects/{pid}/lock", headers=tok)).status_code == 204

    assert (await _put(client, pid, h, b"PK\x05\x06" + b"\0" * 18)).status_code == 422  # not a package
    other, _ = package(uuid.uuid4(), example_rows())
    assert (await _put(client, pid, h, other)).status_code == 422  # another project's package
    assert (await client.post(f"{BASE}/projects/{pid}/draft/revision", headers=h)).status_code == 404
    # a stale draft (the chain moved on) is refused by the intake, and the draft is kept
    assert (await _put(client, pid, h, package(pid, example_rows())[0])).status_code == 200
    assert (await client.post(f"{BASE}/projects/{pid}/draft/revision", headers=h)).status_code == 409
    assert (await client.get(f"{BASE}/projects/{pid}/draft", headers=h)).status_code == 200
    assert (await client.delete(f"{BASE}/projects/{pid}/draft", headers=h)).status_code == 204
    assert _none(await client.get(f"{BASE}/projects/{pid}/draft", headers=h))


async def test_editor_ai_choice_defaults_to_the_erp(client):
    _, h = await make_user(client)
    url = f"{BASE}/ai-choice"
    assert (await client.get(url, headers=h)).json() == {"same_as_erp": True, "preferred_model": None, "model": None}
    put = await client.put(url, json={"preferred_model": "local", "model": "small-model"}, headers=h)
    assert put.json() == {"same_as_erp": False, "preferred_model": "local", "model": "small-model"}
    assert (await client.get(url, headers=h)).json()["model"] == "small-model"
    assert (await client.put(url, json={}, headers=h)).json()["same_as_erp"] is True


async def test_editor_ai_choice_reaches_the_extraction_only_from_the_editor(client, monkeypatch):
    import app.modules.ai.ai_client as ac
    from app.database import async_session_factory
    from app.modules.design.brief_api import provider_completer

    uid, h = await make_user(client)
    await client.put(f"{BASE}/ai-choice", json={"preferred_model": "local", "model": "small-model"}, headers=h)
    asked: list = []
    used: list = []
    monkeypatch.setattr(
        ac, "resolve_provider_key_model", lambda s, p=None: (asked.append(p), ("svc", "k", "erp-model"))[1]
    )

    async def call_ai(**kw):
        used.append(kw["model"])
        return "{}"

    monkeypatch.setattr(ac, "call_ai", call_ai)
    async with async_session_factory() as s:
        for editor in (True, False):
            complete = await provider_completer(s, uid, editor=editor)
            await complete(system="s", prompt="p")
    assert asked == ["local", None] and used == ["small-model", "erp-model"]
