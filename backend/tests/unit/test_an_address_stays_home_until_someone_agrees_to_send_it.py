# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A site address goes to a geocoder only after the installation agreed.

Saving a project address used to send it to the public OpenStreetMap
services at once. The installation is now asked once (allow, deny or own
mirror) and nothing leaves before the answer. Environment switches set by
the deployer win over the answer.
"""

from __future__ import annotations

import httpx
import pytest

from app.modules.geo_hub import consent, geocoder

_ENV = (
    "OE_GEOCODER_DISABLED",
    "OE_GEOCODER_BASE_URL",
    "OE_GEOCODER_PHOTON_URL",
    "OE_GEOCODER_PHOTON_DISABLED",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    consent.invalidate_cache()


def test_unanswered_sends_nothing() -> None:
    out = consent.decide(None)
    assert out.state == "unanswered"
    assert not out.allowed
    assert out.photon_url is None


def test_deny_sends_nothing() -> None:
    assert not consent.decide(("deny", None)).allowed


def test_allow_uses_the_public_services() -> None:
    out = consent.decide(("allow", None))
    assert out.nominatim_url == consent.PUBLIC_NOMINATIM_URL
    assert out.photon_url == consent.PUBLIC_PHOTON_URL


def test_mirror_never_falls_back_to_public_photon() -> None:
    out = consent.decide(("mirror", "https://geo.example.org/"))
    assert out.nominatim_url == "https://geo.example.org"
    assert out.photon_url is None


def test_env_disabled_beats_an_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OE_GEOCODER_DISABLED", "true")
    out = consent.decide(("allow", None))
    assert out.state == "env_disabled"
    assert not out.allowed


def test_env_mirror_needs_no_answer_and_keeps_photon_private(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OE_GEOCODER_BASE_URL", "https://nominatim.internal")
    out = consent.decide(None)
    assert out.state == "env_mirror"
    assert out.nominatim_url == "https://nominatim.internal"
    assert out.photon_url is None
    monkeypatch.setenv("OE_GEOCODER_PHOTON_URL", "https://photon.internal")
    assert consent.decide(None).photon_url == "https://photon.internal"


def test_photon_switch_beats_an_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OE_GEOCODER_PHOTON_DISABLED", "true")
    out = consent.decide(("allow", None))
    assert out.allowed
    assert out.photon_url is None


@pytest.mark.asyncio
async def test_suggestions_make_no_request_before_an_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_answer(_session: object) -> None:
        return None

    monkeypatch.setattr(consent, "_read_choice", _no_answer)
    calls: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        assert await geocoder.suggest_addresses("Hauptstrasse 1 Berlin", http_client=client) == []
    assert calls == []


@pytest.mark.asyncio
async def test_suggestions_go_to_the_answered_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _mirror(_session: object) -> tuple[str, str]:
        return ("mirror", "https://geo.example.org")

    monkeypatch.setattr(consent, "_read_choice", _mirror)
    hosts: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        await geocoder.suggest_addresses("Hauptstrasse 1 Berlin", http_client=client)
    assert hosts == ["geo.example.org"]
