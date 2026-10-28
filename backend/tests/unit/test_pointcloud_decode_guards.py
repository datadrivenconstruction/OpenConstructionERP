# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠OOM guards for the point-cloud inline decode path.

Two front-door guards keep ``get_points`` from OOMing the 3 GB core:

* a byte cap on the object pull (``_spill_stream_to_temp``) - the object is
  streamed to a temp file and refused with HTTP 413 the moment it exceeds the
  cap, instead of ``read_bytes`` pulling the whole 5-200 GB blob into RAM; and
* a header point-count ceiling (``_enforce_point_ceiling``) - a scan whose
  header declares more points than the inline ceiling is refused before the
  decoder materialises it, so a LAZ/E57 decompression bomb cannot allocate.

Plus the truncation signal (``PointsPayload.truncated``). Pure/DB-free: no laspy,
no pye57, no storage, no session.
"""

from __future__ import annotations

import contextlib
import os
import tempfile

import pytest
from fastapi import HTTPException

from app.modules.pointcloud.decode import (
    DEFAULT_MAX_TOTAL_POINTS,
    PointDecodeTooLarge,
    _enforce_point_ceiling,
)
from app.modules.pointcloud.service import PointsPayload, _spill_stream_to_temp

# ── Header point-count ceiling ──────────────────────────────────────────────


def test_ceiling_raises_above_the_cap() -> None:
    with pytest.raises(PointDecodeTooLarge) as exc:
        _enforce_point_ceiling(200, 100)
    assert exc.value.total_count == 200
    assert exc.value.max_total_points == 100


def test_ceiling_allows_at_or_below_the_cap() -> None:
    _enforce_point_ceiling(100, 100)
    _enforce_point_ceiling(0, 100)


def test_ceiling_of_zero_disables_the_guard() -> None:
    # A non-positive ceiling is an explicit "no limit" - never raise.
    _enforce_point_ceiling(10**12, 0)


def test_default_ceiling_is_positive() -> None:
    assert DEFAULT_MAX_TOTAL_POINTS > 0


# ── Truncation signal ───────────────────────────────────────────────────────


def test_points_payload_flags_a_decimated_preview() -> None:
    assert PointsPayload(b"", total_count=100, returned_count=50).truncated is True


def test_points_payload_full_scan_is_not_truncated() -> None:
    assert PointsPayload(b"", total_count=50, returned_count=50).truncated is False


# ── Capped streamed spill ───────────────────────────────────────────────────


async def _agen(chunks: list[bytes]):
    for chunk in chunks:
        yield chunk


async def test_spill_under_cap_writes_every_byte() -> None:
    path = await _spill_stream_to_temp(_agen([b"abc", b"defg"]), suffix=".las", max_bytes=1000)
    try:
        assert os.path.exists(path)
        with open(path, "rb") as fh:
            assert fh.read() == b"abcdefg"
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


async def test_spill_over_cap_raises_413_and_leaves_no_temp_file(monkeypatch) -> None:
    # Capture the temp path mkstemp hands the helper so we can prove the partial
    # file is cleaned up when the cap trips (no disk leak on a rejected upload).
    created: dict[str, str] = {}
    real_mkstemp = tempfile.mkstemp

    def _spy_mkstemp(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        created["name"] = name
        return fd, name

    monkeypatch.setattr(tempfile, "mkstemp", _spy_mkstemp)

    with pytest.raises(HTTPException) as exc:
        await _spill_stream_to_temp(_agen([b"x" * 600, b"y" * 600]), suffix=".las", max_bytes=1000)

    assert exc.value.status_code == 413
    assert not os.path.exists(created["name"])


async def test_spill_with_no_cap_writes_through() -> None:
    # max_bytes <= 0 disables the cap (matches the "no limit" contract).
    path = await _spill_stream_to_temp(_agen([b"z" * 5000]), suffix=".las", max_bytes=0)
    try:
        assert os.path.getsize(path) == 5000
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)
