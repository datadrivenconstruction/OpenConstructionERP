# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""How the chat stream offers, dispatches and stores ``propose_*`` tool calls.

The model changes nothing by itself. It reads through the read tools and
proposes a change through the action registry's ``propose_*`` tools; a person
applies the change later from its card, on another request. So the stream has
to (1) put the same tool set on every wire, read at request time, (2) store a
proposal on its own session and commit it BEFORE the card's frame goes out, so
the Apply request finds the row, (3) link the turn's proposals to the stored
assistant message, committed before ``done``, and (4) keep the manager gate
for tools that write directly away from proposals, which write nothing.

The database is replaced by a recorder and the proposal service by a stand-in,
so these tests pin the stream's order of work; the PG lane covers the same
turn against a real database.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest

import app.modules.erp_chat.service as chat_service
from app.modules.erp_chat.actions import registry
from app.modules.erp_chat.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_NO_TOOLS
from app.modules.erp_chat.schemas import StreamChatRequest
from app.modules.erp_chat.service import (
    ERPChatService,
    _anthropic_tool_schema,
    _openai_tool_schema,
    _result_for_model,
    _truncate_tool_result,
)
from app.modules.erp_chat.tools import TOOL_DEFINITIONS, TOOL_HANDLER_MAP

PROPOSE_TOOL = "propose_create_task"


class _Nested:
    async def __aenter__(self) -> _Nested:
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


class _RecordingSession:
    """AsyncSession stand-in that counts commits and rollbacks and has no rows."""

    def __init__(self, *, fail_commit: bool = False) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = fail_commit

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("the database went away")
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    def begin_nested(self) -> _Nested:
        return _Nested()


class _ChatSessionRow:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.project_id = None
        self.title = "Existing title"


def _names_anthropic(tools: list[dict[str, Any]]) -> list[str]:
    return [t["name"] for t in tools]


def _names_openai(tools: list[dict[str, Any]]) -> list[str]:
    return [t["function"]["name"] for t in tools]


