# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A stored geocoding mirror is resolved before each request, like an AI endpoint.

The mirror URL a manager saves passes the self-hosted policy by its text, but a
hostname is only a promise: it can resolve to a cloud metadata address, or be
pointed there after it was saved. Every lookup sent to the stored mirror now
resolves the name first and stays home when an answer is link-local or
metadata. The suggestion fallback to Nominatim did not check the mirror at all.
LAN answers stay allowed, a self-hosted mirror usually lives there.
"""

from __future__ import annotations

import socket

import httpx
import pytest

from app.modules.geo_hub import consent, geocoder

_ENV = (
    "OE_GEOCODER_DISABLED",
    "OE_GEOCODER_BASE_URL",
    "OE_GEOCODER_PHOTON_URL",
    "OE_GEOCODER_PHOTON_DISABLED",
)
_MIRROR = "http://geo.mirror.test"


@pytest.fixture(autouse=True)
def _stored_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    consent.invalidate_cache()

    async def _mirror(_session: object) -> tuple[str, str]:
        return ("mirror", _MIRROR)

    monkeypatch.setattr(consent, "_read_choice", _mirror)
    monkeypatch.setattr(geocoder, "_MIN_INTERVAL_SECONDS", 0)
    yield
    consent.invalidate_cache()


def _resolve_to(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    def _fake(host: str, *_a: object, **_k: object) -> list[tuple]:
        assert host == "geo.mirror.test", host
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake)


def _recording_client(hosts: list[str]) -> httpx.AsyncClient:
    def _handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(200, json=[])

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


@pytest.mark.asyncio
async def test_a_suggestion_does_not_go_to_a_mirror_that_resolves_to_metadata(monkeypatch) -> None:
    _resolve_to(monkeypatch, "169.254.169.254")
    hosts: list[str] = []
    async with _recording_client(hosts) as client:
        assert await geocoder.suggest_addresses("Hauptstrasse 1 Berlin", http_client=client) == []
    assert hosts == []


@pytest.mark.asyncio
async def test_a_lookup_does_not_go_to_a_mirror_that_resolves_to_metadata(monkeypatch) -> None:
    monkeypatch.setattr(geocoder, "_disabled", lambda: False)
    _resolve_to(monkeypatch, "100.100.100.200")
    hosts: list[str] = []
    async with _recording_client(hosts) as client:
        assert (
            await geocoder._fetch_nominatim("berlin", base_url=_MIRROR, http_client=client, resolve_host=True) is None
        )
    assert hosts == []


@pytest.mark.asyncio
async def test_a_mirror_on_the_lan_is_still_asked(monkeypatch) -> None:
    _resolve_to(monkeypatch, "10.0.0.12")
    hosts: list[str] = []
    async with _recording_client(hosts) as client:
        await geocoder.suggest_addresses("Hauptstrasse 1 Berlin", http_client=client)
    assert hosts == ["geo.mirror.test"]
