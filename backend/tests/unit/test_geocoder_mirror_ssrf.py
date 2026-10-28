# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A geocoding mirror may live on the LAN, but never on a metadata address.

A manager answering the geocoding question can name a private Nominatim
mirror, and every address lookup is then sent there from the server. The URL
was checked only for an ``http(s)://`` prefix. A self-hosted mirror usually
sits on a private address, so the self-hosted policy applies, the same one the
AI runtimes use: loopback and private stay allowed, link-local and the cloud
metadata addresses do not, at save time and again before each request.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.geo_hub import geocoder
from app.modules.geo_hub.schemas import GeocodingConsentUpdate


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest",
        "http://metadata.google.internal/",
        "http://100.100.100.200/",
        "file:///etc/passwd",
    ],
)
def test_a_metadata_mirror_is_refused(url: str) -> None:
    with pytest.raises(ValidationError):
        GeocodingConsentUpdate(choice="mirror", mirror_url=url)


@pytest.mark.parametrize("url", ["http://10.0.0.12:8080", "http://nominatim.lan", "https://geo.example.com"])
def test_a_lan_or_public_mirror_is_accepted(url: str) -> None:
    assert GeocodingConsentUpdate(choice="mirror", mirror_url=url).mirror_url == url


class _NeverCalled:
    async def get(self, *_: object, **__: object) -> object:
        raise AssertionError("the geocoder sent a request to a blocked mirror")


@pytest.mark.asyncio
async def test_the_geocoder_does_not_call_a_stored_metadata_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geocoder, "_disabled", lambda: False)
    monkeypatch.setattr(geocoder, "_MIN_INTERVAL_SECONDS", 0)
    result = await geocoder._fetch_nominatim(
        "berlin", base_url="http://169.254.169.254/latest", http_client=_NeverCalled()
    )
    assert result is None


@pytest.mark.asyncio
async def test_photon_does_not_call_a_stored_metadata_mirror() -> None:
    result = await geocoder._photon_suggest(
        "berlin", limit=5, http_client=_NeverCalled(), base_url="http://169.254.169.254/latest"
    )
    assert result == []
