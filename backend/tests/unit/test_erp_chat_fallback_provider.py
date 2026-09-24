# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Issues #417 and #424 - which providers in erp_chat get a tool schema.

Providers we call WITHOUT one (Cohere, Mistral, Groq, Ollama, ...) go through
``_call_fallback`` as plain text. That path used to send ``SYSTEM_PROMPT``, which advertises
~20 tools and orders "Always use tools first", while putting no tool schema on
the wire. Models did as instructed using their own call syntax and the literal
text reached the chat bubble - the reported symptom was a block of
``invoke name="list_projects"`` tags naming one of our own tools.

The same branch also returned out of ``stream_response`` before the shared
tail, which skipped persistence (so the thumbs feedback POST 404'd on a
client-side id, the "Last error captured" line of the report) and discarded
the token count (so the 24h budget was never charged for these providers).

The second half of the file covers issue #424, the opposite mistake: a
provider that DOES speak the OpenAI tool protocol being sent down that
plain-text path anyway, and telling the user it had no way to read their data.
The two halves constrain each other - the prompt must match what is on the
wire in both directions - which is why they live in one file.

These tests drive the real ``stream_response`` generator with the database
calls patched out and the provider response supplied from a fixture; nothing
contacts a provider.
"""

from __future__ import annotations

import inspect
import json
import uuid
from typing import Any

import httpx
import pytest

from app.modules.ai.ai_client import call_ai
from app.modules.erp_chat.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_NO_TOOLS
from app.modules.erp_chat.schemas import StreamChatRequest
from app.modules.erp_chat.service import ERPChatService
from app.modules.erp_chat.tools import TOOL_HANDLER_MAP


class _FakeSession:
    """Stand-in for the AsyncSession - ``stream_response`` only flushes it."""

    async def flush(self) -> None:
        return None


class _FakeChatSession:
    """Minimal ChatSession surface used by ``stream_response``."""

    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.project_id = None
        self.title = "Existing title"


def _frames(chunks: list[str], event: str) -> list[dict[str, Any]]:
    """Return the JSON payloads of every SSE frame of the given event type."""
    joined = "".join(chunks)
    payloads: list[dict[str, Any]] = []
    blocks = [b for b in joined.split("\n\n") if b.strip()]
    for block in blocks:
        lines = block.splitlines()
        if not lines or lines[0].strip() != f"event: {event}":
            continue
        for line in lines[1:]:
            if line.startswith("data:"):
                payloads.append(json.loads(line[len("data:") :].strip()))
    return payloads


def _streamed_text(chunks: list[str]) -> str:
    """Reassemble the assistant text from the chunked ``text`` frames."""
    return "".join(p.get("content", "") for p in _frames(chunks, "text"))


#: A provider that stays on the plain-text path. It used to be ``openrouter``
#: here, which was only ever a stand-in for "some provider without tools";
#: issue #424 moved that one onto the tool path, so the stand-in is now Cohere.
#: Cohere is the honest choice rather than a placeholder - it speaks ``/v2/chat``,
#: a different contract entirely, so it is not a candidate for that widening.
FALLBACK_PROVIDER = "cohere"


async def _drive(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider_text: str = "",
    provider_tokens: int = 42,
    provider_error: Exception | None = None,
    user_message: str = "Show all my projects",
    provider: str = FALLBACK_PROVIDER,
) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    """Run one full turn against a non-tool provider.

    ``provider_error``, when given, is raised by the faked provider call
    instead of returning text.

    Returns (sse_chunks, captured call_ai kwargs, captured persist kwargs).
    """
    service = ERPChatService(_FakeSession())  # type: ignore[arg-type]
    chat_session = _FakeChatSession()
    captured_call: dict[str, Any] = {}
    captured_persist: dict[str, Any] = {}
    persisted_id = uuid.uuid4()

    async def _fake_call_ai(**kwargs: Any) -> tuple[str, int]:
        captured_call.update(kwargs)
        if provider_error is not None:
            raise provider_error
        return provider_text, provider_tokens

    # _call_fallback imports call_ai inside the function body, so patch it at
    # its definition site rather than on the erp_chat module.
    monkeypatch.setattr("app.modules.ai.ai_client.call_ai", _fake_call_ai)

    async def _fake_get_or_create(*_a: Any, **_k: Any) -> _FakeChatSession:
        return chat_session

    async def _fake_budget(_uid: str) -> tuple[bool, int]:
        return True, 0

    async def _fake_build_messages(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [{"role": "user", "content": user_message}]

    async def _fake_resolve(_uid: str) -> tuple[str, str, str | None]:
        return provider, "test-key", None

    async def _fake_persist(
        _session: Any,
        _user_id: str,
        user_msg: str,
        assistant_text: str,
        tool_calls: Any,
        tool_results: Any,
        tokens_used: int,
    ) -> uuid.UUID:
        captured_persist.update(
            {
                "user_message": user_msg,
                "assistant_text": assistant_text,
                "tool_calls": tool_calls,
                "tool_results": tool_results,
                "tokens_used": tokens_used,
            }
        )
        return persisted_id

    monkeypatch.setattr(service, "get_or_create_session", _fake_get_or_create)
    monkeypatch.setattr(service, "check_daily_token_budget", _fake_budget)
    monkeypatch.setattr(service, "_build_messages", _fake_build_messages)
    monkeypatch.setattr(service, "_resolve_ai", _fake_resolve)
    monkeypatch.setattr(service, "_persist_messages", _fake_persist)

    req = StreamChatRequest(message=user_message)
    chunks: list[str] = []
    async for chunk in service.stream_response(str(uuid.uuid4()), req):
        chunks.append(chunk)

    captured_persist["_expected_id"] = persisted_id
    return chunks, captured_call, captured_persist


@pytest.mark.asyncio
async def test_the_fallback_provider_of_these_tests_really_takes_that_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard on the stand-in itself, not on the code under test.

    Every test below reads its evidence out of the faked ``call_ai`` kwargs,
    which are only populated when the turn actually goes through
    ``_call_fallback``. The day this provider is admitted to the tool path,
    those kwargs go empty and each of those tests fails on a confusing
    assertion instead of this clear one.
    """
    from app.modules.erp_chat.service import TOOL_CAPABLE_OPENAI_COMPAT

    assert FALLBACK_PROVIDER not in TOOL_CAPABLE_OPENAI_COMPAT

    _chunks, call_kwargs, _persist = await _drive(monkeypatch, provider_text="ok")
    assert call_kwargs.get("provider") == FALLBACK_PROVIDER, (
        f"{FALLBACK_PROVIDER} no longer reaches call_ai - pick another plain-text provider here"
    )


