# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The MCP endpoint end to end: handshake, tool listing, permissions, proposals, revocation, limits, audit.

The authorisation cases carry the weight. A token must never reach further than
its owner: another person's project answers like a missing one, a read-only
token cannot propose, a general API key cannot speak MCP, and a revoked token
or an owner who switched MCP off is refused before any tool runs. A proposal
must leave the domain table untouched and land as a pending action that the
person's review view lists.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.core.audit_log import ActivityLog
from app.modules.boq.models import BOQ, Position
from app.modules.erp_chat.models import ChatAction
from tests.modules.mcp.conftest import (
    API_PREFIX,
    PROTOCOL_VERSION,
    auth,
    build_app,
    enable_mcp,
    http_client,
    issue_token,
    make_project,
    make_user,
    rpc,
)

URL = f"{API_PREFIX}/"


async def _owner_with_token(session, *, role: str = "editor", can_propose: bool = True):
    user = await make_user(session, role=role)
    await enable_mcp(session, user.id)
    token, token_id = await issue_token(session, user.id, can_propose=can_propose)
    return user, token, token_id


def _tool_names(response) -> set[str]:
    return {t["name"] for t in response.json()["result"]["tools"]}


# ── Handshake ───────────────────────────────────────────────────────────────


async def test_initialize_negotiates_the_version_and_declares_tools_only(session) -> None:
    _user, token, _ = await _owner_with_token(session)
    async with http_client(build_app(session)) as client:
        resp = await client.post(
            URL,
            json=rpc(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            ),
            headers=auth(token),
        )
        assert resp.status_code == 200, resp.text
        result = resp.json()["result"]
        assert result["protocolVersion"] == PROTOCOL_VERSION
        assert result["capabilities"] == {"tools": {"listChanged": False}}
        assert result["serverInfo"]["name"] == "openconstructionerp"
        assert "propose_" in result["instructions"]
        assert "mcp-session-id" not in {k.lower() for k in resp.headers}

        initialized = await client.post(URL, json=rpc("notifications/initialized", msg_id=None), headers=auth(token))
        assert initialized.status_code == 202
        assert initialized.content == b""

        ping = await client.post(URL, json=rpc("ping", msg_id="p"), headers=auth(token))
        assert ping.json() == {"jsonrpc": "2.0", "id": "p", "result": {}}


async def test_the_endpoint_answers_without_a_trailing_slash_and_refuses_get(session) -> None:
    _user, token, _ = await _owner_with_token(session)
    async with http_client(build_app(session)) as client:
        resp = await client.post(API_PREFIX, json=rpc("ping"), headers=auth(token))
        assert resp.status_code == 200
        stream = await client.get(URL, headers=auth(token))
        assert stream.status_code == 405
        assert stream.headers["allow"] == "POST"


async def test_unsupported_protocol_header_parse_errors_and_foreign_origins_are_refused(session) -> None:
    _user, token, _ = await _owner_with_token(session)
    async with http_client(build_app(session)) as client:
        old = await client.post(URL, json=rpc("ping"), headers={**auth(token), "MCP-Protocol-Version": "1999-01-01"})
        assert old.status_code == 400
        broken = await client.post(
            URL, content=b"{not json", headers={**auth(token), "Content-Type": "application/json"}
        )
        assert broken.status_code == 400
        assert broken.json()["error"]["code"] == -32700
        foreign = await client.post(URL, json=rpc("ping"), headers={**auth(token), "Origin": "https://evil.example"})
        assert foreign.status_code == 403


# ── Authentication ──────────────────────────────────────────────────────────


