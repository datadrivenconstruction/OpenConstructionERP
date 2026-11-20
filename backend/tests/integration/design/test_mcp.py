"""R15: the Design MCP entry point. Off by default, MCP tokens only, foreign projects look missing, writes are
pending proposals until a person applies them, and the person's AI key never leaves the server."""

from __future__ import annotations

import json
import logging
import uuid
from types import SimpleNamespace

import pytest

from .conftest import make_project, make_user
from .ddcrev import example_rows, package
from .test_ai_profile import SECRET, _provider, _save_settings
from .test_design_revisions import BASE, _linked_project, _upload

pytestmark = pytest.mark.asyncio

MCP = f"{BASE}/mcp"
DESIGN_READ = {
    "design_get_job",
    "design_get_project",
    "design_get_brief",
    "design_list_revisions",
    "design_get_revision_impact",
    "design_get_estimate",
    "design_extract_brief_draft",
}
DESIGN_PROPOSE = {
    "propose_design_generation",
    "propose_design_brief_values",
    "propose_design_revision_decision",
    "propose_design_estimate_rules",
}


@pytest.fixture(autouse=True)
def _mcp_on(monkeypatch):
    from app.modules.design import mcp
    from app.modules.design.mcp_actions import register_specs
    from app.modules.mcp.auth import tool_call_limiter

    register_specs()
    tool_call_limiter.reset()
    monkeypatch.setattr(mcp, "get_design_settings", lambda: SimpleNamespace(mcp_enabled=True))