@pytest.mark.asyncio
async def test_no_tool_provider_is_not_told_it_has_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """The system prompt sent to a provider we call without a tool schema
    must not advertise tools - that mismatch is what made models emit call
    syntax as literal text (issue #417)."""
    _chunks, call_kwargs, _persist = await _drive(monkeypatch, provider_text="Sure.")

    system = call_kwargs["system"]

    # The tool-advertising prompt must not be the one on the wire.
    assert system != SYSTEM_PROMPT
    assert "You have access to live tools" not in system
    assert "Always use tools first" not in system

    # And the model is positively instructed the other way.
    assert "Never emit a tool call" in system
    assert "CANNOT query" in system


@pytest.mark.asyncio
async def test_the_prompt_choice_is_tied_to_the_call_that_carries_no_schema() -> None:
    """Tripwire on the SYSTEM_PROMPT_NO_TOOLS decision itself.

    The original form asserted only that ``call_ai`` had no ``tools``
    parameter, with the message "revisit SYSTEM_PROMPT_NO_TOOLS: providers
    that can now receive a tool schema should be told they have tools". Issue
    #424 is someone doing exactly that, so the tripwire is rewritten to assert
    the contract that came out of it rather than deleted.

    Two halves, and both are load-bearing:

    * ``call_ai`` remains the schema-free transport. ``_call_fallback``'s use
      of ``SYSTEM_PROMPT_NO_TOOLS`` is only correct while that holds, so the
      original assertion stays exactly as it was.
    * The tool-carrying sibling exists and takes BOTH prompts. Making
      ``system_without_tools`` a required argument is what stops a tools
      rejection from degrading into #417: the retry cannot drop the schema
      without also swapping the prompt that advertises it.
    """
    from app.modules.ai import ai_client

    assert "tools" not in inspect.signature(call_ai).parameters, (
        "call_ai grew a 'tools' parameter - revisit SYSTEM_PROMPT_NO_TOOLS: "
        "providers that can now receive a tool schema should be told they have tools"
    )

    assert hasattr(ai_client, "call_ai_tools"), (
        "no tool-carrying sibling for call_ai - a provider that speaks the "
        "OpenAI tool protocol has nowhere to send a schema (issue #424)"
    )
    tools_params = inspect.signature(ai_client.call_ai_tools).parameters
    assert "tools" in tools_params
    assert "system" in tools_params
    assert "system_without_tools" in tools_params, (
        "call_ai_tools must take the no-tools prompt as well, so the retry "
        "that drops the schema cannot keep advertising it (issue #417)"
    )


