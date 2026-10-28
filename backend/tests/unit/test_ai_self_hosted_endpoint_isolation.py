# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠One user's self-hosted AI endpoint is one user's.

Reported as GHSA-wfpw-cv5v-64j5. Saving an Ollama or vLLM base URL wrote it
into a module-global provider table, so the endpoint belonged to the worker
process rather than to the person who saved it. Everyone whose next AI call
routed to a self-hosted runtime - a different user, a different tenant, the
administrator - sent their prompt, and whatever project text was in it, to the
host the last person to touch their own settings had named. Nothing in the
request path noticed, because by then the URL looked exactly like
configuration.

Only Ollama and vLLM were ever tunable, which is the whole reachable surface:
every other provider is a fixed vendor URL. The dispatch-time SSRF guard is
not a mitigation here either - it blocks link-local and cloud-metadata
addresses, and an ordinary public host is precisely what it lets through.

What is pinned:

* resolving one user's settings does not change what a second resolution
  dispatches to, which is the cross-user claim itself;
* an explicit ``base_url`` argument still wins, because the connection test
  endpoint sends one before anything is saved;
* settings that name no endpoint clear a previous binding rather than
  inheriting it, so a loop over users inside one task cannot carry the first
  user's host into the rest;
* the URL still gains the chat-completions path when the user saved the
  runtime root, which is the shape people actually save.

Reads the resolved endpoint the way the dispatch does, without a network:
``_post_openai_compat`` is called with a stubbed transport and the URL it was
about to POST to is captured.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.ai import ai_client

ATTACKER = "https://attacker.example/v1"
VICTIM = "http://gpu-box.internal:11434"


def _settings(**meta: Any) -> SimpleNamespace:
    """The two attributes the resolver reads off an AISettings row."""
    return SimpleNamespace(preferred_model="ollama", metadata_=dict(meta))


class _Response:
    status_code = 200

    @staticmethod
    def raise_for_status() -> None:
        return None

    @staticmethod
    def json() -> dict[str, Any]:
        return {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 1}}


async def _dispatch_url(monkeypatch: pytest.MonkeyPatch, provider: str = "ollama", **kwargs: Any) -> str:
    """Return the URL a dispatch would POST to, without dispatching."""
    seen: dict[str, str] = {}

    class _Client:
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def post(self, url: str, **_kw: Any) -> _Response:
            seen["url"] = url
            return _Response()

    # The guard resolves DNS; the endpoint under test is a hostname that does
    # not exist, and what it resolves to is a different test's subject.
    async def _no_guard(url: str, _allow: Any = None) -> str:
        return url

    monkeypatch.setattr(ai_client.httpx, "AsyncClient", lambda *a, **k: _Client())
    monkeypatch.setattr("app.core.url_safety.resolve_and_validate_ai_provider_url", _no_guard)
    await ai_client._post_openai_compat(provider, "", [{"role": "user", "content": "hi"}], **kwargs)
    return seen["url"]


def test_one_users_endpoint_does_not_become_another_users(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> tuple[str, str]:
        # The attacker saves a public endpoint, and their own call goes there.
        ai_client.resolve_provider_and_key(_settings(ollama_base_url=ATTACKER))
        attacker_url = await _dispatch_url(monkeypatch)
        # A second user resolves their own settings and dispatches.
        ai_client.resolve_provider_and_key(_settings(ollama_base_url=VICTIM))
        victim_url = await _dispatch_url(monkeypatch)
        return attacker_url, victim_url

    attacker_url, victim_url = asyncio.run(scenario())
    assert attacker_url.startswith("https://attacker.example")
    assert victim_url.startswith("http://gpu-box.internal:11434")
    # And nothing user-supplied reached the shared table on the way through:
    # that table is what the whole process reads when nobody has bound an
    # endpoint, and writing to it is what the advisory describes.
    assert ai_client._OPENAI_COMPAT_CONFIG["ollama"]["url"].startswith("http://localhost")


def test_settings_without_an_endpoint_do_not_inherit_the_previous_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> str:
        ai_client.resolve_provider_and_key(_settings(ollama_base_url=ATTACKER))
        # Same task, next user: no endpoint of their own, so the process
        # default - not the host still bound from the resolution above.
        ai_client.resolve_provider_and_key(_settings())
        return await _dispatch_url(monkeypatch)

    url = asyncio.run(scenario())
    assert "attacker.example" not in url
    assert url == ai_client._OPENAI_COMPAT_CONFIG["ollama"]["url"]


def test_an_explicit_base_url_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    # The connection test sends the URL being tested before it is saved.
    async def scenario() -> str:
        ai_client.resolve_provider_and_key(_settings(ollama_base_url=ATTACKER))
        return await _dispatch_url(monkeypatch, base_url="http://localhost:9/v1/chat/completions")

    assert asyncio.run(scenario()) == "http://localhost:9/v1/chat/completions"


def test_saving_settings_no_longer_reaches_the_provider_table() -> None:
    # The mutator is gone rather than merely unused: a reintroduced caller
    # would restore the vulnerability in one line.
    assert not hasattr(ai_client, "update_provider_config")
    assert ai_client._OPENAI_COMPAT_CONFIG["ollama"]["url"].startswith("http://localhost")


class TestEndpointExtraction:
    """The normalisation the binding applies, in isolation."""

    def test_the_runtime_root_gains_the_chat_path(self) -> None:
        found = ai_client.self_hosted_endpoints({"ollama_base_url": "http://gpu-box:11434/"})
        assert found == {"ollama": "http://gpu-box:11434/v1/chat/completions"}

    def test_a_full_endpoint_is_left_alone(self) -> None:
        full = "http://gpu-box:11434/v1/chat/completions"
        assert ai_client.self_hosted_endpoints({"vllm_base_url": full}) == {"vllm": full}

    def test_only_the_self_hosted_runtimes_are_tunable(self) -> None:
        # Rewriting a vendor URL would send that vendor's key elsewhere.
        assert ai_client.self_hosted_endpoints({"openai_base_url": ATTACKER}) == {}

    def test_blank_and_missing_metadata_name_nothing(self) -> None:
        assert ai_client.self_hosted_endpoints(None) == {}
        assert ai_client.self_hosted_endpoints({"ollama_base_url": "   "}) == {}
