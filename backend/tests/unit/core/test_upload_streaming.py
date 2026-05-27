"""Unit tests for ``app.core.upload_streaming``.

Covers:

* :func:`stream_upload_to_temp` — the chunked-write context manager
  that spools an ``UploadFile`` to a real temp file rather than
  buffering its body in memory.
* :func:`proportional_timeout` — derives a subprocess timeout from
  the input file size so the fixed 300 s ceiling that used to cap
  legitimate uploads at ~30 MB is gone.

Tests are pure-Python and never touch the disk outside ``tmp_path``.
"""

from __future__ import annotations

import io

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.core.upload_streaming import (
    proportional_timeout,
    stream_upload_to_temp,
)

# ---------------------------------------------------------------------------
# proportional_timeout
# ---------------------------------------------------------------------------


class TestProportionalTimeout:
    def test_zero_bytes_returns_floor(self):
        """A 0-byte input still gets the floor (10 min default)."""
        assert proportional_timeout(0) == 600.0

    def test_small_file_returns_floor(self):
        """A 10 MB DXF gets the floor — converter startup overhead matters."""
        assert proportional_timeout(10 * 1024 * 1024) == 600.0

    def test_80mb_dwg_scales_linearly(self):
        """An 80 MB DWG city plan — the original 300 s ceiling killed these."""
        # 80 MB * 30 s/MB = 2400 s = 40 min — comfortably above the
        # converter's typical 90-180 s wall-time at this size.
        assert proportional_timeout(80 * 1024 * 1024) == 2400.0

    def test_200mb_rvt_gets_100_minutes(self):
        """A 200 MB hospital RVT model — needs proportional headroom."""
        assert proportional_timeout(200 * 1024 * 1024) == 6000.0

    def test_5gb_federation_stays_within_max_when_set(self):
        """``max_sec`` caps runaway timeouts even on multi-GB inputs."""
        five_gb = 5 * 1024 * 1024 * 1024
        # Default unbounded — would be 153 600 s (~42 h)
        assert proportional_timeout(five_gb) > 100_000.0
        # With explicit cap
        capped = proportional_timeout(five_gb, max_sec=3600.0)
        assert capped == 3600.0

    def test_custom_floor_and_per_mb_rate(self):
        """Callers can override the floor / per-MB rate for tuning."""
        secs = proportional_timeout(
            50 * 1024 * 1024,
            min_sec=120.0,
            sec_per_mb=10.0,
        )
        # 50 * 10 = 500 s; floor 120 s; max(120, 500) = 500
        assert secs == 500.0

    def test_negative_size_treated_as_zero(self):
        """Defensive: negative ``size_bytes`` does not produce negative timeout."""
        assert proportional_timeout(-1024) == 600.0


# ---------------------------------------------------------------------------
# stream_upload_to_temp
# ---------------------------------------------------------------------------


def _make_upload_file(payload: bytes, filename: str = "test.bin") -> UploadFile:
    """Build a Starlette UploadFile around an in-memory bytes payload.

    The constructor accepts a ``SpooledTemporaryFile``-like object —
    ``BytesIO`` works because UploadFile only needs ``read`` / ``seek``.
    """
    spool = io.BytesIO(payload)
    return UploadFile(
        file=spool,
        filename=filename,
        size=len(payload),
        headers=Headers({"content-type": "application/octet-stream"}),
    )


class TestStreamUploadToTemp:
    @pytest.mark.asyncio
    async def test_small_payload_written_to_temp(self, tmp_path):
        """A 4 KB payload survives the spool round-trip byte-for-byte."""
        payload = b"hello world" * 400  # 4.4 KB
        file = _make_upload_file(payload)

        async with stream_upload_to_temp(file) as upload:
            assert upload.size == len(payload)
            assert upload.path.exists()
            assert upload.path.read_bytes() == payload
            assert upload.head.startswith(b"hello world")

    @pytest.mark.asyncio
    async def test_temp_file_cleaned_up_on_exit(self):
        """The context manager removes the spool when the caller doesn't move it."""
        file = _make_upload_file(b"x" * 1024)
        temp_path = None
        async with stream_upload_to_temp(file) as upload:
            temp_path = upload.path
            assert temp_path.exists()
        # After exit the file is gone.
        assert not temp_path.exists()

    @pytest.mark.asyncio
    async def test_consumed_path_not_recreated(self, tmp_path):
        """If the caller moves the spool elsewhere, exit does not raise."""
        file = _make_upload_file(b"payload")
        dest = tmp_path / "moved"
        async with stream_upload_to_temp(file) as upload:
            upload.path.rename(dest)
            assert not upload.path.exists()
            assert dest.exists()
        # Exit on a missing path must be silent.
        assert dest.exists()

    @pytest.mark.asyncio
    async def test_large_payload_streamed_chunked(self):
        """A 5 MB payload streams through the 1 MB chunk loop without OOM.

        We verify the spool ends up correct and that the SHA-256 matches
        a re-hash of the original — proves we didn't drop any bytes at
        chunk boundaries.
        """
        import hashlib

        payload = (b"abcdefgh" * 128) * 5120  # 5 MB
        expected_hash = hashlib.sha256(payload).hexdigest()
        file = _make_upload_file(payload)

        async with stream_upload_to_temp(file) as upload:
            assert upload.size == len(payload)
            assert upload.sha256_hex == expected_hash
            assert upload.path.read_bytes() == payload

    @pytest.mark.asyncio
    async def test_head_truncated_to_64_bytes(self):
        """Magic-byte buffer is bounded regardless of payload size."""
        payload = b"%PDF-1.7\n" + b"x" * 10_000
        file = _make_upload_file(payload)

        async with stream_upload_to_temp(file) as upload:
            assert len(upload.head) == 64
            assert upload.head.startswith(b"%PDF-1.7\n")

    @pytest.mark.asyncio
    async def test_max_bytes_optional_cap(self):
        """``max_bytes`` raises ValueError when exceeded — opt-in soft cap."""
        file = _make_upload_file(b"x" * (2 * 1024 * 1024))  # 2 MB
        with pytest.raises(ValueError, match="exceeds maximum size"):
            async with stream_upload_to_temp(file, max_bytes=1024) as _upload:
                pass

    @pytest.mark.asyncio
    async def test_max_bytes_none_no_cap(self):
        """Default ``max_bytes=None`` accepts any size (product policy)."""
        # 3 MB — would trip a typical 1 MB cap, but None disables it.
        file = _make_upload_file(b"x" * (3 * 1024 * 1024))
        async with stream_upload_to_temp(file) as upload:
            assert upload.size == 3 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_suffix_applied_to_temp_path(self):
        """Optional suffix preserves extension for downstream tools."""
        file = _make_upload_file(b"AC1032" + b"\x00" * 100)
        async with stream_upload_to_temp(file, suffix=".dwg") as upload:
            assert upload.path.suffix == ".dwg"
