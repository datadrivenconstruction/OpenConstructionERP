# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A self-hosted AI endpoint is checked again at the moment it is called.

GHSA-rq5j-mwq2-6558 was closed in two places: the settings schema refuses a
metadata or link-local URL when it is saved, and the dispatch re-resolves the
URL right before the POST. Only the first half was pinned by a test. The
second is the half that matters for a URL saved before the schema check
existed, written by an import, or a hostname that resolves inward after it was
saved, and removing it left every test green. These tests reach the dispatch
with such a URL already stored and require that nothing is sent.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.url_safety import UnsafeUrlError
from app.modules.ai import ai_client


class _NoNetwork:
    async def __aenter__(self) -> _NoNetwork:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def post(self, url: str, **_kw: Any) -> None:
        raise AssertionError(f"the dispatch sent a request to {url}")


@pytest.mark.parametrize("provider", ["ollama", "vllm"])
@pytest.mark.parametrize(
    "stored",
    ["http://169.254.169.254/latest/meta-data", "http://[fd00:ec2::254]/", "http://metadata.google.internal/"],
)
def test_a_stored_metadata_endpoint_is_refused_at_dispatch(
    monkeypatch: pytest.MonkeyPatch, provider: str, stored: str
) -> None:
    monkeypatch.setattr(ai_client.httpx, "AsyncClient", lambda *a, **k: _NoNetwork())
    # Bound the way a saved row binds it, without passing the schema validator.
    ai_client.resolve_provider_and_key(
        SimpleNamespace(preferred_model=provider, metadata_={f"{provider}_base_url": stored})
    )

    async def scenario() -> None:
        await ai_client._post_openai_compat(provider, "", [{"role": "user", "content": "hi"}])

    with pytest.raises(UnsafeUrlError):
        asyncio.run(scenario())


def test_an_explicit_metadata_base_url_is_refused_at_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_client.httpx, "AsyncClient", lambda *a, **k: _NoNetwork())

    async def scenario() -> None:
        await ai_client._post_openai_compat(
            "ollama", "", [{"role": "user", "content": "hi"}], base_url="http://169.254.169.254/v1/chat/completions"
        )

    with pytest.raises(UnsafeUrlError):
        asyncio.run(scenario())