@pytest.mark.asyncio
async def test_no_tool_provider_turn_is_persisted_and_returns_its_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The turn must reach the shared persistence tail, and ``done`` must
    carry the persisted assistant id.

    Without this the client keeps its optimistic bubble id and the thumbs
    feedback POST 404s - the error captured in the issue report.
    """
    chunks, _call_kwargs, persist = await _drive(
        monkeypatch, provider_text="Here is what I can tell you.", provider_tokens=137
    )

    # Persistence ran, with the assistant text of this turn.
    assert persist["assistant_text"] == "Here is what I can tell you."

    done = _frames(chunks, "done")
    assert len(done) == 1, f"expected exactly one done frame, got {done}"
    assert done[0]["message_id"] == str(persist["_expected_id"])


@pytest.mark.asyncio
async def test_no_tool_provider_tokens_are_counted_against_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tokens spent on a no-tool provider must be accounted for.

    The old early return discarded ``call_ai``'s token count, so the 24h
    budget was never charged for any of these providers.
    """
    chunks, _call_kwargs, persist = await _drive(monkeypatch, provider_text="ok", provider_tokens=137)

    assert persist["tokens_used"] == 137
    done = _frames(chunks, "done")
    assert done[0]["tokens"] == 137


@pytest.mark.asyncio
async def test_provider_transport_failure_names_the_provider_and_ends_the_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed provider call must say WHICH provider failed, terminate the
    stream once, and persist nothing.

    ``_call_fallback`` no longer swallows its own exceptions, so the shared
    handlers own this path. The common failures - 401 on a bad key, 429, 400
    on a retired model slug - reach them as ``httpx.HTTPStatusError`` from
    ``raise_for_status()``, not as ``ValueError``. Sixteen providers share
    this branch, so an unattributed error message is useless to the user.
    """
    request = httpx.Request("POST", "https://api.cohere.com/v2/chat")
    response = httpx.Response(401, request=request)
    boom = httpx.HTTPStatusError("Unauthorized", request=request, response=response)

    chunks, _call_kwargs, persist = await _drive(monkeypatch, provider_error=boom)

    errors = _frames(chunks, "error")
    assert len(errors) == 1, f"expected exactly one error frame, got {errors}"
    assert FALLBACK_PROVIDER in errors[0]["message"], (
        f"error frame does not name the failing provider: {errors[0]['message']}"
    )

    # The stream is terminated exactly once, and a failed turn stores nothing.
    assert len(_frames(chunks, "done")) == 1
    assert "assistant_text" not in persist
    assert _streamed_text(chunks) == ""


@pytest.mark.asyncio
async def test_assistant_text_that_looks_like_a_tool_call_is_never_altered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Content that merely RESEMBLES a tool call must survive byte-for-byte.

    The fix removes the cause (the prompt) and deliberately adds no output
    scrubber, because a pattern that deletes "tool-call-looking" text would
    silently eat a legitimate answer. This is the guard on that decision: a
    genuine assistant reply explaining the very tag syntax from the bug
    report - including a real tool name of ours - must pass through the SSE
    text frames unmodified.
    """
    # Deliberately hostile: the exact shape from the issue screenshot, a
    # fenced JSON block naming a real tool, and prose about it.
    legitimate = (
        "Those tags come from the model, not from the ERP. A provider that "
        "lacks tool support may print <|DSML|tool_calls> and\n"
        '<|DSML|invoke name="list_projects"> instead of calling anything.\n'
        "```json\n"
        '{"name": "get_all_projects", "arguments": {}}\n'
        "```\n"
        '<tool_call>{"name": "get_all_projects"}</tool_call>\n'
        "Switch the provider under Settings > AI to enable live queries."
    )

    chunks, _call_kwargs, persist = await _drive(monkeypatch, provider_text=legitimate)

    # Nothing was stripped, reordered or re-encoded on the wire...
    assert _streamed_text(chunks) == legitimate
    # ...nor on the way into the database.
    assert persist["assistant_text"] == legitimate


