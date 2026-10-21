# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""OE_CSP_CONNECT_SRC_EXTRA extends connect-src with vetted origins only."""

from __future__ import annotations

import pytest

from app.middleware.security_headers import parse_csp_connect_extra


def test_valid_origins_are_kept() -> None:
    raw = "https://api.example.com, https://tiles.example.org:8443,http://localhost:9000"
    assert parse_csp_connect_extra(raw) == [
        "https://api.example.com",
        "https://tiles.example.org:8443",
        "http://localhost:9000",
    ]


@pytest.mark.parametrize(
    "bad",
    ["*", "https://*.example.com", "https://example.com/path", "http://example.com", "example.com", "https://"],
)
def test_invalid_origins_are_dropped(bad: str) -> None:
    assert parse_csp_connect_extra(bad) == []


def test_empty_and_none() -> None:
    assert parse_csp_connect_extra("") == []
    assert parse_csp_connect_extra(None) == []