async def test_missing_unknown_and_general_purpose_keys_are_refused(session) -> None:
    from app.config import get_settings
    from app.modules.users.schemas import APIKeyCreate
    from app.modules.users.service import UserService

    user = await make_user(session)
    await enable_mcp(session, user.id)
    general = await UserService(session, get_settings()).create_api_key(user.id, APIKeyCreate(name="CI key"))
    async with http_client(build_app(session)) as client:
        none = await client.post(URL, json=rpc("ping"))
        assert none.status_code == 401
        assert none.headers["www-authenticate"].startswith("Bearer")
        unknown = await client.post(URL, json=rpc("ping"), headers=auth("oe_not-a-real-token"))
        assert unknown.status_code == 401
        wrong_kind = await client.post(URL, json=rpc("ping"), headers={"X-API-Key": general.key})
        assert wrong_kind.status_code == 403
        assert wrong_kind.json()["error"]["data"]["code"] == "not_an_mcp_token"


async def test_a_token_stops_working_when_mcp_is_switched_off_or_the_token_is_revoked(session) -> None:
    user, token, token_id = await _owner_with_token(session)
    async with http_client(build_app(session, caller_id=user.id)) as client:
        assert (await client.post(URL, json=rpc("ping"), headers=auth(token))).status_code == 200

        off = await client.put(f"{API_PREFIX}/settings/", json={"enabled": False})
        assert off.status_code == 200 and off.json()["enabled"] is False
        disabled = await client.post(URL, json=rpc("ping"), headers=auth(token))
        assert disabled.status_code == 403
        assert disabled.json()["error"]["data"]["code"] == "mcp_disabled"

        await client.put(f"{API_PREFIX}/settings/", json={"enabled": True})
        revoked = await client.delete(f"{API_PREFIX}/tokens/{token_id}/")
        assert revoked.status_code == 204
        after = await client.post(URL, json=rpc("ping"), headers=auth(token))
        assert after.status_code == 401
        listed = (await client.get(f"{API_PREFIX}/tokens/")).json()
        assert [t["is_active"] for t in listed] == [False]


async def test_issued_tokens_declare_only_mcp_scopes_so_rest_key_routes_refuse_them(session) -> None:
    from app.dependencies import key_scopes_allow
    from app.modules.users.models import APIKey

    _user, _token, token_id = await _owner_with_token(session)
    key = await session.get(APIKey, uuid.UUID(token_id))
    assert sorted(key.permissions) == ["mcp.access", "mcp.propose"]
    # RequirePermissionOrApiKey narrows by the key's declared list, so no REST permission passes.
    assert key_scopes_allow(key.permissions, "inbound.write") is False


# ── Tool listing and permissions ────────────────────────────────────────────


async def test_tools_list_shows_read_tools_and_proposals_only_to_a_proposing_token(session) -> None:
    _user, token, _ = await _owner_with_token(session, can_propose=True)
    _reader, read_token, _ = await _owner_with_token(session, can_propose=False)
    async with http_client(build_app(session)) as client:
        full = _tool_names(await client.post(URL, json=rpc("tools/list"), headers=auth(token)))
        assert {"list_projects", "get_boq", "get_schedule", "search_cost_database", "list_documents"} <= full
        assert {"get_validation_results", "get_site_issues_summary"} <= full
        assert "propose_create_task" in full

        read_only = _tool_names(await client.post(URL, json=rpc("tools/list"), headers=auth(read_token)))
        assert "list_projects" in read_only
        assert not any(name.startswith("propose_") for name in read_only)

        tools = (await client.post(URL, json=rpc("tools/list"), headers=auth(token))).json()["result"]["tools"]
        task = next(t for t in tools if t["name"] == "propose_create_task")
        assert {"confidence", "rationale", "title"} <= set(task["inputSchema"]["required"])
        assert task["annotations"]["readOnlyHint"] is False
        boq = next(t for t in tools if t["name"] == "get_boq")
        assert boq["annotations"]["readOnlyHint"] is True


async def test_a_role_without_the_read_permission_sees_no_tool_and_is_denied(session) -> None:
    _user, token, _ = await _owner_with_token(session, role="nobody")
    async with http_client(build_app(session)) as client:
        names = _tool_names(await client.post(URL, json=rpc("tools/list"), headers=auth(token)))
        assert "get_boq" not in names
        call = await client.post(
            URL,
            json=rpc("tools/call", {"name": "get_boq", "arguments": {"project_id": str(uuid.uuid4())}}),
            headers=auth(token),
        )
        result = call.json()["result"]
        assert result["isError"] is True
        assert result["structuredContent"]["error"] == "permission_denied"