# ══════════════════════════════════════════════════════════════════════════
# Issue #424 - a provider that speaks the OpenAI tool protocol gets tools
# ══════════════════════════════════════════════════════════════════════════
#
# The reporter was told by the assistant that their provider "is configured
# without tool access". That sentence is not a UI string: it is the model
# restating SYSTEM_PROMPT_NO_TOOLS, which it was given because the dispatch
# admitted two provider literals and sent everything else down the plain-text
# path. OpenRouter speaks the same /chat/completions tool protocol OpenAI
# does, so the statement was true of the implementation and false about the
# transport.
#
# The tests below fake the HTTP layer rather than call_ai, so the real
# transport runs: dispatch, tool-schema assembly, endpoint and header
# resolution, the model-slug retry and both response readers. Every assertion
# about the endpoint, the model slug or the retry is CONJOINED with "the
# request that carried tools", because taken alone each of them already held
# before the fix - the plain-text path posts to the same URL with the same
# headers and the same slug, and already retries a dead slug. Only the tool
# schema tells the two paths apart.

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_SLUG = "deepseek/deepseek-v4-flash-0731"


def _make_response(status: int, body: dict[str, Any], url: str) -> httpx.Response:
    """Build a real httpx.Response so raise_for_status behaves as in prod."""
    return httpx.Response(status, json=body, request=httpx.Request("POST", url))


def _ok_text(text: str = "Here are your projects.", tokens: int = 42) -> tuple[int, dict[str, Any]]:
    """A 200 carrying a plain assistant answer."""
    return 200, {
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 12, "total_tokens": tokens},
    }


def _ok_tool_call(name: str = "list_projects", arguments: str = "{}") -> tuple[int, dict[str, Any]]:
    """A 200 in which the model asks for a tool, OpenAI-shaped."""
    return 200, {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "call_abc", "type": "function", "function": {"name": name, "arguments": arguments}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 15},
    }


def _err(status: int, message: str) -> tuple[int, dict[str, Any]]:
    """A provider error response in the usual OpenAI envelope."""
    return status, {"error": {"message": message}}


