# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠OOM hardening for the documents photo upload path.

A raster photo's PIXEL count, not its byte size, is what OOMs the decoder: a
few-MB file can declare ~150 MP and expand to hundreds of MB of RGB on decode,
OOM-killing the single-worker container on the 3 GB target box (and blocking
the event loop while it does). These tests pin the guard added to
``documents.service``:

* an over-cap image is rejected with a clean 413 - never a 500 or a process
  death - both via the explicit dimension check (1x-2x the cap) and via
  Pillow's own DecompressionBomb guard (> 2x the cap);
* a header we cannot parse is NOT fatal (the magic-byte gate already vouched
  for the bytes; the thumbnail stays best-effort);
* a normal image passes the check and still thumbnails within the size cap;
* the thumbnail runs off the event loop (``asyncio.to_thread``) and the
  offloaded call writes byte-identical output to a direct call;
* even if the upfront gate were bypassed, the thumbnail path degrades to a
  clean ``False`` on an over-cap image instead of OOMing.

Pure unit tests: no DB, no app boot. The oversized case is simulated by
shrinking ``MAX_PHOTO_PIXELS`` rather than allocating a real 64 MP buffer.
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

import pytest

pytest.importorskip("PIL")

from fastapi import HTTPException  # noqa: E402
from PIL import Image  # noqa: E402

from app.modules.documents import service as doc_service  # noqa: E402
from app.modules.documents.service import (  # noqa: E402
    _ensure_photo_within_pixel_cap,
    _generate_photo_thumbnail,
)


def _png_bytes(width: int, height: int, color: tuple[int, int, int] = (120, 130, 140)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _restore_pillow_pixel_limit():
    """Isolate the process-global ``Image.MAX_IMAGE_PIXELS`` across tests.

    ``_ensure_photo_within_pixel_cap`` / ``_generate_photo_thumbnail`` set it as
    a side effect, so restore the pre-test value so an unrelated test that uses
    Pillow is never surprised by a shrunk cap left behind here.
    """
    original = Image.MAX_IMAGE_PIXELS
    try:
        yield
    finally:
        Image.MAX_IMAGE_PIXELS = original


def test_normal_image_passes_pixel_cap() -> None:
    # 64x64 = 4096 px, far under the 64 MP production cap - no raise.
    _ensure_photo_within_pixel_cap(_png_bytes(64, 64))


def test_oversized_image_rejected_via_dimension_check(monkeypatch: pytest.MonkeyPatch) -> None:
    # Shrink the cap so a small test image counts as oversized without
    # allocating a real 64 MP buffer. 40x40 = 1600 px; cap 1000 and 1600 < 2x
    # (2000), so Pillow does NOT raise its own bomb error - the explicit
    # dimension check must be what rejects it.
    monkeypatch.setattr(doc_service, "MAX_PHOTO_PIXELS", 1000)
    with pytest.raises(HTTPException) as exc:
        _ensure_photo_within_pixel_cap(_png_bytes(40, 40))
    assert exc.value.status_code == 413
    detail = exc.value.detail.lower()
    assert "pixels" in detail or "resolution" in detail


def test_oversized_image_rejected_via_decompression_bomb(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cap 100 -> 40x40 (1600 px) is > 2x the cap, so Pillow's DecompressionBomb
    # guard raises during open; the helper must still surface a clean 413.
    monkeypatch.setattr(doc_service, "MAX_PHOTO_PIXELS", 100)
    with pytest.raises(HTTPException) as exc:
        _ensure_photo_within_pixel_cap(_png_bytes(40, 40))
    assert exc.value.status_code == 413


def test_unreadable_header_is_not_fatal() -> None:
    # Bytes that pass the magic-byte gate (PNG signature) but Pillow cannot
    # actually parse: the pixel-cap check defers (no raise) rather than block a
    # file the upstream gate already accepted.
    _ensure_photo_within_pixel_cap(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)


def test_normal_image_still_thumbnails(tmp_path: Path) -> None:
    dest = tmp_path / "thumb.jpg"
    ok = _generate_photo_thumbnail(_png_bytes(800, 600), dest)
    assert ok is True
    assert dest.exists() and dest.stat().st_size > 0
    with Image.open(dest) as img:
        assert max(img.size) <= 512  # honours PHOTO_THUMB_MAX_SIDE


def test_thumbnail_offload_returns_same_bytes(tmp_path: Path) -> None:
    src = _png_bytes(400, 300)
    direct_dest = tmp_path / "direct.jpg"
    thread_dest = tmp_path / "thread.jpg"

    assert _generate_photo_thumbnail(src, direct_dest) is True

    async def _run() -> bool:
        return await asyncio.to_thread(_generate_photo_thumbnail, src, thread_dest)

    assert asyncio.run(_run()) is True
    # Deterministic encoder settings -> identical bytes whether run inline or
    # offloaded to a worker thread.
    assert direct_dest.read_bytes() == thread_dest.read_bytes()


def test_over_cap_thumbnail_degrades_to_false(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Even if the upfront gate were somehow bypassed, the thumbnail path must
    # degrade to a clean False (no thumbnail written) instead of OOMing.
    monkeypatch.setattr(doc_service, "MAX_PHOTO_PIXELS", 100)
    dest = tmp_path / "t.jpg"
    ok = _generate_photo_thumbnail(_png_bytes(40, 40), dest)
    assert ok is False
    assert not dest.exists()
