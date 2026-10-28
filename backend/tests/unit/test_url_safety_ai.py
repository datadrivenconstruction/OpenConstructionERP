# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠SSRF policy for self-hosted AI provider endpoints (Ollama / vLLM).

Covers the GHSA-rq5j-mwq2-6558 hardening: a user-supplied AI base URL is
fetched server-side, so it must never reach a link-local / cloud-metadata
address, while loopback and private ranges stay reachable so a local runtime
(Ollama on localhost, vLLM on a Docker / LAN host) keeps working out of the box.
"""

import pytest

from app.core.url_safety import (
    UnsafeUrlError,
    resolve_and_validate_ai_provider_url,
    validate_ai_provider_url,
)

# ── Allowed by default: local runtimes must keep working ─────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1/chat/completions",  # default Ollama
        "http://127.0.0.1:11434/v1/chat/completions",
        "http://[::1]:11434/v1/chat/completions",
        "http://10.0.0.5:8001/v1/chat/completions",  # vLLM on a private net
        "http://192.168.1.20:8001/v1/chat/completions",
        "http://172.16.4.4:8001/v1/chat/completions",
        "https://ollama.internal:11434/v1/chat/completions",  # private hostname
    ],
)
def test_local_and_private_urls_allowed_without_allowlist(url: str) -> None:
    assert validate_ai_provider_url(url) == url


# ── Blocked regardless of allowlist: metadata / link-local / bad scheme ──────


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # AWS / Azure IMDS
        "http://[fd00:ec2::254]/latest/meta-data/",  # AWS IPv6 IMDS (ULA range)
        "http://metadata.google.internal/computeMetadata/v1/",  # GCP
        "http://metadata/computeMetadata/v1/",
        "http://169.254.1.1/",  # link-local
        "http://[fe80::1]/",  # IPv6 link-local
    ],
)
def test_metadata_and_linklocal_blocked(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_ai_provider_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://127.0.0.1:11211/",
        "ftp://example.com/",
        "not-a-url",
        "http://",  # missing host
    ],
)
def test_bad_scheme_or_malformed_blocked(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_ai_provider_url(url)


# ── Allowlist semantics ──────────────────────────────────────────────────────


def test_allowlist_permits_only_listed_hosts() -> None:
    allow = ["ollama.internal", "10.20.0.0/16"]
    url_host = "https://ollama.internal:11434/v1/chat/completions"
    url_cidr = "http://10.20.5.5:8001/v1/chat/completions"
    assert validate_ai_provider_url(url_host, allow) == url_host
    assert validate_ai_provider_url(url_cidr, allow) == url_cidr


def test_allowlist_rejects_unlisted_host() -> None:
    allow = ["ollama.internal"]
    with pytest.raises(UnsafeUrlError):
        validate_ai_provider_url("http://127.0.0.1:11434/v1/chat/completions", allow)
    with pytest.raises(UnsafeUrlError):
        validate_ai_provider_url("http://evil.example.com/v1/chat/completions", allow)


def test_allowlist_never_reenables_metadata() -> None:
    # Even a careless operator listing a metadata address cannot re-open it -
    # the hard block wins over the allowlist.
    allow = ["169.254.169.254"]
    with pytest.raises(UnsafeUrlError):
        validate_ai_provider_url("http://169.254.169.254/latest/meta-data/", allow)


# ── Dispatch-time DNS re-check ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_allows_localhost() -> None:
    url = "http://localhost:11434/v1/chat/completions"
    assert await resolve_and_validate_ai_provider_url(url) == url


@pytest.mark.asyncio
async def test_resolve_blocks_literal_metadata() -> None:
    with pytest.raises(UnsafeUrlError):
        await resolve_and_validate_ai_provider_url("http://169.254.169.254/latest/meta-data/")


# ── Write-time Pydantic validator on the AI settings schema ──────────────────


def test_ai_settings_update_rejects_metadata_url() -> None:
    from pydantic import ValidationError

    from app.modules.ai.schemas import AISettingsUpdate

    with pytest.raises(ValidationError):
        AISettingsUpdate(ollama_base_url="http://169.254.169.254/")
    with pytest.raises(ValidationError):
        AISettingsUpdate(vllm_base_url="http://metadata.google.internal/")


def test_ai_settings_update_accepts_localhost() -> None:
    from app.modules.ai.schemas import AISettingsUpdate

    model = AISettingsUpdate(ollama_base_url="http://localhost:11434", vllm_base_url="http://127.0.0.1:8001")
    assert model.ollama_base_url == "http://localhost:11434"
    assert model.vllm_base_url == "http://127.0.0.1:8001"
