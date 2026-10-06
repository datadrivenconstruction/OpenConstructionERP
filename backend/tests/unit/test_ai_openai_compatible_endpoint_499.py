# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Issue #499 - the self-hosted ``vllm`` provider as a generic OpenAI-compatible endpoint.

A self-hosting operator asked for a provider that takes a base URL, an optional
key and a model name, so any gateway or local runtime speaking the OpenAI chat
protocol can be plugged in. The ``vllm`` provider already had the base URL, the
model override and the SSRF guard. What it lacked:

* a key. There was no place to store one and the resolver returned an empty
  string for every self-hosted runtime, so a gateway that wants a bearer token
  could not be used, although a comment claimed a stored key was sent;
* a URL rule that accepts the shape gateways are written in. A base ending in
  ``/v1`` became ``/v1/v1/chat/completions``;
* one normaliser. The connection test carried its own copy, so it could pass
  while real calls failed, or the other way round;
* a timeout of the operator's choosing (issue item 4), and the knowledge that
  a vLLM server started without a tool parser refuses a tool schema in words
  the tools-rejection retry did not recognise (item 3).

Nothing here touches a network: transports are stubbed and the URLs are
literal private addresses, so the dispatch-time SSRF guard runs for real
without DNS.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.core.crypto import encrypt_secret
from app.modules.ai import ai_client
from app.modules.ai.models import AISettings
from app.modules.ai.schemas import AISettingsUpdate

GATEWAY = "http://10.20.0.5:4000"
VLLM_TOOL_REFUSAL = '"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set'


def _row(**meta: Any) -> AISettings:
    """A transient settings row - the real class, so its properties are exercised."""
    return AISettings(user_id=uuid.uuid4(), preferred_model="vllm", metadata_=dict(meta))


class _Capture:
    """Stub transport recording what one POST carried."""

    def __init__(self, responses: list[tuple[int, dict[str, Any]]] | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self._responses = list(responses or [])

    def client(self, *_a: Any, **_k: Any) -> _Capture:
        return self

    async def __aenter__(self) -> _Capture:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def post(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,  # httpx's own kwarg name
        timeout: float | None = None,
    ) -> httpx.Response:
        self.requests.append({"url": url, "headers": dict(headers or {}), "payload": json or {}, "timeout": timeout})
        status, body = (
            self._responses.pop(0)
            if self._responses
            else (200, {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 1}})
        )
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> _Capture:
    capture = _Capture()
    monkeypatch.setattr(ai_client.httpx, "AsyncClient", capture.client)
    return capture


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OE_VLLM_API_KEY", raising=False)
    settings = get_settings()
    # Guarded so the file reports one failure per missing behaviour, not one
    # fixture error for all of them, on a tree without the new settings.
    for name, value in (("ai_timeout", None), ("chat_ai_timeout", None), ("ai_tools_self_hosted", "")):
        if name in type(settings).model_fields:
            monkeypatch.setattr(settings, name, value)
    refused = getattr(ai_client, "_TOOLS_REFUSED", None)
    if refused is not None:
        refused.clear()


# ── URL normalisation, one rule for every caller ─────────────────────────────


@pytest.mark.parametrize(
    ("saved", "expected"),
    [
        ("http://gpu-box:11434", "http://gpu-box:11434/v1/chat/completions"),
        ("http://gpu-box:11434/", "http://gpu-box:11434/v1/chat/completions"),
        ("https://gw.example/v1", "https://gw.example/v1/chat/completions"),
        ("https://gw.example/v1/", "https://gw.example/v1/chat/completions"),
        ("https://gw.example/api/v1", "https://gw.example/api/v1/chat/completions"),
        ("https://gw.example/v1/chat/completions", "https://gw.example/v1/chat/completions"),
        ("https://gw.example/openai/chat/completions", "https://gw.example/openai/chat/completions"),
    ],
)
def test_a_saved_base_url_becomes_one_chat_completions_endpoint(saved: str, expected: str) -> None:
    assert ai_client._normalise_self_hosted_url(saved) == expected