async def _drive_tools(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[tuple[int, dict[str, Any]]],
    *,
    model_override: str | None = _SLUG,
    user_message: str = "Show all my projects",
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    """Run one full turn against OpenRouter with only the HTTP layer faked.

    Args:
        responses: One (status, body) pair per expected outbound request, in
            order. Running out of them fails the test rather than looping.
        model_override: What Settings > AI holds for this provider.
        user_message: The user's turn.

    Returns:
        Tuple of (sse_chunks, outbound requests, captured persist kwargs).
    """
    from app.modules.ai import ai_client

    service = ERPChatService(_FakeSession())  # type: ignore[arg-type]
    chat_session = _FakeChatSession()
    requests: list[dict[str, Any]] = []
    captured_persist: dict[str, Any] = {}
    persisted_id = uuid.uuid4()
    queue = list(responses)

    class _FakeClient:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *_exc: Any) -> bool:
            return False

        async def post(
            self,
            url: str,
            headers: dict[str, str] | None = None,
            json: dict[str, Any] | None = None,  # httpx's own kwarg name
            timeout: float | None = None,
        ) -> httpx.Response:
            requests.append({"url": url, "headers": dict(headers or {}), "payload": json or {}})
            if not queue:
                msg = f"provider called {len(requests)} times, test queued {len(responses)}"
                raise AssertionError(msg)
            status, body = queue.pop(0)
            return _make_response(status, body, url)

    monkeypatch.setattr(ai_client.httpx, "AsyncClient", _FakeClient)

    async def _fake_get_or_create(*_a: Any, **_k: Any) -> _FakeChatSession:
        return chat_session

    async def _fake_budget(_uid: str) -> tuple[bool, int]:
        return True, 0

    async def _fake_build_messages(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [{"role": "user", "content": user_message}]

    async def _fake_resolve(_uid: str) -> tuple[str, str, str | None]:
        return "openrouter", "or-test-key", model_override

    async def _fake_persist(
        _session: Any,
        _user_id: str,
        user_msg: str,
        assistant_text: str,
        tool_calls: Any,
        tool_results: Any,
        tokens_used: int,
    ) -> uuid.UUID:
        captured_persist.update(
            {
                "user_message": user_msg,
                "assistant_text": assistant_text,
                "tool_calls": tool_calls,
                "tool_results": tool_results,
                "tokens_used": tokens_used,
            }
        )
        return persisted_id

    monkeypatch.setattr(service, "get_or_create_session", _fake_get_or_create)
    monkeypatch.setattr(service, "check_daily_token_budget", _fake_budget)
    monkeypatch.setattr(service, "_build_messages", _fake_build_messages)
    monkeypatch.setattr(service, "_resolve_ai", _fake_resolve)
    monkeypatch.setattr(service, "_persist_messages", _fake_persist)

    req = StreamChatRequest(message=user_message)
    chunks: list[str] = []
    async for chunk in service.stream_response(str(uuid.uuid4()), req):
        chunks.append(chunk)

    captured_persist["_expected_id"] = persisted_id
    return chunks, requests, captured_persist


def _tool_requests(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only the outbound requests that actually carried a tool schema."""
    return [r for r in requests if r["payload"].get("tools")]


def _system_of(request: dict[str, Any]) -> str:
    """The system turn of an outbound OpenAI-shaped request."""
    for msg in request["payload"].get("messages", []):
        if msg.get("role") == "system":
            return msg.get("content", "")
    return ""


@pytest.mark.asyncio
async def test_openrouter_receives_a_tool_schema_and_the_tool_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression test for #424.

    A provider on the OpenAI wire protocol must get the tool definitions and
    the prompt that tells it they exist. Before the fix the payload had no
    ``tools`` key at all and the system turn was SYSTEM_PROMPT_NO_TOOLS, whose
    text is what the user saw quoted back at them.
    """
    _chunks, requests, _persist = await _drive_tools(monkeypatch, [_ok_text()])

    assert len(requests) == 1
    payload = requests[0]["payload"]

    tools = payload.get("tools")
    assert tools, "no tool schema on the wire - this is issue #424 itself"
    assert len(tools) > 1
    assert all(t.get("type") == "function" for t in tools)
    assert all(t["function"].get("name") and t["function"].get("parameters") for t in tools)

    # The tool prompt, followed by this request's context block (date, page).
    system = _system_of(requests[0])
    assert system.startswith(SYSTEM_PROMPT)
    assert not system.startswith(SYSTEM_PROMPT_NO_TOOLS)
    assert "without tool support" not in system


@pytest.mark.asyncio
async def test_the_tool_request_goes_to_openrouter_and_keeps_its_referer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool-carrying request must reach OpenRouter, not OpenAI.

    Conjoined with the tool schema on purpose: the plain-text path already
    posted to this URL with this header, so the endpoint alone proves nothing
    about the change. Inheriting ``api.openai.com`` from the OpenAI branch
    would send an OpenRouter key to OpenAI.
    """
    _chunks, requests, _persist = await _drive_tools(monkeypatch, [_ok_text()])

    with_tools = _tool_requests(requests)
    assert len(with_tools) == 1, "no request carried tools, so there is nothing to check the endpoint of"
    assert with_tools[0]["url"] == OPENROUTER_URL
    assert with_tools[0]["headers"].get("HTTP-Referer") == "https://openconstructionerp.com"
    assert with_tools[0]["headers"].get("Authorization") == "Bearer or-test-key"

    assert not [r for r in requests if "api.openai.com" in r["url"]], "an OpenRouter key was sent to OpenAI"


@pytest.mark.asyncio
async def test_the_tool_request_carries_the_model_slug_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user's slug reaches the wire with its slash and date suffix intact.

    Conjoined with the tool schema for the same reason as the endpoint test.
    """
    _chunks, requests, _persist = await _drive_tools(monkeypatch, [_ok_text()])

    with_tools = _tool_requests(requests)
    assert len(with_tools) == 1, "no request carried tools, so there is no tool request to read a model off"
    assert with_tools[0]["payload"]["model"] == _SLUG


@pytest.mark.asyncio
async def test_the_tool_turn_is_persisted_and_returns_its_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider moved onto the tool path still reaches the shared tail.

    That tail was the #417 fix: persistence, token accounting and exactly one
    ``done`` frame carrying the persisted assistant id, which the client needs
    for its thumbs feedback POST to land.
    """
    chunks, requests, persist = await _drive_tools(monkeypatch, [_ok_text("All good.", tokens=57)])

    assert _tool_requests(requests), "the turn never carried tools, so it is not the path under test"

    assert persist["assistant_text"] == "All good."
    assert persist["tokens_used"] == 57
    done = _frames(chunks, "done")
    assert len(done) == 1, f"expected exactly one done frame, got {done}"
    assert done[0]["message_id"] == str(persist["_expected_id"])
    assert done[0]["tokens"] == 57
    assert not _frames(chunks, "error")


@pytest.mark.asyncio
async def test_a_tool_call_round_trips_to_an_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end over the widened path, which is what the three parsers are for.

    The model asks for a tool, the tool runs, its result is appended in OpenAI
    shape and fed back, and the second round answers. Widening only the
    dispatch leaves each of those three steps returning its empty default, so
    this fails at a different assertion for each half-applied variant.
    """
    calls: list[dict[str, Any]] = []

    async def _fake_handler(_session: Any, args: dict[str, Any], _user_id: str) -> dict[str, Any]:
        calls.append(args)
        return {"renderer": "generic_table", "data": [{"name": "Tower A"}], "summary": "1 project"}

    monkeypatch.setitem(TOOL_HANDLER_MAP, "list_projects", _fake_handler)

    chunks, requests, persist = await _drive_tools(
        monkeypatch,
        [_ok_tool_call("list_projects"), _ok_text("You have 1 project: Tower A.")],
    )

    # The tool call was seen (parser 1) and executed.
    assert len(calls) == 1
    starts = _frames(chunks, "tool_start")
    assert [s["tool"] for s in starts] == ["list_projects"]
    assert len(_frames(chunks, "tool_result")) == 1

    # Its result went back to the provider in OpenAI shape (parser 3).
    assert len(requests) == 2
    followup = requests[1]["payload"]["messages"]
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "call_abc" for m in followup), (
        f"tool results were not appended for the next round: {followup}"
    )
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in followup)
    assert requests[1]["payload"].get("tools"), "the follow-up round dropped the tool schema"

    # And the final text reached the user (parser 2).
    assert _streamed_text(chunks) == "You have 1 project: Tower A."
    assert persist["assistant_text"] == "You have 1 project: Tower A."
    assert persist["tokens_used"] == 57