def _tool_use(name: str, args: dict[str, Any], tool_id: str = "tu-1") -> tuple[dict[str, Any], int]:
    return (
        {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": args}], "usage": {}},
        10,
    )


def _text(text: str) -> tuple[dict[str, Any], int]:
    return {"content": [{"type": "text", "text": text}], "usage": {}}, 5


def _proposal(action_id: str = "act-1", summary: str | None = None) -> dict[str, Any]:
    return {
        "renderer": "action_proposal",
        "data": {"id": action_id, "status": "proposed", "action_type": "task.create", "fields": []},
        "summary": summary or "Proposed 'Create task': title=Check formwork. NOT saved yet: it waits for the user.",
    }


async def _drive(
    monkeypatch: pytest.MonkeyPatch,
    rounds: list[tuple[dict[str, Any], int] | Exception],
    *,
    session: _RecordingSession | None = None,
    request: StreamChatRequest | None = None,
    propose_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one Anthropic turn against the recorder; return what every seam saw.

    ``frames`` holds ``(event, payload, commits_when_yielded)`` so a test can
    tell whether a commit happened before or after a frame left.
    """
    session = session or _RecordingSession()
    service = ERPChatService(session)  # type: ignore[arg-type]
    chat_row = _ChatSessionRow()
    persisted_id = uuid.uuid4()
    seen: dict[str, Any] = {
        "session": session,
        "chat_row": chat_row,
        "persisted_id": persisted_id,
        "proposals": [],
        "attached": [],
        "messages": [],
        "systems": [],
    }
    queue = list(rounds)

    async def _fake_anthropic(api_key: str, messages: list[dict[str, Any]], preferred_model: str | None):  # noqa: ARG001
        seen["messages"].append(json.loads(json.dumps(messages, default=str)))
        seen["systems"].append(service._system_prompt)
        step = queue.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    async def _fake_propose(_session: Any, **kwargs: Any) -> dict[str, Any]:
        seen["proposals"].append({**kwargs, "commits": session.commits})
        return propose_result or _proposal()

    class _FakeActions:
        def __init__(self, _session: Any) -> None:
            pass

        async def attach_message(self, *, batch_id: str, message_id: Any) -> int:
            seen["attached"].append({"batch_id": batch_id, "message_id": message_id, "commits": session.commits})
            return 1

    async def _fake_get_or_create(*_a: Any, **_k: Any) -> _ChatSessionRow:
        seen["created_with"] = _a
        return chat_row

    async def _fake_budget(_uid: str) -> tuple[bool, int]:
        return True, 0

    async def _fake_build(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [{"role": "user", "content": "add a task"}]

    async def _fake_resolve(_uid: str) -> tuple[str, str, str | None]:
        return "anthropic", "test-key", None

    async def _fake_persist(*_a: Any, **_k: Any) -> uuid.UUID:
        seen["persist_commits"] = session.commits
        return persisted_id

    monkeypatch.setattr(chat_service, "propose_tool_result", _fake_propose)
    monkeypatch.setattr(chat_service, "ChatActionService", _FakeActions)
    monkeypatch.setattr(service, "_call_anthropic", _fake_anthropic)
    monkeypatch.setattr(service, "get_or_create_session", _fake_get_or_create)
    monkeypatch.setattr(service, "check_daily_token_budget", _fake_budget)
    monkeypatch.setattr(service, "_build_messages", _fake_build)
    monkeypatch.setattr(service, "_resolve_ai", _fake_resolve)
    monkeypatch.setattr(service, "_persist_messages", _fake_persist)

    frames: list[tuple[str, dict[str, Any], int]] = []
    request = request or StreamChatRequest(message="add a task for the site team")
    async for chunk in service.stream_response(str(uuid.uuid4()), request):
        head, _, body = chunk.partition("\n")
        frames.append((head.removeprefix("event: "), json.loads(body.removeprefix("data: ")), session.commits))
    seen["frames"] = frames
    return seen


def _frames(seen: dict[str, Any], event: str) -> list[tuple[dict[str, Any], int]]:
    return [(payload, commits) for name, payload, commits in seen["frames"] if name == event]


# ── 1. The same tools on every wire, read per request ─────────────────────────


def test_every_wire_offers_the_read_tools_and_the_proposal_tools() -> None:
    anthropic = _names_anthropic(_anthropic_tool_schema())
    openai = _names_openai(_openai_tool_schema())

    assert anthropic == openai
    assert set(registry.tool_names()) <= set(anthropic)
    assert PROPOSE_TOOL in anthropic
    assert {t["name"] for t in TOOL_DEFINITIONS} <= set(anthropic)
    assert "create_boq_item" not in anthropic
    assert "create_boq_item" not in TOOL_HANDLER_MAP


def test_the_tool_set_is_read_from_the_registry_at_request_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """A module switched off after startup takes its tools out of the next request."""
    monkeypatch.setattr(registry, "tool_definitions", lambda: [])
    monkeypatch.setattr(registry, "openai_tool_definitions", lambda: [])

    assert _names_anthropic(_anthropic_tool_schema()) == [t["name"] for t in TOOL_DEFINITIONS]
    assert _names_openai(_openai_tool_schema()) == [t["name"] for t in TOOL_DEFINITIONS]


def test_a_broken_registry_leaves_the_read_tools_standing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> list[dict[str, Any]]:
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(registry, "tool_definitions", _boom)
    monkeypatch.setattr(registry, "openai_tool_definitions", _boom)

    assert _names_anthropic(_anthropic_tool_schema()) == [t["name"] for t in TOOL_DEFINITIONS]
    assert _names_openai(_openai_tool_schema()) == [t["name"] for t in TOOL_DEFINITIONS]


@pytest.mark.asyncio
async def test_the_anthropic_request_carries_the_proposal_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    bodies: list[dict[str, Any]] = []

    def _answer(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}], "usage": {}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        chat_service.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": httpx.MockTransport(_answer)}),
    )

    await ERPChatService(session=object())._call_anthropic("sk-ant-test", [{"role": "user", "content": "hi"}], None)  # type: ignore[arg-type]

    names = [t["name"] for t in bodies[0]["tools"]]
    assert PROPOSE_TOOL in names
    assert "create_boq_item" not in names
    assert bodies[0]["system"] == SYSTEM_PROMPT  # no turn, no context block


# ── 2. + 3. Dispatch, commit before the card, attach before done ──────────────


@pytest.mark.asyncio
async def test_a_proposal_is_committed_before_its_card_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = await _drive(
        monkeypatch,
        [_tool_use(PROPOSE_TOOL, {"title": "Check formwork on level 3"}), _text("Prepared, waiting for you.")],
    )

    [(result_frame, commits_at_card)] = _frames(seen, "tool_result")
    assert result_frame["tool"] == PROPOSE_TOOL
    assert result_frame["result"]["renderer"] == "action_proposal"
    # The proposal service ran with nothing committed yet, and the card left
    # only after the commit that makes the row visible to another request.
    assert seen["proposals"][0]["commits"] == 0
    assert commits_at_card == 1
    assert not _frames(seen, "error")


@pytest.mark.asyncio
async def test_the_proposal_is_stored_on_the_turns_chat_session_and_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    args = {"title": "Check formwork on level 3", "project_id": str(uuid.uuid4())}
    seen = await _drive(monkeypatch, [_tool_use(PROPOSE_TOOL, args), _text("Prepared.")])

    [call] = seen["proposals"]
    assert call["tool_name"] == PROPOSE_TOOL
    assert call["args"] == args
    assert call["chat_session_id"] == seen["chat_row"].id
    assert call["project_id"] is None  # no project open in the request
    assert call["batch_id"]


@pytest.mark.asyncio
async def test_the_turns_message_is_attached_and_committed_before_done(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = await _drive(
        monkeypatch,
        [
            _tool_use(PROPOSE_TOOL, {"title": "Task A"}, "tu-1"),
            _tool_use(PROPOSE_TOOL, {"title": "Task B"}, "tu-2"),
            _text("Two tasks prepared."),
        ],
    )

    batch_ids = {call["batch_id"] for call in seen["proposals"]}
    assert len(batch_ids) == 1, "one user turn is one batch"
    [attach] = seen["attached"]
    assert attach["batch_id"] in batch_ids
    assert attach["message_id"] == seen["persisted_id"]
    [(done, commits_at_done)] = _frames(seen, "done")
    assert done["message_id"] == str(seen["persisted_id"])
    # Two proposal commits, then the one that carries the messages and the link.
    assert attach["commits"] == 2
    assert commits_at_done == 3


@pytest.mark.asyncio
async def test_a_turn_without_proposals_commits_nothing_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _read(_session: Any, _args: dict[str, Any], _uid: str) -> dict[str, Any]:
        return {"renderer": "projects_grid", "data": {"projects": []}, "summary": "0 projects"}

    monkeypatch.setitem(TOOL_HANDLER_MAP, "get_all_projects", _read)
    seen = await _drive(monkeypatch, [_tool_use("get_all_projects", {}), _text("You have none.")])

    assert seen["session"].commits == 0
    assert seen["proposals"] == []
    assert seen["attached"] == []


@pytest.mark.asyncio
async def test_a_refused_proposal_is_not_committed_and_reaches_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    refusal = {
        "renderer": "error",
        "data": {"error": "boq_ambiguous", "message": "Which bill?", "options": [{"id": "b1", "name": "Shell"}]},
        "summary": "Several bills; ask the user which one.",
    }
    seen = await _drive(
        monkeypatch,
        [_tool_use(PROPOSE_TOOL, {"title": "x"}), _text("Which bill do you mean?")],
        propose_result=refusal,
    )

    assert seen["session"].commits == 0
    assert seen["attached"] == []
    [(result_frame, _)] = _frames(seen, "tool_result")
    assert result_frame["result"] == refusal
    fed_back = seen["messages"][1][-1]["content"][0]["content"]
    assert json.loads(fed_back)["data"]["error"] == "boq_ambiguous"


@pytest.mark.asyncio
async def test_a_failed_commit_turns_the_card_into_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _RecordingSession(fail_commit=True)
    seen = await _drive(monkeypatch, [_tool_use(PROPOSE_TOOL, {"title": "x"}), _text("Sorry.")], session=session)

    [(result_frame, _)] = _frames(seen, "tool_result")
    assert result_frame["result"]["renderer"] == "error"
    assert result_frame["result"]["data"]["error"] == "internal_error"
    assert session.rollbacks == 1
    assert seen["attached"] == []
    assert _frames(seen, "done")


@pytest.mark.asyncio
async def test_a_proposal_does_not_meet_the_manager_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proposing is harmless; the gate is for a tool that writes directly."""
    gate_calls: list[str] = []

    async def _gate(*args: Any, **_k: Any) -> None:
        gate_calls.append("check_tool_permission")
        raise AssertionError("the manager gate ran for a proposal")

    async def _idor(*args: Any, **_k: Any) -> None:
        gate_calls.append("_require_project_access")
        raise AssertionError("the write-tool access gate ran for a proposal")

    monkeypatch.setattr(chat_service, "check_tool_permission", _gate)
    monkeypatch.setattr(chat_service, "_require_project_access", _idor)
    seen = await _drive(
        monkeypatch,
        [_tool_use(PROPOSE_TOOL, {"title": "x", "project_id": str(uuid.uuid4())}), _text("Prepared.")],
    )

    assert gate_calls == []
    [(result_frame, _)] = _frames(seen, "tool_result")
    assert result_frame["result"]["renderer"] == "action_proposal"


@pytest.mark.asyncio
async def test_a_turn_that_fails_after_proposing_keeps_what_it_committed(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = await _drive(
        monkeypatch,
        [_tool_use(PROPOSE_TOOL, {"title": "x"}), RuntimeError("provider fell over")],
    )

    assert seen["session"].commits == 1  # the proposal, before the failure
    assert seen["session"].rollbacks == 0
    assert _frames(seen, "error")
    assert seen["attached"] == []  # no assistant message to attach to


# ── What the model reads back ─────────────────────────────────────────────────


def _big_proposal() -> dict[str, Any]:
    """A proposal whose card data is far over the re-feed limit (a long description, 300 members)."""
    description = "Formwork inspection on level 3. " * 60
    summary = f"Proposed 'Create task' in Residential House: description={description}. NOT saved yet: it waits."
    result = _proposal("act-42", summary)
    result["data"]["fields"] = [
        {
            "key": "assignee",
            "kind": "enum",
            "options": [{"value": str(uuid.uuid4()), "label": f"Member {i}", "label_key": None} for i in range(300)],
        }
    ]
    return result


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_the_model_reads_a_compact_proposal(provider: str) -> None:
    big = _big_proposal()
    ai_result = (
        {"content": [{"type": "tool_use", "id": "tu-1", "name": PROPOSE_TOOL, "input": {}}]}
        if provider == "anthropic"
        else {"choices": [{"message": {"role": "assistant", "tool_calls": []}}]}
    )

    messages = ERPChatService(session=object())._append_tool_results(  # type: ignore[arg-type]
        provider, [], ai_result, [{"tool_name": PROPOSE_TOOL, "tool_id": "tu-1", "result": big}]
    )

    content = messages[-1]["content"][0]["content"] if provider == "anthropic" else messages[-1]["content"]
    fed = json.loads(content)
    assert fed["action_id"] == "act-42"
    assert fed["status"] == "proposed"
    assert "NOT saved yet" in fed["summary"]
    assert "options" not in content
    # Without the compact view the truncation keeps 1000 characters of the
    # summary and loses exactly the sentence that says nothing is saved.
    assert "NOT saved yet" not in json.dumps(_truncate_tool_result(big))


def test_a_read_result_is_fed_back_unchanged() -> None:
    read = {"renderer": "boq_table", "data": {"positions": []}, "summary": "0 lines"}
    assert _result_for_model(read) is read


# ── 4. + 5. The request context in the prompt ────────────────────────────────


@pytest.mark.asyncio
async def test_the_request_context_follows_the_tool_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    request = StreamChatRequest.model_validate(
        {
            "message": "what is on this page?",
            "locale": "de",
            "client_context": {"route": "/boq/7f3c?tab=lines", "project_id": None},
        }
    )
    seen = await _drive(monkeypatch, [_text("Hallo.")], request=request)

    [system] = seen["systems"]
    assert system.startswith(SYSTEM_PROMPT)
    tail = system[len(SYSTEM_PROMPT) :]
    assert "## Request context" in tail
    assert "Interface language: Deutsch (de)" in tail
    assert "Current page: /boq/7f3c" in tail
    assert "tab=lines" not in tail
    assert "Active project: none selected" in tail
    assert not _frames(seen, "error")


@pytest.mark.asyncio
async def test_a_malformed_locale_is_ignored_not_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    request = StreamChatRequest.model_validate({"message": "hi", "locale": "<script>", "client_context": "junk"})
    assert request.locale is None
    assert request.client_context is None

    seen = await _drive(monkeypatch, [_text("Hi.")], request=request)

    assert "Interface language" not in seen["systems"][0]
    assert not _frames(seen, "error")


@pytest.mark.asyncio
async def test_the_no_tools_prompt_gets_the_same_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def _fake_call_ai(**kwargs: Any) -> tuple[str, int]:
        captured.update(kwargs)
        return "Sure.", 3

    monkeypatch.setattr("app.modules.ai.ai_client.call_ai", _fake_call_ai)
    service = ERPChatService(_RecordingSession())  # type: ignore[arg-type]

    async def _resolve(_uid: str) -> tuple[str, str, str | None]:
        return "cohere", "k", None

    async def _session_row(*_a: Any, **_k: Any) -> _ChatSessionRow:
        return _ChatSessionRow()

    async def _budget(_uid: str) -> tuple[bool, int]:
        return True, 0

    async def _build(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [{"role": "user", "content": "hi"}]

    async def _persist(*_a: Any, **_k: Any) -> uuid.UUID:
        return uuid.uuid4()

    monkeypatch.setattr(service, "_resolve_ai", _resolve)
    monkeypatch.setattr(service, "get_or_create_session", _session_row)
    monkeypatch.setattr(service, "check_daily_token_budget", _budget)
    monkeypatch.setattr(service, "_build_messages", _build)
    monkeypatch.setattr(service, "_persist_messages", _persist)

    request = StreamChatRequest.model_validate({"message": "add a line", "locale": "fr"})
    _ = [c async for c in service.stream_response(str(uuid.uuid4()), request)]

    system = captured["system"]
    assert system.startswith(SYSTEM_PROMPT_NO_TOOLS)
    assert "Interface language: Français (fr)" in system[len(SYSTEM_PROMPT_NO_TOOLS) :]
    assert "cannot prepare changes" in system


@pytest.mark.asyncio
async def test_a_project_the_check_refuses_is_dropped_not_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    async def _refuse(*_a: Any, **_k: Any) -> None:
        raise HTTPException(status_code=404, detail="Project not found")

    monkeypatch.setattr("app.dependencies.verify_project_access", _refuse)
    project_id = uuid.uuid4()
    request = StreamChatRequest.model_validate({"message": "hi", "client_context": {"project_id": str(project_id)}})
    seen = await _drive(monkeypatch, [_text("Hi.")], request=request)

    assert str(project_id) not in seen["systems"][0]
    assert "Active project: none selected" in seen["systems"][0]
    assert seen["created_with"][2] is None, "the new chat session must not store an unchecked project"
    assert not _frames(seen, "error")


@pytest.mark.asyncio
async def test_a_project_lookup_that_breaks_is_dropped_not_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _broken(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("lookup failed")

    monkeypatch.setattr("app.dependencies.verify_project_access", _broken)
    request = StreamChatRequest.model_validate({"message": "hi", "project_id": str(uuid.uuid4())})
    seen = await _drive(monkeypatch, [_text("Hi.")], request=request)

    assert "Active project: none selected" in seen["systems"][0]
    assert seen["created_with"][2] is None
    assert not _frames(seen, "error")