async def test_another_persons_project_answers_like_a_missing_one(session) -> None:
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    _stranger, token, _ = await _owner_with_token(session)
    async with http_client(build_app(session)) as client:
        for name in ("get_boq", "get_schedule", "list_documents", "get_site_issues_summary", "get_project_summary"):
            resp = await client.post(
                URL,
                json=rpc("tools/call", {"name": name, "arguments": {"project_id": str(project.id)}}),
                headers=auth(token),
            )
            result = resp.json()["result"]
            assert result["isError"] is True, name
            assert result["structuredContent"]["error"] == "project_not_found", name

        projects = await client.post(
            URL, json=rpc("tools/call", {"name": "list_projects", "arguments": {}}), headers=auth(token)
        )
        listed = projects.json()["result"]["structuredContent"]["projects"]
        assert str(project.id) not in {p["id"] for p in listed}


async def test_unknown_tools_and_bad_arguments_are_protocol_errors(session) -> None:
    _user, token, _ = await _owner_with_token(session)
    async with http_client(build_app(session)) as client:
        unknown = await client.post(URL, json=rpc("tools/call", {"name": "drop_database"}), headers=auth(token))
        assert unknown.json()["error"]["code"] == -32602
        bad = await client.post(URL, json=rpc("tools/call", {"name": "get_boq", "arguments": "x"}), headers=auth(token))
        assert bad.json()["error"]["code"] == -32602


# ── Reading ─────────────────────────────────────────────────────────────────


async def test_get_boq_returns_positions_and_totals_as_decimal_strings(session) -> None:
    user, token, _ = await _owner_with_token(session)
    project = await make_project(session, user.id, name="Riverside")
    boq = BOQ(project_id=project.id, name="Main bill")
    session.add(boq)
    await session.flush()
    session.add(
        Position(
            boq_id=boq.id,
            ordinal="01.001",
            description="Concrete wall",
            unit="m3",
            quantity="12.5",
            unit_rate="180",
            total="2250",
        )
    )
    await session.flush()
    async with http_client(build_app(session)) as client:
        resp = await client.post(
            URL,
            json=rpc("tools/call", {"name": "get_boq", "arguments": {"project_id": str(project.id)}}),
            headers=auth(token),
        )
        result = resp.json()["result"]
        assert result["isError"] is False, result
        data = result["structuredContent"]
        assert data["currency"] == "EUR"
        assert data["boq"]["name"] == "Main bill"
        position = data["boq"]["positions"][0]
        assert position["description"] == "Concrete wall"
        assert isinstance(position["total"], str)
        assert result["content"][0]["type"] == "text"
        assert "Main bill" in result["content"][0]["text"]


# ── Proposals ───────────────────────────────────────────────────────────────


async def test_a_proposal_is_stored_pending_with_confidence_and_rationale_and_writes_nothing_else(session) -> None:
    from app.modules.tasks.models import Task

    user, token, _ = await _owner_with_token(session)
    project = await make_project(session, user.id)
    tasks_before = (await session.execute(select(func.count(Task.id)))).scalar_one()
    async with http_client(build_app(session, caller_id=user.id)) as client:
        resp = await client.post(
            URL,
            json=rpc(
                "tools/call",
                {
                    "name": "propose_create_task",
                    "arguments": {
                        "project_id": str(project.id),
                        "title": "Check formwork before the pour",
                        "confidence": 0.8,
                        "rationale": "Pour is scheduled for Monday",
                    },
                },
            ),
            headers=auth(token),
        )
        result = resp.json()["result"]
        assert result["isError"] is False, result
        action_id = result["structuredContent"]["action_id"]
        assert result["structuredContent"]["status"] == "proposed"
        assert "NOT saved" in result["content"][0]["text"]

    action = await session.get(ChatAction, uuid.UUID(action_id))
    assert action is not None
    assert action.status == "proposed"
    assert action.source == "mcp"
    assert action.session_id is None
    assert action.confidence == 0.8
    assert action.rationale == "Pour is scheduled for Monday"
    assert action.requested_by == user.id
    assert (await session.execute(select(func.count(Task.id)))).scalar_one() == tasks_before