@pytest.mark.asyncio
async def test_the_connection_test_uses_the_same_url_rule_and_the_stored_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The route used to normalise on its own and read no key for vllm."""
    from app.modules.ai import router as ai_router

    row = _row(vllm_base_url="https://gw.example/v1", vllm_api_key=encrypt_secret("sk-gateway"))
    seen: dict[str, Any] = {}

    async def _fake_call_ai(**kwargs: Any) -> tuple[str, int]:
        seen.update(kwargs)
        return "OK", 1

    class _Repo:
        async def get_by_user_id(self, _uid: uuid.UUID) -> AISettings:
            return row

    class _Service:
        settings_repo = _Repo()

    monkeypatch.setattr(ai_router, "call_ai", _fake_call_ai)
    result = await ai_router.test_ai_connection({"provider": "vllm"}, str(uuid.uuid4()), _Service())  # type: ignore[arg-type]

    assert result["success"] is True
    assert seen["base_url"] == "https://gw.example/v1/chat/completions"
    assert seen["api_key"] == "sk-gateway"
    # The connection test keeps its own short cap whatever the operator set.
    assert seen["timeout"] == 15.0


# ── The optional key ─────────────────────────────────────────────────────────


def test_the_key_lives_encrypted_in_metadata_behind_the_usual_attribute() -> None:
    row = _row()
    row.vllm_api_key = encrypt_secret("sk-gateway")
    assert "sk-gateway" not in repr(row.metadata_)
    assert row.metadata_["vllm_api_key"] == row.vllm_api_key
    row.vllm_api_key = None
    assert "vllm_api_key" not in row.metadata_
    assert row.vllm_api_key is None


def test_the_resolver_returns_the_stored_key_for_the_endpoint() -> None:
    row = _row(vllm_base_url=GATEWAY, vllm_api_key=encrypt_secret("sk-gateway"))
    assert ai_client.resolve_provider_and_key(row) == ("vllm", "sk-gateway")


def test_the_resolver_falls_back_to_the_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OE_VLLM_API_KEY", "sk-from-env")
    assert ai_client.resolve_provider_and_key(_row(vllm_base_url=GATEWAY)) == ("vllm", "sk-from-env")
    # A key saved in Settings wins over the server-wide one.
    stored = _row(vllm_base_url=GATEWAY, vllm_api_key=encrypt_secret("sk-stored"))
    assert ai_client.resolve_provider_and_key(stored) == ("vllm", "sk-stored")


def test_the_local_only_fallback_also_carries_the_key() -> None:
    """A user with only an endpoint keeps preferred_model=claude-sonnet."""
    row = _row(vllm_base_url=GATEWAY, vllm_api_key=encrypt_secret("sk-gateway"))
    row.preferred_model = "claude-sonnet"
    assert ai_client.resolve_provider_and_key(row) == ("vllm", "sk-gateway")


def test_ollama_stays_keyless() -> None:
    row = AISettings(user_id=uuid.uuid4(), preferred_model="ollama", metadata_={"ollama_base_url": GATEWAY})
    assert ai_client.resolve_provider_and_key(row) == ("ollama", "")


@pytest.mark.asyncio
async def test_the_bearer_header_is_sent_only_when_a_key_is_set(transport: _Capture) -> None:
    provider, key = ai_client.resolve_provider_and_key(
        _row(vllm_base_url=GATEWAY, vllm_api_key=encrypt_secret("sk-gateway"))
    )
    await ai_client.call_ai(provider=provider, api_key=key, system="s", prompt="p")
    provider, key = ai_client.resolve_provider_and_key(_row(vllm_base_url=GATEWAY))
    await ai_client.call_ai(provider=provider, api_key=key, system="s", prompt="p")

    with_key, without_key = transport.requests
    assert with_key["url"] == f"{GATEWAY}/v1/chat/completions"
    assert with_key["headers"]["Authorization"] == "Bearer sk-gateway"
    assert "Authorization" not in without_key["headers"]


def test_the_settings_payload_accepts_the_key() -> None:
    assert AISettingsUpdate(vllm_api_key="sk-gateway").vllm_api_key == "sk-gateway"


# ── Tool calling: the vLLM refusal and the remembered fallback ───────────────


def test_a_vllm_server_without_a_tool_parser_is_a_tools_rejection() -> None:
    """The literal message vLLM returns (vllm/renderers/online_renderer.py, HTTP 400)."""
    assert ai_client._is_tools_rejection(400, VLLM_TOOL_REFUSAL)


def test_the_vllm_refusal_is_not_mistaken_for_a_dead_model_id() -> None:
    # A model rejection triggers the slug fallback first; the two sets must not overlap.
    low = VLLM_TOOL_REFUSAL.lower()
    for word in ("model not found", "unknown model", "invalid model", "deprecated", "unsupported model"):
        assert word not in low


def _tools_call(model: str = "qwen", **kwargs: Any) -> Any:
    return ai_client.call_openai_compatible_tools(
        "vllm",
        "",
        "with tools",
        "without tools",
        [{"role": "user", "content": "hi"}],
        [{"type": "function", "function": {"name": "list_projects", "parameters": {}}}],
        model=model,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_auto_remembers_a_refusal_per_endpoint_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    ai_client.resolve_provider_and_key(_row(vllm_base_url=GATEWAY))
    refusal = (400, {"object": "error", "message": VLLM_TOOL_REFUSAL})
    capture = _Capture([refusal, (200, {"choices": [{"message": {"content": "a"}}]})])
    monkeypatch.setattr(ai_client.httpx, "AsyncClient", capture.client)

    await _tools_call(remember_refusal=True)
    assert [bool(r["payload"].get("tools")) for r in capture.requests] == [True, False]

    # Same endpoint and model: straight to the plain request, no second refusal.
    await _tools_call(remember_refusal=True)
    assert [bool(r["payload"].get("tools")) for r in capture.requests] == [True, False, False]
    assert capture.requests[2]["payload"]["messages"][0]["content"] == "without tools"

    # Another model on the same gateway is asked afresh.
    await _tools_call(model="llama-tools", remember_refusal=True)
    assert bool(capture.requests[3]["payload"].get("tools")) is True


@pytest.mark.asyncio
async def test_the_remembered_refusal_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    ai_client.resolve_provider_and_key(_row(vllm_base_url=GATEWAY))
    now = [1000.0]
    monkeypatch.setattr(ai_client.time, "monotonic", lambda: now[0])
    refusal = (400, {"error": {"message": VLLM_TOOL_REFUSAL}})
    capture = _Capture([refusal])
    monkeypatch.setattr(ai_client.httpx, "AsyncClient", capture.client)

    await _tools_call(remember_refusal=True)
    now[0] += ai_client.TOOLS_REFUSAL_TTL_S + 1
    await _tools_call(remember_refusal=True)
    assert [bool(r["payload"].get("tools")) for r in capture.requests] == [True, False, True]


@pytest.mark.asyncio
async def test_on_does_not_remember(monkeypatch: pytest.MonkeyPatch) -> None:
    ai_client.resolve_provider_and_key(_row(vllm_base_url=GATEWAY))
    refusal = (400, {"error": {"message": VLLM_TOOL_REFUSAL}})
    capture = _Capture([refusal, (200, {"choices": [{"message": {"content": "a"}}]}), refusal])
    monkeypatch.setattr(ai_client.httpx, "AsyncClient", capture.client)

    await _tools_call()
    await _tools_call()
    assert [bool(r["payload"].get("tools")) for r in capture.requests] == [True, False, True, False]


def test_the_tool_mode_is_bound_per_settings_and_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> list[str]:
        modes = []
        ai_client.resolve_provider_and_key(_row(vllm_base_url=GATEWAY, tool_calling={"vllm": "on"}))
        modes.append(ai_client.tool_calling_mode("vllm"))
        ai_client.resolve_provider_and_key(_row(vllm_base_url=GATEWAY))
        modes.append(ai_client.tool_calling_mode("vllm"))
        monkeypatch.setattr(get_settings(), "ai_tools_self_hosted", "vllm, ollama")
        modes.append(ai_client.tool_calling_mode("vllm"))
        ai_client.resolve_provider_and_key(_row(vllm_base_url=GATEWAY, tool_calling={"vllm": "off"}))
        modes.append(ai_client.tool_calling_mode("vllm"))
        # Not a self-hosted provider: not configurable here.
        modes.append(ai_client.tool_calling_mode("mistral"))
        return modes

    assert asyncio.run(scenario()) == ["on", "off", "auto", "off", "off"]


def test_the_settings_payload_rejects_an_unknown_tool_mode() -> None:
    with pytest.raises(ValidationError):
        AISettingsUpdate(tool_calling={"vllm": "sometimes"})
    with pytest.raises(ValidationError):
        AISettingsUpdate(tool_calling={"openai": "on"})  # only self-hosted endpoints are configurable
    assert AISettingsUpdate(tool_calling={"vllm": "auto"}).tool_calling == {"vllm": "auto"}


# ── Timeouts ─────────────────────────────────────────────────────────────────


def test_the_built_in_timeout_is_unchanged() -> None:
    assert ai_client.effective_ai_timeout() == 240.0
    assert ai_client.configured_ai_timeout() is None


def test_timeout_precedence_explicit_then_user_then_env_then_default(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> list[float]:
        seen = []
        monkeypatch.setattr(get_settings(), "ai_timeout", 600.0)
        ai_client.resolve_provider_and_key(_row(vllm_base_url=GATEWAY))
        seen.append(ai_client.effective_ai_timeout())
        ai_client.resolve_provider_and_key(_row(vllm_base_url=GATEWAY, timeouts={"vllm": 900}))
        seen.append(ai_client.effective_ai_timeout())
        seen.append(ai_client.effective_ai_timeout(15.0))
        # Another user's resolution in the same task does not inherit 900.
        ai_client.resolve_provider_and_key(_row(vllm_base_url=GATEWAY, timeouts={"ollama": 1200}))
        seen.append(ai_client.effective_ai_timeout())
        return seen

    assert asyncio.run(scenario()) == [600.0, 900.0, 15.0, 600.0]


@pytest.mark.asyncio
async def test_the_dispatch_waits_as_long_as_the_user_asked(transport: _Capture) -> None:
    provider, key = ai_client.resolve_provider_and_key(_row(vllm_base_url=GATEWAY, timeouts={"vllm": 900}))
    await ai_client.call_ai(provider=provider, api_key=key, system="s", prompt="p")
    assert transport.requests[0]["timeout"] == 900.0


def test_env_timeouts_bind_both_spellings_and_are_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OE_AI_TIMEOUT", "600")
    monkeypatch.setenv("OE_CHAT_AI_TIMEOUT", "300")
    monkeypatch.setenv("OE_AI_TOOLS_SELF_HOSTED", "vllm")
    cfg = Settings()
    assert (cfg.ai_timeout, cfg.chat_ai_timeout, cfg.ai_tools_self_hosted) == (600.0, 300.0, "vllm")
    # Out of range is pulled into 10..1800 rather than refusing to boot.
    assert Settings(ai_timeout=3, chat_ai_timeout=99999).ai_timeout == 10.0
    assert Settings(chat_ai_timeout=99999).chat_ai_timeout == 1800.0


def test_the_settings_payload_bounds_a_per_provider_timeout() -> None:
    with pytest.raises(ValidationError):
        AISettingsUpdate(timeouts={"vllm": 5})
    with pytest.raises(ValidationError):
        AISettingsUpdate(timeouts={"vllm": 1801})
    with pytest.raises(ValidationError):
        AISettingsUpdate(timeouts={"not-a-provider": 60})
    # null clears the override.
    assert AISettingsUpdate(timeouts={"vllm": None, "anthropic": 600}).timeouts == {"vllm": None, "anthropic": 600}


def test_agents_take_an_explicit_timeout_as_their_step_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.ai_agents.base import DEFAULT_LLM_STEP_TIMEOUT, effective_step_timeout

    async def scenario() -> list[float]:
        caps = []
        ai_client.resolve_provider_and_key(_row(vllm_base_url=GATEWAY))
        caps.append(effective_step_timeout(DEFAULT_LLM_STEP_TIMEOUT))
        ai_client.resolve_provider_and_key(_row(vllm_base_url=GATEWAY, timeouts={"vllm": 900}))
        caps.append(effective_step_timeout(DEFAULT_LLM_STEP_TIMEOUT))
        # An agent that chose its own cap keeps it.
        caps.append(effective_step_timeout(20.0))
        ai_client.resolve_provider_and_key(_row(vllm_base_url=GATEWAY))
        monkeypatch.setattr(get_settings(), "ai_timeout", 300.0)
        caps.append(effective_step_timeout(DEFAULT_LLM_STEP_TIMEOUT))
        return caps

    assert asyncio.run(scenario()) == [45.0, 900.0, 20.0, 300.0]