@pytest.mark.asyncio
async def test_a_retired_slug_is_retried_and_the_retry_still_carries_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The issue #148 guard, on the path the provider was moved to.

    The dead-slug self-heal lives in ai_client's unified error handler, which
    the plain-text path goes through. A tool path that posted its own request
    would make tools work today and hand the user a bare HTTP 400 the day the
    slug retires - and the slug in the #424 report carries a date suffix,
    exactly the class this exists for.

    "A retry happened" is not the discriminator; the retry already happened
    before the fix. "The retry carried the fallback slug AND a tool schema" is.
    """
    chunks, requests, persist = await _drive_tools(
        monkeypatch,
        [_err(400, f"{_SLUG} is not a valid model ID"), _ok_text("Recovered.")],
    )

    assert len(requests) == 2, f"expected one retry, saw {len(requests)} requests"
    assert requests[0]["payload"]["model"] == _SLUG
    assert requests[1]["payload"]["model"] == "openrouter/auto"
    assert requests[1]["payload"].get("tools"), "the #148 retry dropped the tool schema"
    assert _system_of(requests[1]).startswith(SYSTEM_PROMPT)

    assert not _frames(chunks, "error")
    assert persist["assistant_text"] == "Recovered."


@pytest.mark.asyncio
async def test_a_tools_rejection_retries_once_without_tools_and_still_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shape-(b) guard, and the reason this is not just a wider allowlist.

    Whether any given OpenRouter model implements function calling is a
    catalog fact, not a fact in this repo. The fix does not need to know: it
    assumes the endpoint takes tools and degrades when the provider says
    otherwise. The retry must drop the schema AND swap the prompt - dropping
    only the schema leaves the model advertised tools it cannot call, which
    is issue #417 recreated on the retry.
    """
    chunks, requests, persist = await _drive_tools(
        monkeypatch,
        [
            _err(404, "No endpoints found that support tool use"),
            _ok_text("I cannot read your data, but here is general guidance."),
        ],
    )

    assert len(requests) == 2, f"expected exactly one retry, saw {len(requests)} requests"

    assert requests[0]["payload"].get("tools"), "the first attempt did not try tools at all"
    assert _system_of(requests[0]).startswith(SYSTEM_PROMPT)

    assert "tools" not in requests[1]["payload"], "the retry kept the schema the provider just refused"
    assert _system_of(requests[1]).startswith(SYSTEM_PROMPT_NO_TOOLS), (
        "the retry dropped the tool schema but kept the prompt advertising tools - that is issue #417"
    )
    # Both prompts carry the same request context block after them.
    assert _system_of(requests[0])[len(SYSTEM_PROMPT) :] == _system_of(requests[1])[len(SYSTEM_PROMPT_NO_TOOLS) :]
    # The retry stays on the user's model: a tools rejection says nothing
    # about the slug, so this must not silently swap what they configured.
    assert requests[1]["payload"]["model"] == _SLUG

    # The user gets an answer, not an error.
    assert not _frames(chunks, "error")
    assert _streamed_text(chunks) == "I cannot read your data, but here is general guidance."
    assert len(_frames(chunks, "done")) == 1
    assert persist["assistant_text"] == "I cannot read your data, but here is general guidance."