async def _mcp_token(user_id: uuid.UUID, *, can_propose: bool = True, enable: bool = True) -> str:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.mcp.models import McpSettings
    from app.modules.mcp.schemas import McpTokenCreate
    from app.modules.mcp.service import McpService

    async with async_session_factory() as s:
        if enable and (await s.execute(select(McpSettings).where(McpSettings.user_id == user_id))).first() is None:
            s.add(McpSettings(user_id=user_id, enabled=True, rate_limit_per_minute=600))
        created = await McpService(s).create_token(
            user_id, McpTokenCreate(name=f"agent-{uuid.uuid4().hex[:8]}", can_propose=can_propose)
        )
        await s.commit()
    return created.token


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _rpc(client, token, method, params=None, *, headers=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return await client.post(MCP, json=body, headers=headers if headers is not None else _h(token))


async def _call(client, token, name, **arguments):
    r = await _rpc(client, token, "tools/call", {"name": name, "arguments": arguments})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def _apply_path(app, action_id) -> str:
    """The Changes view's Apply (module oe_erp_chat, mounted at /api/v1/erp-chat)."""
    return f"/api/v1/erp-chat/actions/{action_id}/apply/"


async def test_off_by_default(client, monkeypatch):
    from app.modules.design import mcp
    from app.modules.design.settings import DesignSettings

    monkeypatch.setattr(mcp, "get_design_settings", lambda: DesignSettings())
    uid, _ = await make_user(client)
    r = await _rpc(client, await _mcp_token(uid), "tools/list")
    assert r.status_code == 404


async def test_auth_required(client):
    uid, h = await make_user(client)
    assert (await _rpc(client, "", "tools/list", headers={})).status_code == 401
    assert (await _rpc(client, "", "tools/list", headers=h)).status_code == 401  # an ERP session is not an MCP token
    assert (await _rpc(client, "oe_unknown_token_value", "tools/list")).status_code == 401
    switched_off = await _mcp_token(uid, enable=False)
    r = await _rpc(client, switched_off, "tools/list")
    assert r.status_code == 403 and r.json()["error"]["data"]["code"] == "mcp_disabled"


async def test_tools_list(client):
    uid, _ = await make_user(client)
    tools = {t["name"]: t for t in (await _rpc(client, await _mcp_token(uid), "tools/list")).json()["result"]["tools"]}
    assert set(tools) >= DESIGN_READ | DESIGN_PROPOSE
    assert "list_projects" in tools  # one entry point: the core tools are there too
    assert all(tools[n]["annotations"]["readOnlyHint"] for n in DESIGN_READ)
    assert not any(tools[n]["annotations"]["readOnlyHint"] for n in DESIGN_PROPOSE)
    assert {"confidence", "rationale"} <= set(tools["propose_design_brief_values"]["inputSchema"]["required"])
    reader = await _mcp_token(uid, can_propose=False)
    names = {t["name"] for t in (await _rpc(client, reader, "tools/list")).json()["result"]["tools"]}
    assert names >= DESIGN_READ and not names & DESIGN_PROPOSE


async def test_cross_project_access_denied(client):
    uid, h, pid, tok = await _linked_project(client)
    data, _ = package(pid, example_rows())
    rev = (await _upload(client, pid, tok, data)).json()
    stranger, _ = await make_user(client)
    token = await _mcp_token(stranger)
    for name, args in (
        ("design_get_project", {"project_id": str(pid)}),
        ("design_get_brief", {"project_id": str(pid)}),
        ("design_get_estimate", {"project_id": str(pid)}),
        ("design_list_revisions", {"project_id": str(pid)}),
        ("design_get_revision_impact", {"revision_id": rev["revision_id"]}),
    ):
        res = await _call(client, token, name, **args)
        assert res["isError"], name
        assert res["structuredContent"]["error"] in ("project_not_found", "revision_not_found"), name
    res = await _call(
        client,
        token,
        "propose_design_brief_values",
        project_id=str(pid),
        base_version=0,
        values=[{"pointer": "/country", "value": "DE"}],
        confidence=0.9,
        rationale="test",
    )
    assert res["isError"]
    res = await _call(
        client,
        token,
        "propose_design_revision_decision",
        revision_id=rev["revision_id"],
        decision="accept",
        confidence=0.9,
        rationale="test",
    )
    assert res["isError"]
    # Unknown ids answer exactly like foreign ones.
    res = await _call(client, token, "design_get_project", project_id=str(uuid.uuid4()))
    assert res["structuredContent"]["error"] == "project_not_found"


async def test_brief_proposal_is_pending_until_a_person_applies(client, app_instance):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    token = await _mcp_token(uid)
    res = await _call(
        client,
        token,
        "propose_design_brief_values",
        project_id=str(pid),
        base_version=0,
        values=[{"pointer": "/country", "value": "DE"}, {"pointer": "/massing/floors_above", "value": 5}],
        confidence=0.8,
        rationale="From the description.",
    )
    assert not res["isError"], res
    action_id = res["structuredContent"]["action_id"]
    assert res["structuredContent"]["status"] == "proposed"
    assert (await client.get(f"{BASE}/projects/{pid}/brief", headers=h)).status_code == 404  # nothing written
    # The token cannot apply its own proposal: the apply route takes a person's session only.
    path = _apply_path(app_instance, action_id)
    assert (await client.post(path, headers=_h(token))).status_code == 401
    r = await client.post(path, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "applied", r.text
    # An incomplete brief is saved with the values still proposed: confirming needs a complete brief, as in the form.
    brief = (await client.get(f"{BASE}/projects/{pid}/brief", headers=h)).json()
    assert brief["version"] == 1 and brief["country"] == "DE" and brief["massing"]["floors_above"] == 5
    assert brief["provenance"]["/country"]["status"] == "proposed"
    # A proposal based on an old version is refused, not merged.
    res = await _call(
        client,
        token,
        "propose_design_brief_values",
        project_id=str(pid),
        base_version=0,
        values=[{"pointer": "/country", "value": "FR"}],
        confidence=0.5,
        rationale="x",
    )
    assert res["isError"] and res["structuredContent"]["error"] == "stale_brief"
    rest = [
        {"pointer": "/country", "value": "DE"},
        {"pointer": "/massing/floors_above", "value": 5},
        {"pointer": "/locale", "value": "de"},
        {"pointer": "/use/category", "value": "residential_multi"},
        {"pointer": "/depth_level", "value": "D2"},
        {
            "pointer": "/programme/units",
            "value": [
                {"name": "2-Zimmer", "count": 10, "area_m2": 52, "rooms": [{"kind": "living"}, {"kind": "kitchen"}]}
            ],
        },
    ]
    res = await _call(
        client,
        token,
        "propose_design_brief_values",
        project_id=str(pid),
        base_version=1,
        values=rest,
        confidence=0.8,
        rationale="Completes the brief.",
    )
    assert not res["isError"], res
    assert (await client.get(f"{BASE}/projects/{pid}/brief", headers=h)).json()["version"] == 1
    r = await client.post(_apply_path(app_instance, res["structuredContent"]["action_id"]), headers=h)
    assert r.status_code == 200 and r.json()["status"] == "applied", r.text
    brief = (await client.get(f"{BASE}/projects/{pid}/brief", headers=h)).json()
    assert brief["version"] == 3
    for item in rest:
        entry = brief["provenance"][item["pointer"]]
        assert entry["status"] == "confirmed" and entry["confirmed_by"] == str(uid), item["pointer"]
    versions = (await client.get(f"{BASE}/projects/{pid}/brief/versions", headers=h)).json()
    assert [v["action"] for v in versions] == ["confirm", "save", "save"]
    read = await _call(client, token, "design_get_brief", project_id=str(pid))
    assert read["structuredContent"]["version"] == 3


async def test_revision_decision_is_pending_until_a_manager_applies(client, app_instance):
    uid, h, pid, tok = await _linked_project(client)
    data, _ = package(pid, example_rows())
    rev = (await _upload(client, pid, tok, data)).json()
    token = await _mcp_token(uid)
    listed = await _call(client, token, "design_list_revisions", project_id=str(pid))
    assert listed["structuredContent"]["revisions"][0]["status"] == "shared"
    res = await _call(
        client,
        token,
        "propose_design_revision_decision",
        revision_id=rev["revision_id"],
        decision="accept",
        confidence=0.7,
        rationale="Matches the brief.",
    )
    assert not res["isError"], res
    assert (await client.get(f"{BASE}/revisions/{rev['revision_id']}", headers=h)).json()["status"] == "shared"
    r = await client.post(_apply_path(app_instance, res["structuredContent"]["action_id"]), headers=h)
    assert r.status_code == 200 and r.json()["status"] == "applied", r.text
    assert (await client.get(f"{BASE}/revisions/{rev['revision_id']}", headers=h)).json()["status"] == "published"
    again = await _call(
        client,
        token,
        "propose_design_revision_decision",
        revision_id=rev["revision_id"],
        decision="reject",
        comment="no",
        confidence=0.5,
        rationale="x",
    )
    assert again["isError"] and again["structuredContent"]["error"] == "not_pending"


async def test_estimate_rules_proposal_needs_a_manager(client, app_instance):
    owner, h_owner = await make_user(client)
    pid = await make_project(owner)
    token = await _mcp_token(owner)
    res = await _call(
        client,
        token,
        "propose_design_estimate_rules",
        project_id=str(pid),
        country="DE",
        confidence=0.9,
        rationale="German project.",
    )
    assert not res["isError"], res
    assert (await client.get(f"{BASE}/projects/{pid}/estimate/rules", headers=h_owner)).json() == []
    r = await client.post(_apply_path(app_instance, res["structuredContent"]["action_id"]), headers=h_owner)
    assert r.status_code == 200 and r.json()["status"] == "applied", r.text
    assert len((await client.get(f"{BASE}/projects/{pid}/estimate/rules", headers=h_owner)).json()) > 0


async def test_ai_key_never_in_responses_or_logs(client, caplog):
    uid, h, pid, tok = await _linked_project(client)
    await _save_settings(uid, _provider())
    data, _ = package(pid, example_rows())
    rev = (await _upload(client, pid, tok, data)).json()
    token = await _mcp_token(uid)
    caplog.set_level(logging.DEBUG)
    texts = [(await _rpc(client, token, "tools/list")).text]
    for name, args in (
        ("design_get_project", {"project_id": str(pid)}),
        ("design_get_brief", {"project_id": str(pid)}),
        ("design_list_revisions", {"project_id": str(pid)}),
        ("design_get_revision_impact", {"revision_id": rev["revision_id"]}),
        ("design_get_estimate", {"project_id": str(pid)}),
        ("design_extract_brief_draft", {"project_id": str(pid), "text": "Wohnhaus, 5 Geschosse", "use_ai": False}),
    ):
        r = await _rpc(client, token, "tools/call", {"name": name, "arguments": args})
        assert r.status_code == 200 and not r.json()["result"]["isError"], (name, r.text)
        texts.append(r.text)
    project = json.loads(texts[1])["result"]["structuredContent"]
    assert "ai" not in project and project["project"]["id"] == str(pid)
    assert all(SECRET not in t for t in texts)
    assert SECRET not in caplog.text
    from sqlalchemy import select

    from app.core.audit_log import ActivityLog
    from app.database import async_session_factory

    async with async_session_factory() as s:
        rows = (
            (await s.execute(select(ActivityLog).where(ActivityLog.module == "mcp", ActivityLog.actor_id == uid)))
            .scalars()
            .all()
        )
    assert len(rows) >= 6
    assert all(SECRET not in json.dumps(r.metadata_ or {}, default=str) for r in rows)
