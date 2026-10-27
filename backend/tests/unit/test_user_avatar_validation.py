# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Profile photo​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ validation: type, size, real content, and the 256 px square output."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.modules.users.avatar import (
    AVATAR_SIZE,
    MAX_AVATAR_BYTES,
    AvatarValidationError,
    process_avatar,
)


def _image(fmt: str, size: tuple[int, int] = (640, 320), mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, (200, 30, 30, 255) if mode == "RGBA" else (200, 30, 30)).save(buf, format=fmt)
    return buf.getvalue()


@pytest.mark.parametrize(("fmt", "mime"), [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")])
def test_accepted_types_become_a_256_square_png(fmt: str, mime: str) -> None:
    out = process_avatar(_image(fmt), mime)
    with Image.open(io.BytesIO(out)) as result:
        assert result.format == "PNG"
        assert result.size == (AVATAR_SIZE, AVATAR_SIZE)


def test_small_image_is_scaled_up_to_the_square() -> None:
    with Image.open(io.BytesIO(process_avatar(_image("PNG", (40, 90)), None))) as result:
        assert result.size == (AVATAR_SIZE, AVATAR_SIZE)


def test_transparency_is_kept() -> None:
    with Image.open(io.BytesIO(process_avatar(_image("PNG", (50, 50), "RGBA"), "image/png"))) as result:
        assert result.mode == "RGBA"


def test_exif_metadata_is_stripped() -> None:
    src = Image.new("RGB", (100, 100), (1, 2, 3))
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"
    buf = io.BytesIO()
    src.save(buf, format="JPEG", exif=exif)
    assert b"SecretCamera" in buf.getvalue()
    assert b"SecretCamera" not in process_avatar(buf.getvalue(), "image/jpeg")


@pytest.mark.parametrize("declared", ["image/gif", "image/svg+xml", "application/pdf", "text/html"])
def test_disallowed_declared_type_is_refused(declared: str) -> None:
    with pytest.raises(AvatarValidationError) as err:
        process_avatar(_image("PNG"), declared)
    assert err.value.rule == "users.avatar.type"


def test_gif_bytes_are_refused_even_when_declared_png() -> None:
    with pytest.raises(AvatarValidationError) as err:
        process_avatar(_image("GIF"), "image/png")
    assert err.value.rule == "users.avatar.type"


def test_declared_type_must_match_real_bytes() -> None:
    with pytest.raises(AvatarValidationError) as err:
        process_avatar(_image("JPEG"), "image/png")
    assert err.value.rule == "users.avatar.content"


def test_png_header_with_garbage_body_is_refused() -> None:
    with pytest.raises(AvatarValidationError) as err:
        process_avatar(b"\x89PNG\r\n\x1a\n" + b"not an image" * 10, "image/png")
    assert err.value.rule == "users.avatar.content"


def test_html_renamed_to_png_is_refused() -> None:
    with pytest.raises(AvatarValidationError) as err:
        process_avatar(b"<html><script>alert(1)</script></html>", "image/png")
    assert err.value.rule == "users.avatar.type"


def test_empty_file_is_refused() -> None:
    with pytest.raises(AvatarValidationError) as err:
        process_avatar(b"", "image/png")
    assert err.value.rule == "users.avatar.empty"


def test_oversize_file_is_refused() -> None:
    data = _image("PNG") + b"\0" * (MAX_AVATAR_BYTES + 1)
    with pytest.raises(AvatarValidationError) as err:
        process_avatar(data, "image/png")
    assert err.value.rule == "users.avatar.size"


def test_exactly_at_the_limit_passes_the_size_rule() -> None:
    base = _image("PNG")
    padded = base + b"\0" * (MAX_AVATAR_BYTES - len(base))
    assert len(padded) == MAX_AVATAR_BYTES
    process_avatar(padded, "image/png")