@pytest.mark.asyncio
async def test_a_list_typed_content_from_the_tool_path_is_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The issue #138 guard, on the path the provider was moved to.

    ``content`` returned as a list of typed parts is one of the four shapes
    behind #138, where a request billed tokens upstream and the user saw no
    response. ai_client's reader handles it; the naive read the tool path used
    (``msg.get("content", "") or ""``) returns an empty string for it, which
    reproduces that symptom exactly.

    Conjoined with the tool schema, because the plain-text path already ran
    the hardened reader - this only discriminates for a tool request.
    """
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Budget is "},
                        {"type": "text", "text": "EUR 1.2M."},
                    ],
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"total_tokens": 11},
    }

    chunks, requests, persist = await _drive_tools(monkeypatch, [(200, body)])

    assert _tool_requests(requests), "no request carried tools, so this is not the reader under test"
    assert _streamed_text(chunks) == "Budget is EUR 1.2M."
    assert persist["assistant_text"] == "Budget is EUR 1.2M."
    assert not _frames(chunks, "error")


@pytest.mark.asyncio
async def test_a_reply_with_no_usable_text_is_reported_not_left_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An HTTP-200 carrying an empty ``choices`` array must not go unnoticed.

    Another of #138's four shapes. On the tool path it is worse than a blank
    bubble: ``choices[0]`` on an empty list raises IndexError, which surfaces
    as an unattributed "Internal error". The user must get a message that
    names the provider and says what to do.
    """
    chunks, requests, persist = await _drive_tools(monkeypatch, [(200, {"choices": [], "usage": {}})])

    assert _tool_requests(requests)
    errors = _frames(chunks, "error")
    assert len(errors) == 1, f"expected exactly one error frame, got {errors}"
    assert "openrouter" in errors[0]["message"]
    assert "Internal error" not in errors[0]["message"], (
        "an empty choices array crashed the parser instead of being reported"
    )
    assert len(_frames(chunks, "done")) == 1
    assert "assistant_text" not in persist


