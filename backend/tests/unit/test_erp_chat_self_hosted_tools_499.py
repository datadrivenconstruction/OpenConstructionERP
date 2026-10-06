# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Issue #499 - the assistant on a self-hosted endpoint: tools, timeout, keepalive.

Three things the assistant did not do for an operator's own OpenAI-compatible
endpoint:

* send it the tool schema. Only OpenRouter was admitted, so a vLLM or Ollama
  server that does implement OpenAI tool calls got the no-tools prompt and the
  assistant told the user it could not read their projects. Admission is now a
  per-endpoint setting (auto / on / off, default off, server default from
  ``OE_AI_TOOLS_SELF_HOSTED``);
* wait as long as the operator said. The chat's own Anthropic and OpenAI calls
  hard-coded 120 s, every other chat call 240 s;
* keep the stream alive while a slow model thinks. The reply is not
  token-streamed, so nothing crossed the wire until the model answered, and a
  reverse proxy with a 120 s read timeout (our own nginx config) cut the
  request whatever timeout the backend used. A comment frame now goes out on a
  timer, and the timer must stop on completion, on error and on disconnect.

The real ``stream_response`` runs with the database patched out and the
provider HTTP layer stubbed. Provider resolution is the real one, applied to a
transient settings row, so the per-request binding is exercised as in prod.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import httpx
import pytest

from app.config import get_settings
from app.modules.ai import ai_client
from app.modules.ai.models import AISettings
from app.modules.erp_chat import service as chat_service
from app.modules.erp_chat.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_NO_TOOLS
from app.modules.erp_chat.schemas import StreamChatRequest
from app.modules.erp_chat.service import ERPChatService

GATEWAY = "http://10.20.0.5:8001"
VLLM_TOOL_REFUSAL = '"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set'


class _FakeSession:
    async def flush(self) -> None:
        return None


class _FakeChatSession:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.project_id = None
        self.title = "Existing title"


