"""Evidence records for field photos: sources, precedence, grading, privacy."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from PIL import Image

from app.core import photo_evidence as pe


def _jpeg(*, gps: tuple[float, float] | None = None, taken: str | None = None, orientation: int | None = None) -> bytes:
    img = Image.new("RGB", (8, 6), (200, 10, 10))
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    exif[0x010F] = "SiteCam"
    exif[0x0110] = "Model 7"
    if taken:
        exif[0x0132] = taken
    if gps:
        lat, lon = gps

        def dms(v: float) -> tuple[float, float, float]:
            v = abs(v)
            d = int(v)
            m = int((v - d) * 60)
            s = round(((v - d) * 60 - m) * 60, 4)
            return (float(d), float(m), float(s))

        exif[0x8825] = {
            1: "N" if lat >= 0 else "S",
            2: dms(lat),
            3: "E" if lon >= 0 else "W",
            4: dms(lon),
            0x11: 135.0,
        }
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def test_exif_evidence_reads_gps_time_orientation_and_camera():
    data = _jpeg(gps=(52.52, 13.405), taken="2026:10:20 09:15:00", orientation=6)
    tags = pe.read_exif_evidence(data)
    assert tags["lat"] == pytest.approx(52.52, abs=1e-4)
    assert tags["lon"] == pytest.approx(13.405, abs=1e-4)
    assert tags["taken_at"] == "2026-10-20T09:15:00"
    assert tags["orientation"] == 6
    assert tags["make"] == "SiteCam"
    assert tags["heading_deg"] == pytest.approx(135.0)
    assert tags["width"] == 8


def test_garbage_bytes_give_no_tags_and_no_error():
    assert pe.read_exif_evidence(b"not an image") == {}


def test_device_fix_beats_exif_and_grades_full():
    data = _jpeg(gps=(48.1, 11.5))
    device = pe.DeviceCapture(lat=48.2, lon=11.6, accuracy_m=6.4, captured_at=datetime(2026, 10, 25, 8, 0, tzinfo=UTC))
    record = pe.build_evidence_record(data, path="p/1.jpg", device=device, exif=pe.read_exif_evidence(data))
    assert record["location"] == {"lat": 48.2, "lon": 11.6, "accuracy_m": 6.4, "source": "device"}
    assert record["captured_at"]["source"] == "device"
    assert record["sha256"] == pe.sha256_hex(data)
    assert record["grade"] == pe.EVIDENCE_GRADE_FULL


def test_exif_location_used_when_device_has_none():
    data = _jpeg(gps=(-33.86, 151.21), taken="2026:01:02 03:04:05")
    record = pe.build_evidence_record(data, path="x", exif=pe.read_exif_evidence(data))
    assert record["location"]["source"] == "exif"
    assert record["location"]["lat"] < 0
    assert record["captured_at"] == {"value": "2026-01-02T03:04:05", "source": "exif"}
    assert record["grade"] == pe.EVIDENCE_GRADE_FULL


def test_coarse_device_fix_is_only_basic_evidence():
    device = pe.DeviceCapture(lat=1.0, lon=2.0, accuracy_m=900.0, captured_at=datetime.now(UTC))
    record = pe.build_evidence_record(b"abc", path="x", device=device)
    assert record["grade"] == pe.EVIDENCE_GRADE_BASIC


def test_no_location_and_server_time_is_basic():
    record = pe.build_evidence_record(b"abc", path="x")
    assert record["location"] is None
    assert record["captured_at"]["source"] == "server"
    assert record["grade"] == pe.EVIDENCE_GRADE_BASIC


def test_null_island_and_out_of_range_are_rejected():
    assert pe.DeviceCapture(lat=0.0, lon=0.0).location_valid() is False
    assert pe.DeviceCapture(lat=91.0, lon=0.5).location_valid() is False
    record = pe.build_evidence_record(b"a", path="x", device=pe.DeviceCapture(lat=0.0, lon=0.0, accuracy_m=3))
    assert record["location"] is None


def test_orientation_angles_are_clamped_to_their_ranges():
    device = pe.DeviceCapture(heading_deg=400.0, pitch_deg=45.0, roll_deg=-120.0)
    record = pe.build_evidence_record(b"a", path="x", device=device)
    assert record["orientation"] == {"pitch_deg": 45.0}


def test_parse_device_capture_from_form_strings():
    capture = pe.parse_device_capture(lat="52.1", lon="13.2", accuracy_m="12", captured_at="2026-10-25T10:00:00Z")
    assert capture is not None and capture.location_valid()
    assert capture.captured_at is not None and capture.captured_at.tzinfo is not None
    assert pe.parse_device_capture() is None
    assert pe.parse_device_capture(lat="nan", lon="x") is None


def test_privacy_strip_keeps_coordinates_in_record(monkeypatch):
    monkeypatch.delenv("OE_PHOTO_KEEP_EXIF_GPS", raising=False)
    data = _jpeg(gps=(40.0, -3.7))
    stored, tags, original_sha = pe.prepare_stored_photo(data)
    assert tags["lat"] == pytest.approx(40.0, abs=1e-4)
    assert stored != data
    assert original_sha == pe.sha256_hex(data)
    assert "lat" not in pe.read_exif_evidence(stored)
    record = pe.build_evidence_record(stored, path="x", exif=tags, original_sha256=original_sha)
    assert record["original_sha256"] == original_sha
    assert record["location"]["source"] == "exif"


def test_keep_gps_setting_stores_file_untouched(monkeypatch):
    monkeypatch.setenv("OE_PHOTO_KEEP_EXIF_GPS", "true")
    data = _jpeg(gps=(40.0, -3.7))
    stored, _tags, original_sha = pe.prepare_stored_photo(data)
    assert stored == data
    assert original_sha is None