async def test_proposals_need_confidence_and_rationale_and_a_proposing_token(session) -> None:
    user, token, _ = await _owner_with_token(session)
    _reader, read_token, _ = await _owner_with_token(session, can_propose=False)
    project = await make_project(session, user.id)
    args = {"project_id": str(project.id), "title": "Order rebar"}
    async with http_client(build_app(session)) as client:
        missing = await client.post(
            URL, json=rpc("tools/call", {"name": "propose_create_task", "arguments": args}), headers=auth(token)
        )
        assert missing.json()["result"]["isError"] is True
        assert missing.json()["result"]["structuredContent"]["error"] == "invalid_arguments"

        refused = await client.post(
            URL,
            json=rpc(
                "tools/call",
                {"name": "propose_create_task", "arguments": {**args, "confidence": 0.5, "rationale": "x"}},
            ),
            headers=auth(read_token),
        )
        assert refused.json()["result"]["structuredContent"]["error"] == "proposals_not_allowed"
    count = (await session.execute(select(func.count(ChatAction.id)).where(ChatAction.source == "mcp"))).scalar_one()
    assert count == 0


async def test_a_proposal_for_a_foreign_project_is_refused(session) -> None:
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    _stranger, token, _ = await _owner_with_token(session)
    async with http_client(build_app(session)) as client:
        resp = await client.post(
            URL,
            json=rpc(
                "tools/call",
                {
                    "name": "propose_create_task",
                    "arguments": {"project_id": str(project.id), "title": "x", "confidence": 0.9, "rationale": "y"},
                },
            ),
            headers=auth(token),
        )
        assert resp.json()["result"]["isError"] is True
    assert (await session.execute(select(func.count(ChatAction.id)))).scalar_one() == 0


# ── Rate limiting and audit ─────────────────────────────────────────────────


async def test_calls_over_the_budget_are_refused_with_429(session) -> None:
    user = await make_user(session)
    await enable_mcp(session, user.id, rate_limit=2)
    token, _ = await issue_token(session, user.id)
    call = rpc("tools/call", {"name": "list_projects", "arguments": {}})
    async with http_client(build_app(session)) as client:
        assert (await client.post(URL, json=call, headers=auth(token))).status_code == 200
        assert (await client.post(URL, json=call, headers=auth(token))).status_code == 200
        third = await client.post(URL, json=call, headers=auth(token))
        assert third.status_code == 429
        assert third.json()["error"]["code"] == -32001
        # The budget counts tool calls; the handshake still works.
        assert (await client.post(URL, json=rpc("ping"), headers=auth(token))).status_code == 200


async def test_every_tool_call_is_audited_and_listed_for_its_owner(session) -> None:
    user, token, _ = await _owner_with_token(session)
    async with http_client(build_app(session, caller_id=user.id)) as client:
        await client.post(URL, json=rpc("tools/call", {"name": "list_projects", "arguments": {}}), headers=auth(token))
        await client.post(
            URL,
            json=rpc("tools/call", {"name": "get_boq", "arguments": {"project_id": str(uuid.uuid4())}}),
            headers=auth(token),
        )
        calls = (await client.get(f"{API_PREFIX}/calls/")).json()
    assert [c["tool"] for c in calls] == ["get_boq", "list_projects"]
    assert [c["outcome"] for c in calls] == ["denied", "ok"]
    rows = (
        (await session.execute(select(ActivityLog).where(ActivityLog.module == "mcp", ActivityLog.actor_id == user.id)))
        .scalars()
        .all()
    )
    tool_rows = [r for r in rows if r.entity_type == "mcp_tool_call"]
    assert len(tool_rows) == 2
    assert all(r.metadata_["argument_names"] in ([], ["project_id"]) for r in tool_rows)
    assert {r.metadata_["token_prefix"] for r in tool_rows} == {token[:12]}