def _ok_text(text: str = "Here you go.") -> tuple[int, dict[str, Any]]:
    return 200, {
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


def _frames(chunks: list[str], event: str) -> list[dict[str, Any]]:
    out = []
    for chunk in chunks:
        if chunk.startswith(f"event: {event}\n"):
            out.append(json.loads(chunk.split("data: ", 1)[1]))
    return out


def _system_of(request: dict[str, Any]) -> str:
    for msg in request["payload"].get("messages", []):
        if msg.get("role") == "system":
            return msg.get("content", "")
    return ""


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    for name, value in (("ai_timeout", None), ("chat_ai_timeout", None), ("ai_tools_self_hosted", "")):
        if name in type(settings).model_fields:
            monkeypatch.setattr(settings, name, value)
    refused = getattr(ai_client, "_TOOLS_REFUSED", None)
    if refused is not None:
        refused.clear()


async def _drive(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[tuple[int, dict[str, Any]]],
    *,
    meta: dict[str, Any] | None = None,
    preferred_model: str = "vllm",
) -> tuple[list[str], list[dict[str, Any]]]:
    """One full turn; returns the SSE chunks and the outbound requests."""
    service = ERPChatService(_FakeSession())  # type: ignore[arg-type]
    chat_session = _FakeChatSession()
    requests: list[dict[str, Any]] = []
    queue = list(responses)

    class _Client:
        def __init__(self, *_a: Any, timeout: float | None = None, **_k: Any) -> None:
            self.init_timeout = timeout

        async def __aenter__(self) -> _Client:
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
            requests.append(
                {"url": url, "payload": json or {}, "timeout": timeout if timeout is not None else self.init_timeout}
            )
            if not queue:
                raise AssertionError(f"provider called {len(requests)} times, test queued {len(responses)}")
            status, body = queue.pop(0)
            return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(ai_client.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(chat_service.httpx, "AsyncClient", _Client)

    row = AISettings(
        user_id=uuid.uuid4(),
        preferred_model=preferred_model,
        metadata_={"vllm_base_url": GATEWAY, **(meta or {})},
    )

    async def _resolve(_uid: str) -> tuple[str, str, str | None]:
        return ai_client.resolve_provider_key_model(row)

    async def _get_or_create(*_a: Any, **_k: Any) -> _FakeChatSession:
        return chat_session

    async def _budget(_uid: str) -> tuple[bool, int]:
        return True, 0

    async def _messages(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [{"role": "user", "content": "Show my projects"}]

    async def _persist(*_a: Any, **_k: Any) -> uuid.UUID:
        return uuid.uuid4()

    monkeypatch.setattr(service, "_resolve_ai", _resolve)
    monkeypatch.setattr(service, "get_or_create_session", _get_or_create)
    monkeypatch.setattr(service, "check_daily_token_budget", _budget)
    monkeypatch.setattr(service, "_build_messages", _messages)
    monkeypatch.setattr(service, "_persist_messages", _persist)

    chunks = [chunk async for chunk in service.stream_response(str(uuid.uuid4()), StreamChatRequest(message="hi"))]
    return chunks, requests


# ── Tool calling per endpoint ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_off_by_default_keeps_the_plain_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    _chunks, requests = await _drive(monkeypatch, [_ok_text()])
    assert len(requests) == 1
    assert "tools" not in requests[0]["payload"]
    assert _system_of(requests[0]).startswith(SYSTEM_PROMPT_NO_TOOLS)


@pytest.mark.asyncio
async def test_on_sends_the_schema_and_the_tool_prompt_to_the_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks, requests = await _drive(monkeypatch, [_ok_text("Done.")], meta={"tool_calling": {"vllm": "on"}})
    assert requests[0]["url"] == f"{GATEWAY}/v1/chat/completions"
    assert requests[0]["payload"].get("tools")
    assert _system_of(requests[0]).startswith(SYSTEM_PROMPT)
    assert not _frames(chunks, "error")
    assert "".join(f["content"] for f in _frames(chunks, "text")) == "Done."


@pytest.mark.asyncio
async def test_the_server_default_turns_auto_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "ai_tools_self_hosted", "vllm")
    _chunks, requests = await _drive(monkeypatch, [_ok_text()])
    assert requests[0]["payload"].get("tools")


@pytest.mark.asyncio
async def test_auto_degrades_on_a_vllm_refusal_and_remembers_it(monkeypatch: pytest.MonkeyPatch) -> None:
    meta = {"tool_calling": {"vllm": "auto"}}
    refusal = (400, {"object": "error", "message": VLLM_TOOL_REFUSAL})
    chunks, requests = await _drive(monkeypatch, [refusal, _ok_text("Plain answer.")], meta=meta)
    assert [bool(r["payload"].get("tools")) for r in requests] == [True, False]
    assert _system_of(requests[1]).startswith(SYSTEM_PROMPT_NO_TOOLS)
    assert not _frames(chunks, "error")

    # The next turn on the same endpoint and model does not ask again.
    _chunks, requests = await _drive(monkeypatch, [_ok_text("Again.")], meta=meta)
    assert len(requests) == 1
    assert "tools" not in requests[0]["payload"]


def test_a_self_hosted_tool_call_is_read_in_the_openai_shape() -> None:
    service = ERPChatService(_FakeSession())  # type: ignore[arg-type]
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "type": "function", "function": {"name": "list_projects", "arguments": "{}"}}
                    ],
                }
            }
        ]
    }
    for provider in ("vllm", "ollama"):
        assert service._extract_tool_calls(provider, body) == [{"id": "c1", "name": "list_projects", "args": {}}]


# ── Timeouts in the chat ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_chat_waits_as_long_as_the_user_set_for_the_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    _chunks, requests = await _drive(monkeypatch, [_ok_text()], meta={"timeouts": {"vllm": 900}})
    assert requests[0]["timeout"] == 900.0


@pytest.mark.asyncio
async def test_the_chat_env_timeout_reaches_every_chat_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "chat_ai_timeout", 600.0)
    _chunks, requests = await _drive(monkeypatch, [_ok_text()])
    assert requests[0]["timeout"] == 600.0


