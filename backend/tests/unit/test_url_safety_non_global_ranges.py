# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The SSRF helpers block every address that is not on the public internet.

The webhook policy described itself as blocking carrier-grade NAT, but it
tested ``is_private``, and Python does not count 100.64.0.0/10 as private. So
100.64.x.x passed, and with it 100.100.100.200, the metadata service of one of
the large clouds. The webhook policy now refuses anything that is not global.

The self-hosted policy (AI runtimes, a geocoder mirror) keeps loopback, private
and carrier-grade NAT open on purpose, since a runtime on a tailnet address is
an ordinary setup, but it refuses that one metadata address by value, and it
unwraps the NAT64 form of an IPv4 address so a metadata address cannot pass
in IPv6 clothing.
"""

from __future__ import annotations

import pytest

from app.core.url_safety import UnsafeUrlError, validate_ai_provider_url, validate_external_url


@pytest.mark.parametrize(
    "url",
    [
        "http://100.64.0.1/hook",
        "http://100.100.100.200/latest/meta-data/",
        "http://192.0.0.170/",
        "http://198.18.0.1/",
        "http://[::ffff:100.100.100.200]/",
    ],
)
def test_the_webhook_policy_refuses_non_global_addresses(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_external_url(url)


def test_the_webhook_policy_still_accepts_a_public_address() -> None:
    assert validate_external_url("https://8.8.8.8/hook") == "https://8.8.8.8/hook"


@pytest.mark.parametrize(
    "url",
    [
        "http://100.100.100.200/latest/meta-data/",
        "http://[64:ff9b::a9fe:a9fe]/",
        "http://[64:ff9b::6464:64c8]/",
    ],
)
def test_the_self_hosted_policy_refuses_metadata_in_any_form(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_ai_provider_url(url)


@pytest.mark.parametrize("url", ["http://100.64.12.7:11434/v1", "http://127.0.0.1:11434/v1", "http://10.0.0.5:8000/v1"])
def test_the_self_hosted_policy_keeps_local_runtimes_reachable(url: str) -> None:
    assert validate_ai_provider_url(url) == url
