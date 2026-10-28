# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Outbound webhook senders must refuse SSRF-unsafe target URLs.

Discord / Slack / Teams webhook URLs are configured by a tenant admin and
POSTed to server-side, so a URL pointing at loopback, a private LAN address,
link-local (which covers the cloud-metadata address), or a non-http(s) scheme
must be rejected at dispatch, before any network call is made. A normal public
webhook URL still goes through. The senders reuse ``app.core.url_safety`` for
this, the same guard the integration config path already applies.
"""

import httpx
import pytest

from app.modules.integrations import discord, slack, teams

pytestmark = pytest.mark.asyncio

# (sender coroutine, success status code it returns True on)
_SENDERS = [
    (discord.send_discord_notification, 204),
    (slack.send_slack_notification, 200),
    (teams.send_teams_notification, 202),
]

# Every one of these is blocked by the synchronous validator (literal IPs and
# blocked hostnames need no DNS), so a working guard rejects them before the
# HTTP client is ever constructed.
_BLOCKED_URLS = [
    "http://127.0.0.1/hook",  # loopback
    "http://localhost/hook",  # loopback hostname
    "http://169.254.169.254/latest/",  # link-local / cloud metadata
    "http://10.0.0.5/hook",  # private RFC1918
    "http://192.168.1.10/hook",  # private RFC1918
    "file:///etc/passwd",  # non-http scheme
    "gopher://internal/x",  # non-http scheme
]


class _ExplodingClient:
    """Constructing this means the SSRF guard failed to block first."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("HTTP client constructed for a blocked URL")


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.text = "ok"

    def json(self) -> dict:
        return {"ok": True}


@pytest.mark.parametrize("bad_url", _BLOCKED_URLS)
@pytest.mark.parametrize("sender_status", _SENDERS, ids=lambda s: s[0].__name__)
async def test_sender_refuses_unsafe_url(monkeypatch, sender_status, bad_url):
    sender, _status = sender_status
    monkeypatch.setattr(httpx, "AsyncClient", _ExplodingClient)
    result = await sender(bad_url, "Title", "Message")
    assert result is False


@pytest.mark.parametrize("sender_status", _SENDERS, ids=lambda s: s[0].__name__)
async def test_sender_allows_public_literal_ip(monkeypatch, sender_status):
    # A public literal IP passes the guard with no DNS lookup and is dispatched
    # to unchanged, so the guard does not break legitimate webhooks.
    sender, status = sender_status
    captured: dict[str, str] = {}

    class _RecordingClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "_RecordingClient":
            return self

        async def __aexit__(self, *exc) -> bool:
            return False

        async def post(self, url, **kwargs):
            captured["url"] = url
            return _FakeResponse(status)

    monkeypatch.setattr(httpx, "AsyncClient", _RecordingClient)
    url = "https://93.184.216.34/api/webhooks/1/token"
    result = await sender(url, "Title", "Message")
    assert result is True
    assert captured["url"] == url
