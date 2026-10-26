# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Evidence-grade photo records for field items (punch items, defects).

A site photo used as evidence has to answer four questions later, often in a
dispute: where was it taken, when, which way was the camera pointing, and is
this still the file that was uploaded. This module turns the uploaded bytes
plus what the browser measured at capture time into one JSON record that
answers them, and grades how complete that answer is.

Two independent sources are kept side by side, never merged silently:

* ``device``: what the browser reported (geolocation with its accuracy radius,
  the capture clock, device orientation). Present only for photos taken in the
  app.
* ``exif``: what the camera wrote into the file (GPS, shutter time, EXIF
  orientation, make and model). Present for any camera photo that kept it.

The effective ``location`` and ``captured_at`` name their ``source`` so a
reader can tell a measured value from an embedded one. Pure and side-effect
free apart from reading the bytes; no database, no request objects.
"""

from __future__ import annotations

import hashlib
import io
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.match_service.extractors.photo import extract_exif_datetime, extract_exif_gps

logger = logging.getLogger(__name__)

__all__ = [
    "EVIDENCE_GRADE_BASIC",
    "EVIDENCE_GRADE_FULL",
    "EVIDENCE_GRADE_NONE",
    "MAX_GOOD_ACCURACY_M",
    "DeviceCapture",
    "build_evidence_record",
    "evidence_grade",
    "parse_device_capture",
    "prepare_stored_photo",
    "read_exif_evidence",
    "sha256_hex",
]

#: A device fix with a radius at or under this many metres counts as located.
MAX_GOOD_ACCURACY_M = 50.0

EVIDENCE_GRADE_FULL = "full"
EVIDENCE_GRADE_BASIC = "basic"
EVIDENCE_GRADE_NONE = "none"

_EXIF_ORIENTATION = 0x0112
_EXIF_MAKE = 0x010F
_EXIF_MODEL = 0x0110
_GPS_IFD = 0x8825
_GPS_ALTITUDE_REF = 0x0005
_GPS_ALTITUDE = 0x0006
_GPS_IMG_DIRECTION = 0x0011


@dataclass(frozen=True)
class DeviceCapture:
    """What the browser measured when the photo was taken.

    Every field is optional: a desktop upload carries none of them, a phone
    that denied location carries only the clock.
    """

    lat: float | None = None
    lon: float | None = None
    accuracy_m: float | None = None
    altitude_m: float | None = None
    captured_at: datetime | None = None
    heading_deg: float | None = None
    pitch_deg: float | None = None
    roll_deg: float | None = None

    def location_valid(self) -> bool:
        """True when both coordinates are finite, in range and not (0, 0)."""
        return _valid_lat_lon(self.lat, self.lon)


def sha256_hex(data: bytes) -> str:
    """Hex SHA-256 of the stored bytes (the integrity anchor of the record)."""
    return hashlib.sha256(data).hexdigest()


def _finite(value: float | None) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(float(value))


def _valid_lat_lon(lat: float | None, lon: float | None) -> bool:
    if not (_finite(lat) and _finite(lon)):
        return False
    assert lat is not None and lon is not None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return False
    return not (abs(lat) < 1e-9 and abs(lon) < 1e-9)


def _clean_angle(value: float | None, low: float, high: float) -> float | None:
    if not _finite(value):
        return None
    assert value is not None
    v = float(value)
    if v < low or v > high:
        return None
    return round(v, 2)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat()
    return dt.astimezone(UTC).isoformat()


def _rational(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return f if math.isfinite(f) else None


def read_exif_evidence(image_bytes: bytes) -> dict[str, Any]:
    """Read the evidence-relevant EXIF tags from an image.

    GPS position and shutter time come from the dependency-free reader the
    documents module already uses; orientation, make, model, altitude and
    image direction come from Pillow, which only parses the header here.
    Never raises: an unreadable block yields fewer keys, not an error.
    """
    out: dict[str, Any] = {}
    coords = extract_exif_gps(image_bytes)
    if coords is not None:
        out["lat"], out["lon"] = coords
    taken = extract_exif_datetime(image_bytes)
    if taken is not None:
        # EXIF time is the camera's local clock with no zone; keep it naive.
        out["taken_at"] = taken.isoformat()
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as img:
            out["width"], out["height"] = img.size
            exif = img.getexif()
            orientation = exif.get(_EXIF_ORIENTATION)
            if isinstance(orientation, int) and 1 <= orientation <= 8:
                out["orientation"] = orientation
            for tag, key in ((_EXIF_MAKE, "make"), (_EXIF_MODEL, "model")):
                raw = exif.get(tag)
                if isinstance(raw, str) and raw.strip():
                    out[key] = raw.strip().strip("\x00")[:80]
            gps = exif.get_ifd(_GPS_IFD) if _GPS_IFD in exif else {}
            altitude = _rational(gps.get(_GPS_ALTITUDE)) if gps else None
            if altitude is not None:
                ref = gps.get(_GPS_ALTITUDE_REF)
                below = ref in (1, b"\x01")
                out["altitude_m"] = round(-altitude if below else altitude, 2)
            direction = _rational(gps.get(_GPS_IMG_DIRECTION)) if gps else None
            if direction is not None and 0.0 <= direction <= 360.0:
                out["heading_deg"] = round(direction, 2)
    except Exception:  # noqa: BLE001 - a malformed header must not break an upload
        logger.debug("photo evidence: Pillow EXIF read failed", exc_info=True)
    return out


def build_evidence_record(
    stored_bytes: bytes,
    *,
    path: str,
    device: DeviceCapture | None = None,
    exif: dict[str, Any] | None = None,
    received_at: datetime | None = None,
    uploaded_by: str | None = None,
    original_sha256: str | None = None,
) -> dict[str, Any]:
    """Assemble the evidence record for one stored photo.

    Args:
        stored_bytes: The bytes as written to storage; their hash is recorded.
        path: The storage path the owning item lists the photo under.
        device: Browser measurements at capture time, when taken in the app.
        exif: Tags read from the original upload (see :func:`read_exif_evidence`).
            Pass the original's tags when the stored copy had its GPS stripped.
        received_at: Server receive time; defaults to now (UTC).
        uploaded_by: User id of the uploader.
        original_sha256: Hash of the upload before any privacy stripping, when
            it differs from the stored bytes.

    Returns:
        A JSON-serialisable dict. ``location`` and ``captured_at`` are the
        effective values with their ``source`` (``device`` beats ``exif``,
        since the browser fix carries an accuracy radius and the EXIF one
        does not).
    """
    received = received_at or datetime.now(UTC)
    exif = dict(exif or {})
    record: dict[str, Any] = {
        "path": path,
        "sha256": sha256_hex(stored_bytes),
        "size_bytes": len(stored_bytes),
        "received_at": _iso(received),
        "uploaded_by": uploaded_by,
        "exif": exif,
        "device": None,
        "location": None,
        "captured_at": None,
        "orientation": None,
    }
    if original_sha256 and original_sha256 != record["sha256"]:
        record["original_sha256"] = original_sha256

    if device is not None:
        dev: dict[str, Any] = {}
        if device.location_valid():
            dev["lat"] = round(float(device.lat), 7)  # type: ignore[arg-type]
            dev["lon"] = round(float(device.lon), 7)  # type: ignore[arg-type]
            if _finite(device.accuracy_m) and float(device.accuracy_m) >= 0:  # type: ignore[arg-type]
                dev["accuracy_m"] = round(float(device.accuracy_m), 1)  # type: ignore[arg-type]
            if _finite(device.altitude_m):
                dev["altitude_m"] = round(float(device.altitude_m), 2)  # type: ignore[arg-type]
        if device.captured_at is not None:
            dev["captured_at"] = _iso(device.captured_at)
        heading = _clean_angle(device.heading_deg, 0.0, 360.0)
        pitch = _clean_angle(device.pitch_deg, -180.0, 180.0)
        roll = _clean_angle(device.roll_deg, -90.0, 90.0)
        if heading is not None:
            dev["heading_deg"] = heading
        if pitch is not None:
            dev["pitch_deg"] = pitch
        if roll is not None:
            dev["roll_deg"] = roll
        record["device"] = dev or None

    dev = record["device"] or {}
    if "lat" in dev:
        record["location"] = {
            "lat": dev["lat"],
            "lon": dev["lon"],
            "accuracy_m": dev.get("accuracy_m"),
            "source": "device",
        }
    elif _valid_lat_lon(exif.get("lat"), exif.get("lon")):
        record["location"] = {"lat": exif["lat"], "lon": exif["lon"], "accuracy_m": None, "source": "exif"}

    if dev.get("captured_at"):
        record["captured_at"] = {"value": dev["captured_at"], "source": "device"}
    elif exif.get("taken_at"):
        record["captured_at"] = {"value": exif["taken_at"], "source": "exif"}
    else:
        record["captured_at"] = {"value": record["received_at"], "source": "server"}

    orientation: dict[str, Any] = {}
    for key in ("heading_deg", "pitch_deg", "roll_deg"):
        if key in dev:
            orientation[key] = dev[key]
    if "heading_deg" not in orientation and "heading_deg" in exif:
        orientation["heading_deg"] = exif["heading_deg"]
    if "orientation" in exif:
        orientation["exif_orientation"] = exif["orientation"]
    record["orientation"] = orientation or None

    record["grade"] = evidence_grade(record)
    return record


def evidence_grade(record: dict[str, Any]) -> str:
    """Grade an evidence record.

    ``full``: located within :data:`MAX_GOOD_ACCURACY_M` by the device, or by
    EXIF GPS, with a capture time from the device or the camera, and hashed.
    ``basic``: hashed with a capture time but no usable location.
    ``none``: anything less (no hash).
    """
    if not record.get("sha256"):
        return EVIDENCE_GRADE_NONE
    captured = (record.get("captured_at") or {}).get("source")
    timed = captured in ("device", "exif")
    location = record.get("location") or {}
    located = False
    if location.get("source") == "device":
        accuracy = location.get("accuracy_m")
        located = accuracy is not None and float(accuracy) <= MAX_GOOD_ACCURACY_M
    elif location.get("source") == "exif":
        located = True
    if located and timed:
        return EVIDENCE_GRADE_FULL
    return EVIDENCE_GRADE_BASIC


def _to_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _to_datetime(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_device_capture(
    *,
    lat: Any = None,
    lon: Any = None,
    accuracy_m: Any = None,
    altitude_m: Any = None,
    captured_at: Any = None,
    heading_deg: Any = None,
    pitch_deg: Any = None,
    roll_deg: Any = None,
) -> DeviceCapture | None:
    """Build a :class:`DeviceCapture` from loosely typed form fields.

    Returns ``None`` when the client sent nothing usable, so a plain desktop
    upload records no ``device`` block rather than an empty one.
    """
    capture = DeviceCapture(
        lat=_to_float(lat),
        lon=_to_float(lon),
        accuracy_m=_to_float(accuracy_m),
        altitude_m=_to_float(altitude_m),
        captured_at=_to_datetime(captured_at),
        heading_deg=_to_float(heading_deg),
        pitch_deg=_to_float(pitch_deg),
        roll_deg=_to_float(roll_deg),
    )
    if (
        not capture.location_valid()
        and capture.captured_at is None
        and capture.heading_deg is None
        and capture.pitch_deg is None
        and capture.roll_deg is None
    ):
        return None
    return capture


def prepare_stored_photo(content: bytes) -> tuple[bytes, dict[str, Any], str | None]:
    """Read EXIF from the upload, then apply the platform GPS privacy default.

    The documents module strips the GPS block from stored photo files unless
    the deployer keeps it (``OE_PHOTO_KEEP_EXIF_GPS``); field evidence follows
    the same policy so a punch photo does not leak more than a gallery photo.
    The coordinates survive in the evidence record either way.

    Returns:
        ``(stored_bytes, exif_tags, original_sha256_or_None)``. The original
        hash is returned only when stripping changed the bytes.
    """
    exif = read_exif_evidence(content)
    try:
        from app.modules.documents.service import _keep_photo_gps, _strip_exif_gps
    except Exception:  # noqa: BLE001 - documents module absent: store untouched
        return content, exif, None
    if _keep_photo_gps():
        return content, exif, None
    stripped = _strip_exif_gps(content)
    if stripped is content or stripped == content:
        return content, exif, None
    exif["gps_stripped_from_file"] = True
    return stripped, exif, sha256_hex(content)
