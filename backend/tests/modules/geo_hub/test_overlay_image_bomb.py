"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An image header declaring an implausible surface answers 413, not a bare 500.

Pillow reads the declared width and height off the header and refuses to open
anything far above ``Image.MAX_IMAGE_PIXELS``, so a few dozen bytes are enough
to trigger it. The exception it raises is not a ``ValueError``, which is the
only failure the overlay upload used to handle, so it travelled past every
handler between the rasteriser and the client and surfaced as an unexplained
500 on a request the server had in fact understood and deliberately refused.
"""

from __future__ import annotations

import struct
import zlib

import pytest


def _png_header(width: int, height: int) -> bytes:
    """A structurally valid PNG whose IHDR declares ``width`` x ``height``.

    The pixel data is a stub: the decompression-bomb check runs off the header
    before any decode, so the file never needs to carry a real image.
    """

    def _chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(b"\x00" * 10))
        + _chunk(b"IEND", b"")
    )


@pytest.mark.asyncio
async def test_oversized_image_header_answers_413_rather_than_500(
    http_client,
    tenant_a,
):
    payload = _png_header(30_000, 30_000)
    # The magic bytes are genuine, so the signature gate passes this through
    # to the rasteriser rather than rejecting it as a mislabelled upload.
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")

    res = await http_client.post(
        "/api/v1/geo-hub/raster-overlays/upload-image",
        data={"project_id": tenant_a["project_id"]},
        files={"file": ("huge.png", payload, "image/png")},
        headers=tenant_a["headers"],
    )

    assert res.status_code == 413, res.text
    assert "pixels" in res.json()["detail"]