@pytest.mark.asyncio
async def test_an_unreadable_final_round_still_keeps_a_turn_whose_tools_ran(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same unreadable response, but after a tool already ran.

    Reporting and returning is right only when nothing happened. Once tools
    have run, their results are already on the user's screen and their tokens
    are already billed, so bailing out before the shared tail would leave the
    turn unpersisted and send a ``done`` with no message_id - the shape issue
    #417 fixed. The turn is kept and closed normally instead.
    """

    async def _fake_handler(_session: Any, args: dict[str, Any], _user_id: str) -> dict[str, Any]:
        return {"renderer": "generic_table", "data": [{"name": "Tower A"}], "summary": "1 project"}

    monkeypatch.setitem(TOOL_HANDLER_MAP, "list_projects", _fake_handler)

    chunks, requests, persist = await _drive_tools(
        monkeypatch,
        [_ok_tool_call("list_projects"), (200, {"choices": [], "usage": {}})],
    )

    assert len(requests) == 2
    assert len(_frames(chunks, "tool_result")) == 1, "the tool never ran, so this is not the case under test"

    # The turn survives: persisted, with the tool results and the tokens the
    # round already cost, and closed by a done frame that can be replied to.
    assert persist["tool_results"], "a turn whose tool ran was dropped instead of persisted"
    assert persist["tokens_used"] == 15
    assert persist["assistant_text"]
    done = _frames(chunks, "done")
    assert len(done) == 1
    assert done[0]["message_id"] == str(persist["_expected_id"]), (
        "done carried no message_id, so the client cannot thread the reply"
    )
    assert not _frames(chunks, "error")


class TestOpenAIWireParsers:
    """The three provider-branching parsers, driven directly.

    Every one of them returns an empty default for a provider it does not
    recognise - no exception, no log line. That is the half-applied fix: the
    dispatch is widened, tool calls read as "the model asked for nothing", and
    the user gets a blank bubble instead of the honest message they had
    before.
    """

    @staticmethod
    def _service() -> ERPChatService:
        return ERPChatService(_FakeSession())  # type: ignore[arg-type]

    @staticmethod
    def _tool_call_result() -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Looking that up.",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "list_projects", "arguments": '{"limit": 5}'},
                            }
                        ],
                    }
                }
            ]
        }

    def test_tool_calls_are_extracted_for_an_openai_compatible_provider(self) -> None:
        calls = self._service()._extract_tool_calls("openrouter", self._tool_call_result())

        assert len(calls) == 1, "an OpenAI-shaped tool call read as 'no tools requested'"
        assert calls[0]["name"] == "list_projects"
        assert calls[0]["args"] == {"limit": 5}
        assert calls[0]["id"] == "call_1"

    def test_text_is_extracted_for_an_openai_compatible_provider(self) -> None:
        text = self._service()._extract_text("openrouter", self._tool_call_result())

        assert text == "Looking that up.", "the user would have received a blank bubble"

    def test_tool_results_are_appended_for_an_openai_compatible_provider(self) -> None:
        messages: list[dict[str, Any]] = [{"role": "user", "content": "hi"}]
        out = self._service()._append_tool_results(
            "openrouter",
            messages,
            self._tool_call_result(),
            [{"tool_name": "list_projects", "tool_id": "call_1", "result": {"summary": "1 project"}}],
        )

        assert len(out) == 3, "the next round would re-send the same prompt with no results"
        assert out[1]["role"] == "assistant"
        assert out[1].get("tool_calls")
        assert out[2]["role"] == "tool"
        assert out[2]["tool_call_id"] == "call_1"
        assert "1 project" in out[2]["content"]

    @pytest.mark.parametrize("provider", ["openai", "openrouter"])
    def test_an_empty_choices_array_never_raises_indexerror(self, provider: str) -> None:
        """``result.get("choices", [{}])[0]`` only defaults when the key is
        ABSENT. An HTTP-200 with ``"choices": []`` - #138's second shape -
        indexes an empty list and raises, before the reader can say why."""
        service = self._service()

        assert service._extract_tool_calls(provider, {"choices": []}) == []
        # Not raising is the assertion; the appended message is empty because
        # the response held nothing to append.
        assert service._append_tool_results(provider, [], {"choices": []}, []) == [{}]

        with pytest.raises(ValueError, match="no choices"):
            service._extract_text(provider, {"choices": []})