@pytest.mark.asyncio
async def test_the_chat_defaults_are_todays(monkeypatch: pytest.MonkeyPatch) -> None:
    _chunks, requests = await _drive(monkeypatch, [_ok_text()])
    assert requests[0]["timeout"] == 240.0
    assert chat_service.chat_ai_timeout("anthropic") == 120.0
    assert chat_service.chat_ai_timeout("openai") == 120.0


# ── Keepalive while the provider is thinking ─────────────────────────────────


@pytest.mark.asyncio
async def test_keepalive_frames_flow_until_the_call_completes() -> None:
    async def _slow() -> str:
        await asyncio.sleep(0.05)
        return "answer"

    task = asyncio.ensure_future(_slow())
    beats = [b async for b in chat_service._keepalive_until(task, interval=0.01)]
    assert beats
    assert all(b == ": keepalive\n\n" for b in beats)
    assert task.result() == "answer"


@pytest.mark.asyncio
async def test_keepalive_stops_on_error_and_the_error_reaches_the_caller() -> None:
    async def _fails() -> str:
        await asyncio.sleep(0.03)
        raise RuntimeError("provider down")

    task = asyncio.ensure_future(_fails())
    beats = [b async for b in chat_service._keepalive_until(task, interval=0.01)]
    assert beats
    assert task.done()
    with pytest.raises(RuntimeError, match="provider down"):
        task.result()


@pytest.mark.asyncio
async def test_a_client_disconnect_cancels_the_provider_call() -> None:
    cancelled = asyncio.Event()

    async def _never() -> str:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "unreachable"

    task = asyncio.ensure_future(_never())
    beats = chat_service._keepalive_until(task, interval=0.01)
    assert await beats.__anext__() == ": keepalive\n\n"
    await beats.aclose()  # what the server does when the browser goes away
    assert cancelled.is_set()
    assert task.cancelled()


@pytest.mark.asyncio
async def test_the_stream_keeps_the_proxy_awake_and_still_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_service, "HEARTBEAT_INTERVAL_S", 0.01)
    real_post = ai_client._post_openai_compat

    async def _slow_post(*args: Any, **kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return await real_post(*args, **kwargs)

    monkeypatch.setattr(ai_client, "_post_openai_compat", _slow_post)
    chunks, _requests = await _drive(monkeypatch, [_ok_text("Slow but sure.")])
    keepalives = [c for c in chunks if c == ": keepalive\n\n"]
    assert keepalives
    assert chunks.index(keepalives[0]) < chunks.index(next(c for c in chunks if c.startswith("event: text")))
    assert "".join(f["content"] for f in _frames(chunks, "text")) == "Slow but sure."


@pytest.mark.asyncio
async def test_closing_the_stream_mid_call_cancels_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_service, "HEARTBEAT_INTERVAL_S", 0.01)
    cancelled = asyncio.Event()

    async def _hang(*_a: Any, **_k: Any) -> dict[str, Any]:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return {}

    monkeypatch.setattr(ai_client, "_post_openai_compat", _hang)
    service = ERPChatService(_FakeSession())  # type: ignore[arg-type]
    row = AISettings(user_id=uuid.uuid4(), preferred_model="vllm", metadata_={"vllm_base_url": GATEWAY})

    async def _resolve(_uid: str) -> tuple[str, str, str | None]:
        return ai_client.resolve_provider_key_model(row)

    async def _get_or_create(*_a: Any, **_k: Any) -> _FakeChatSession:
        return _FakeChatSession()

    async def _budget(_uid: str) -> tuple[bool, int]:
        return True, 0

    async def _messages(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [{"role": "user", "content": "hi"}]

    monkeypatch.setattr(service, "_resolve_ai", _resolve)
    monkeypatch.setattr(service, "get_or_create_session", _get_or_create)
    monkeypatch.setattr(service, "check_daily_token_budget", _budget)
    monkeypatch.setattr(service, "_build_messages", _messages)

    stream = service.stream_response(str(uuid.uuid4()), StreamChatRequest(message="hi"))
    async for chunk in stream:
        if chunk == ": keepalive\n\n":
            break
    await stream.aclose()
    assert cancelled.is_set()
