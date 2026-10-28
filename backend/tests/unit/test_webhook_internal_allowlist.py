# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An administrator can open webhooks to named internal hosts, and only to those.

A self-hosted company often runs the tool it wants events in (a workflow
engine, a chat server) on its own LAN, so refusing every private address breaks
a legitimate setup. ``OE_WEBHOOK_INTERNAL_ALLOWLIST`` takes hostnames and CIDR
ranges, and a webhook whose host is listed, or whose address falls inside a
listed range, may be private or loopback. What a webhook never reaches, listed
or not: link-local, the cloud metadata addresses, multicast and unspecified.
Without the setting nothing changes: every non-global address is refused.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Iterator

import pytest

from app.config import get_settings
from app.core import url_safety
from app.core.url_safety import UnsafeUrlError, resolve_and_validate_external_url, validate_external_url


@pytest.fixture
def allowlist(monkeypatch: pytest.MonkeyPatch) -> Iterator[callable]:
    def _set(value: str | None) -> None:
        if value is None:
            monkeypatch.delenv("OE_WEBHOOK_INTERNAL_ALLOWLIST", raising=False)
        else:
            monkeypatch.setenv("OE_WEBHOOK_INTERNAL_ALLOWLIST", value)
        get_settings.cache_clear()

    yield _set
    monkeypatch.delenv("OE_WEBHOOK_INTERNAL_ALLOWLIST", raising=False)
    get_settings.cache_clear()


def test_without_the_setting_a_lan_target_is_refused(allowlist) -> None:
    allowlist(None)
    with pytest.raises(UnsafeUrlError):
        validate_external_url("http://10.0.0.7/hook")


@pytest.mark.parametrize(
    ("setting", "url"),
    [
        ("10.0.0.0/8", "http://10.0.0.7/hook"),
        ("127.0.0.1", "http://127.0.0.1:5678/webhook"),
        ("n8n.lan", "http://n8n.lan:5678/webhook"),
        ("localhost", "http://localhost:5678/webhook"),
        ("100.64.0.0/10", "http://100.64.3.4/hook"),
    ],
)
def test_a_listed_internal_target_is_accepted(allowlist, setting: str, url: str) -> None:
    allowlist(setting)
    assert validate_external_url(url) == url


@pytest.mark.parametrize(
    ("setting", "url"),
    [
        ("169.254.0.0/16", "http://169.254.169.254/latest/meta-data/"),
        ("100.64.0.0/10", "http://100.100.100.200/"),
        ("metadata.google.internal", "http://metadata.google.internal/"),
        ("fc00::/7", "http://[fd00:ec2::254]/"),
        ("0.0.0.0/0", "http://0.0.0.0/"),
    ],
)
def test_metadata_and_link_local_stay_blocked_even_when_listed(allowlist, setting: str, url: str) -> None:
    allowlist(setting)
    with pytest.raises(UnsafeUrlError):
        validate_external_url(url)


def test_a_listed_range_does_not_open_an_unlisted_one(allowlist) -> None:
    allowlist("10.20.0.0/16")
    with pytest.raises(UnsafeUrlError):
        validate_external_url("http://10.30.0.1/hook")


def test_a_name_resolving_into_a_listed_range_is_accepted_at_dispatch(allowlist, monkeypatch) -> None:
    allowlist("10.0.0.0/8")

    async def scenario() -> str:
        loop = asyncio.get_running_loop()

        async def _fake(*_a: object, **_k: object) -> list[tuple]:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0))]

        monkeypatch.setattr(loop, "getaddrinfo", _fake)
        return await resolve_and_validate_external_url("http://chat.corp/hook")

    assert asyncio.run(scenario()) == "http://chat.corp/hook"


def test_a_name_resolving_to_metadata_is_refused_at_dispatch_even_when_listed(allowlist, monkeypatch) -> None:
    allowlist("chat.corp,169.254.0.0/16")

    async def scenario() -> str:
        loop = asyncio.get_running_loop()

        async def _fake(*_a: object, **_k: object) -> list[tuple]:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

        monkeypatch.setattr(loop, "getaddrinfo", _fake)
        return await resolve_and_validate_external_url("http://chat.corp/hook")

    with pytest.raises(UnsafeUrlError):
        asyncio.run(scenario())


def test_blocked_reason_names_the_setting(allowlist) -> None:
    allowlist(None)
    assert url_safety.external_url_block_reason("http://10.0.0.7/hook") == "internal_address"
    assert url_safety.external_url_block_reason("http://169.254.169.254/") == "metadata_address"
    assert url_safety.external_url_block_reason("https://hooks.example.com/x") is None


def test_the_admin_list_shows_why_a_stored_target_is_not_delivered(allowlist) -> None:
    import datetime as _dt
    import uuid as _uuid

    from app.modules.notifications.models import WebhookTarget
    from app.modules.notifications.router import _webhook_to_response

    now = _dt.datetime.now(_dt.UTC)

    def _row(url: str) -> WebhookTarget:
        return WebhookTarget(
            id=_uuid.uuid4(),
            name="t",
            url=url,
            event_filter="*",
            active=True,
            failure_count=0,
            created_at=now,
            updated_at=now,
        )

    allowlist(None)
    assert _webhook_to_response(_row("http://10.0.0.7/hook")).blocked_reason == "internal_address"
    assert _webhook_to_response(_row("http://169.254.169.254/")).blocked_reason == "metadata_address"
    assert _webhook_to_response(_row("https://hooks.example.com/x")).blocked_reason is None
    allowlist("10.0.0.0/8")
    assert _webhook_to_response(_row("http://10.0.0.7/hook")).blocked_reason is None
