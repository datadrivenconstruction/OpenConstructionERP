# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Photo element → envelope adapter + EXIF GPS extraction.

The envelope adapter exercises the matcher interface end-to-end with a
partial-quality envelope so the rest of the system doesn't block waiting
on the full CV pipeline (PaddleOCR + YOLO, a separate multi-week build).

``extract_exif_gps`` is a real, dependency-light EXIF GPS reader used by
the photo-upload flow to auto-fill a photo's latitude/longitude when the
camera embedded geotags. It parses the JPEG APP1 / raw-TIFF EXIF block by
hand (no Pillow requirement) so it works in a minimal install, and only
returns coordinates it could actually decode - never a fabricated value.

# v2.8 follow-up: depends on CV pipeline build (B=full CV pipeline from scratch)
# Tracked in: the architecture guide Phase 3 "AI Takeoff" → ``services/cv-pipeline/``.
# Replace ``description`` synthesis with the structured CV output
# (object detections + dimension OCR + symbol classification).
"""

from __future__ import annotations

import logging
import struct
from datetime import datetime
from typing import Any

from app.core.match_service.envelope import ElementEnvelope
from app.core.match_service.extractors._helpers import build_envelope_base

logger = logging.getLogger(__name__)

# EXIF tag ids we care about.
_GPS_IFD_TAG = 0x8825  # pointer (in IFD0) to the GPS sub-IFD
_GPS_LAT_REF = 0x0001
_GPS_LAT = 0x0002
_GPS_LON_REF = 0x0003
_GPS_LON = 0x0004

# Date/time tags. ``DateTimeOriginal`` (when the shutter fired) lives in the
# Exif sub-IFD pointed to by tag 0x8769 in IFD0; ``DateTime`` (file change /
# digitised) is a plain IFD0 tag and is used only as a fallback.
_EXIF_IFD_TAG = 0x8769  # pointer (in IFD0) to the Exif sub-IFD
_DATETIME_ORIGINAL = 0x9003  # in the Exif sub-IFD
_DATETIME = 0x0132  # in IFD0

# TIFF field type → (struct code, byte width). Only the types the GPS tags
# actually use are handled; anything else is skipped.
_TYPE_BYTE = 1
_TYPE_ASCII = 2
_TYPE_SHORT = 3
_TYPE_LONG = 4
_TYPE_RATIONAL = 5
_TYPE_WIDTH = {
    _TYPE_BYTE: 1,
    _TYPE_ASCII: 1,
    _TYPE_SHORT: 2,
    _TYPE_LONG: 4,
    _TYPE_RATIONAL: 8,
}


def _find_tiff_block(data: bytes) -> bytes | None:
    """Return the TIFF/EXIF block from ``data``.

    Handles two shapes:

    * A JPEG (starts ``FF D8``): scan the marker segments for APP1 (``FF E1``)
      carrying an ``Exif\\x00\\x00`` header and return the TIFF block that
      follows it.
    * A bare TIFF header (``II*\\x00`` or ``MM\\x00*``): return ``data`` itself.

    Returns ``None`` when no EXIF/TIFF block can be located.
    """
    if len(data) < 8:
        return None

    # Bare TIFF (some HEIC/TIFF exports hand us this directly).
    if data[:2] in (b"II", b"MM") and data[2:4] in (b"\x2a\x00", b"\x00\x2a"):
        return data

    # JPEG: walk the segment markers looking for APP1/Exif.
    if data[:2] != b"\xff\xd8":
        return None

    offset = 2
    n = len(data)
    while offset + 4 <= n:
        if data[offset] != 0xFF:
            # Not at a marker - corrupt/unknown structure, bail out.
            return None
        marker = data[offset + 1]
        # Standalone markers (RSTn, SOI, EOI) carry no length.
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        seg_len = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
        if seg_len < 2:
            return None
        seg_start = offset + 4
        seg_end = offset + 2 + seg_len
        if marker == 0xE1:  # APP1
            payload = data[seg_start:seg_end]
            if payload[:6] == b"Exif\x00\x00":
                return payload[6:]
        # Start-of-scan: image data follows, no more metadata segments.
        if marker == 0xDA:
            return None
        offset = seg_end
    return None


def _read_ifd_entries(tiff: bytes, ifd_offset: int, byte_order: str) -> dict[int, tuple[int, int, int]]:
    """Read one IFD and return ``{tag: (field_type, count, value_or_offset)}``.

    ``value_or_offset`` is the raw 4-byte value field interpreted as an
    unsigned long; the caller decides whether it is an inline value or an
    offset into ``tiff``.
    """
    entries: dict[int, tuple[int, int, int]] = {}
    if ifd_offset + 2 > len(tiff):
        return entries
    count = struct.unpack(byte_order + "H", tiff[ifd_offset : ifd_offset + 2])[0]
    pos = ifd_offset + 2
    for _ in range(count):
        if pos + 12 > len(tiff):
            break
        tag, field_type, num = struct.unpack(byte_order + "HHI", tiff[pos : pos + 8])
        value_field = struct.unpack(byte_order + "I", tiff[pos + 8 : pos + 12])[0]
        entries[tag] = (field_type, num, value_field)
        pos += 12
    return entries


def _value_bytes(tiff: bytes, field_type: int, count: int, value_field: int, byte_order: str) -> bytes:
    """Return the raw bytes for an IFD entry value (inline or via offset)."""
    width = _TYPE_WIDTH.get(field_type, 1)
    total = width * count
    if total <= 4:
        # Value is packed into the 4-byte value field itself.
        packed = struct.pack(byte_order + "I", value_field)
        return packed[:total]
    if value_field + total > len(tiff):
        return b""
    return tiff[value_field : value_field + total]


def _read_rationals(raw: bytes, count: int, byte_order: str) -> list[float]:
    """Decode ``count`` unsigned RATIONAL (num/den) values to floats."""
    out: list[float] = []
    for i in range(count):
        chunk = raw[i * 8 : i * 8 + 8]
        if len(chunk) < 8:
            break
        num, den = struct.unpack(byte_order + "II", chunk)
        out.append(num / den if den else 0.0)
    return out


def _dms_to_degrees(dms: list[float]) -> float | None:
    """Convert a [deg, min, sec] rational triple to decimal degrees."""
    if len(dms) < 3:
        return None
    deg, minutes, seconds = dms[0], dms[1], dms[2]
    return deg + minutes / 60.0 + seconds / 3600.0


def extract_exif_gps(image_bytes: bytes) -> tuple[float, float] | None:
    """Parse EXIF GPS tags from a JPEG/TIFF image and return ``(lat, lon)``.

    Returns ``None`` when the image carries no usable geotag (no EXIF block,
    no GPS IFD, missing/zero coordinates, or coordinates out of range). Never
    raises - any parse error degrades to ``None`` so a malformed upload can't
    break the upload flow.

    Coordinates are returned in signed decimal degrees (south/west negative),
    matching the ``ProjectPhoto.gps_lat`` / ``gps_lon`` columns.
    """
    try:
        tiff = _find_tiff_block(image_bytes)
        if tiff is None or len(tiff) < 8:
            return None

        if tiff[:2] == b"II":
            byte_order = "<"
        elif tiff[:2] == b"MM":
            byte_order = ">"
        else:
            return None

        ifd0_offset = struct.unpack(byte_order + "I", tiff[4:8])[0]
        ifd0 = _read_ifd_entries(tiff, ifd0_offset, byte_order)
        gps_ptr = ifd0.get(_GPS_IFD_TAG)
        if gps_ptr is None:
            return None

        gps_ifd = _read_ifd_entries(tiff, gps_ptr[2], byte_order)
        lat_entry = gps_ifd.get(_GPS_LAT)
        lon_entry = gps_ifd.get(_GPS_LON)
        if lat_entry is None or lon_entry is None:
            return None

        lat_raw = _value_bytes(tiff, lat_entry[0], lat_entry[1], lat_entry[2], byte_order)
        lon_raw = _value_bytes(tiff, lon_entry[0], lon_entry[1], lon_entry[2], byte_order)
        lat = _dms_to_degrees(_read_rationals(lat_raw, lat_entry[1], byte_order))
        lon = _dms_to_degrees(_read_rationals(lon_raw, lon_entry[1], byte_order))
        if lat is None or lon is None:
            return None

        # Apply hemisphere refs (ASCII single char 'N'/'S'/'E'/'W').
        lat_ref_entry = gps_ifd.get(_GPS_LAT_REF)
        lon_ref_entry = gps_ifd.get(_GPS_LON_REF)
        if lat_ref_entry is not None:
            ref = _value_bytes(tiff, lat_ref_entry[0], lat_ref_entry[1], lat_ref_entry[2], byte_order)
            if ref[:1].upper() == b"S":
                lat = -lat
        if lon_ref_entry is not None:
            ref = _value_bytes(tiff, lon_ref_entry[0], lon_ref_entry[1], lon_ref_entry[2], byte_order)
            if ref[:1].upper() == b"W":
                lon = -lon

        # Reject obviously-bogus coordinates and the 0,0 "null island" that a
        # camera writes when it has no fix - both would silently mis-place
        # the photo on the map.
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            return None
        if abs(lat) < 1e-9 and abs(lon) < 1e-9:
            return None

        return round(lat, 7), round(lon, 7)
    except Exception:
        logger.debug("EXIF GPS extraction failed", exc_info=True)
        return None


def _decode_exif_datetime(raw: bytes) -> datetime | None:
    """Decode an EXIF ASCII date string ``"YYYY:MM:DD HH:MM:SS"`` to ``datetime``.

    EXIF stores timestamps in local camera time with no timezone, so the
    returned ``datetime`` is naive (matching the naive-UTC convention the
    ``ProjectPhoto.taken_at`` column round-trips elsewhere). Returns ``None``
    for any unparseable / zero value rather than raising.
    """
    try:
        text = raw.split(b"\x00", 1)[0].decode("ascii", "ignore").strip()
    except Exception:
        return None
    if not text or text.startswith("0000"):
        return None
    try:
        return datetime.strptime(text, "%Y:%m:%d %H:%M:%S")  # noqa: DTZ007 - EXIF has no tz
    except ValueError:
        return None


def extract_exif_datetime(image_bytes: bytes) -> datetime | None:
    """Parse the EXIF capture timestamp from a JPEG/TIFF image.

    Prefers ``DateTimeOriginal`` (when the shutter fired, in the Exif
    sub-IFD); falls back to the IFD0 ``DateTime`` tag. Returns a naive
    ``datetime`` (EXIF carries no timezone) or ``None`` when no usable
    timestamp is present. Never raises - any parse error degrades to
    ``None`` so a malformed upload can't break the upload flow.
    """
    try:
        tiff = _find_tiff_block(image_bytes)
        if tiff is None or len(tiff) < 8:
            return None

        if tiff[:2] == b"II":
            byte_order = "<"
        elif tiff[:2] == b"MM":
            byte_order = ">"
        else:
            return None

        ifd0_offset = struct.unpack(byte_order + "I", tiff[4:8])[0]
        ifd0 = _read_ifd_entries(tiff, ifd0_offset, byte_order)

        # Preferred: DateTimeOriginal in the Exif sub-IFD.
        exif_ptr = ifd0.get(_EXIF_IFD_TAG)
        if exif_ptr is not None:
            exif_ifd = _read_ifd_entries(tiff, exif_ptr[2], byte_order)
            entry = exif_ifd.get(_DATETIME_ORIGINAL)
            if entry is not None:
                raw = _value_bytes(tiff, entry[0], entry[1], entry[2], byte_order)
                dt = _decode_exif_datetime(raw)
                if dt is not None:
                    return dt

        # Fallback: plain IFD0 DateTime.
        entry = ifd0.get(_DATETIME)
        if entry is not None:
            raw = _value_bytes(tiff, entry[0], entry[1], entry[2], byte_order)
            return _decode_exif_datetime(raw)

        return None
    except Exception:
        logger.debug("EXIF datetime extraction failed", exc_info=True)
        return None


def _description_from_tags(tags: list[Any]) -> str:
    """Stringify CV-extracted tags into a description blob."""
    if not tags:
        return ""
    return ", ".join(str(t).strip() for t in tags if str(t).strip())


def extract(raw: dict[str, Any]) -> ElementEnvelope:
    """Build an :class:`ElementEnvelope` from a photo-element dict.

    Pulls description from either ``description`` (direct) or
    ``ai_extracted_tags`` (rendered as ``"tag1, tag2, tag3"``).
    Quantities come from ``estimated_*`` keys exported by the CV
    confidence-scoring step.
    """
    description = str(raw.get("description") or "").strip()
    if not description:
        tags = raw.get("ai_extracted_tags") or raw.get("tags") or []
        if isinstance(tags, list):
            description = _description_from_tags(tags)

    category = str(raw.get("category") or raw.get("estimated_category") or "").strip()

    quantities: dict[str, float] = {}
    for src_key, dst_key in (
        ("estimated_area_m2", "area_m2"),
        ("estimated_length_m", "length_m"),
        ("estimated_volume_m3", "volume_m3"),
        ("estimated_quantity", "quantity"),
        ("estimated_count", "count"),
    ):
        value = raw.get(src_key)
        if value in (None, "", 0):
            continue
        try:
            quantities[dst_key] = float(value)
        except (TypeError, ValueError):
            continue

    properties: dict[str, Any] = {}
    confidence = raw.get("cv_confidence") or raw.get("confidence")
    if confidence is not None:
        properties["cv_confidence"] = confidence
    file_url = raw.get("file_url")
    if file_url:
        properties["file_url"] = file_url

    unit_hint = str(raw.get("estimated_unit") or raw.get("unit") or "").strip() or None

    return build_envelope_base(
        source="photo",
        raw=raw,
        description=description,
        category=category,
        source_lang=str(raw.get("language") or ""),
        properties=properties,
        quantities=quantities or None,
        unit_hint=unit_hint,
    )
