# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the workspace logo validation rules."""

from __future__ import annotations

import base64

import pytest

from app.core.logo_validation import MAX_LOGO_BYTES, LogoValidationError, sanitise_svg, validate_logo_data_url

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _url(mime: str, data: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _rule(value: str) -> str:
    with pytest.raises(LogoValidationError) as info:
        validate_logo_data_url(value)
    return info.value.rule


def test_png_passes() -> None:
    assert validate_logo_data_url(_url("image/png", _PNG)).startswith("data:image/png;base64,")


def test_gif_type_is_refused() -> None:
    assert _rule(_url("image/gif", b"GIF89a")) == "branding.logo.type"


def test_oversize_is_refused() -> None:
    assert _rule(_url("image/png", _PNG + b"\x00" * MAX_LOGO_BYTES)) == "branding.logo.size"


def test_webp_bytes_must_match() -> None:
    assert _rule(_url("image/webp", _PNG)) == "branding.logo.content"


def test_svg_unsafe_parts_are_removed() -> None:
    raw = (
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        b"<script>alert(1)</script><foreignObject><div/></foreignObject>"
        b'<a xlink:href="javascript:alert(1)"><circle r="2" onmouseover="x()"/></a>'
        b'<image href="https://evil.example/x.png"/><rect style="fill:url(http://x)"/></svg>'
    )
    out = sanitise_svg(raw).decode()
    for bad in ("script", "foreignObject", "javascript", "onmouseover", "evil.example", "url(http"):
        assert bad not in out
    assert "circle" in out


def test_svg_entity_bomb_is_refused() -> None:
    bomb = b'<!DOCTYPE s [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>'
    assert _rule(_url("image/svg+xml", bomb)) == "branding.logo.svg"


def test_svg_without_drawing_is_refused() -> None:
    only_script = b'<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>'
    assert _rule(_url("image/svg+xml", only_script)) == "branding.logo.svg"
