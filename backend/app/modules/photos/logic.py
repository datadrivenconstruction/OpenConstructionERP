# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure photo logic: capture precedence, distances, GeoJSON, timeline, AI parsing, export sidecars.

Nothing here touches the database or the disk, so every rule the archive relies on
can be tested in isolation.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

#: Records a photo can be linked to. Each kind resolves to a table of the same project.
LINK_TARGET_KINDS: tuple[str, ...] = (
    "boq_position",
    "schedule_activity",
    "location",
    "punch_item",
    "inspection",
    "diary",
    "field_report",
    "safety_obs",
)

#: Modules whose photos get an index row; ``documents`` owns its own file.
SOURCE_MODULES: tuple[str, ...] = ("documents", "daily_diary", "punchlist", "fieldreports", "progress")

#: Link kind a source module's owning record maps to, so an indexed photo shows on that record.
SOURCE_LINK_KIND: dict[str, str] = {
    "daily_diary": "diary",
    "punchlist": "punch_item",
    "fieldreports": "field_report",
}

AI_KINDS: tuple[str, ...] = ("caption", "tags", "progress", "hazard")
AI_STATUSES: tuple[str, ...] = ("pending", "accepted", "rejected", "edited")
THUMB_STATUSES: tuple[str, ...] = ("pending", "ready", "failed", "skipped")

#: A GPS fix with a worse radius than this, or farther than this from the site anchor, is flagged.
MAX_GPS_ACCURACY_M = 50.0
MAX_DISTANCE_FROM_SITE_M = 2000.0
#: An AI suggestion nobody looked at for this long is reported.
AI_REVIEW_DAYS = 7
#: Longest side sent to a vision model; enough to read a site photo, cheap to send.
AI_MAX_SIDE_PX = 1024
#: Tags a suggestion may carry, and their maximum length.
MAX_AI_TAGS = 8
MAX_TAG_LEN = 40


def _finite(value: Any) -> bool:
    if value is None or isinstance(value, bool | str | bytes):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def valid_lat_lon(lat: Any, lon: Any) -> bool:
    """Whether ``lat``/``lon`` is a usable WGS84 position (``0,0`` is the null island, not a site)."""
    if not (_finite(lat) and _finite(lon)):
        return False
    lat_f, lon_f = float(lat), float(lon)
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
        return False
    return not (lat_f == 0.0 and lon_f == 0.0)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    r = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def as_utc(value: datetime | None) -> datetime | None:
    """Treat a naive timestamp as UTC, so comparisons never mix aware and naive values."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 string (``Z`` allowed) or pass a datetime through."""
    if isinstance(value, datetime):
        return as_utc(value)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return as_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def resolve_capture(
    *,
    explicit_lat: float | None = None,
    explicit_lon: float | None = None,
    explicit_taken_at: datetime | None = None,
    device: dict[str, Any] | None = None,
    exif: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pick the effective position and capture time with their sources.

    Precedence: what the person typed, then the device fix taken in the app (it
    carries an accuracy radius), then the camera's EXIF block. A missing capture
    time stays missing: the upload time is not a capture time and is never
    substituted here.
    """
    device = device or {}
    exif = exif or {}
    out: dict[str, Any] = {
        "lat": None,
        "lon": None,
        "accuracy_m": None,
        "location_source": None,
        "taken_at": None,
        "taken_at_source": None,
    }
    if valid_lat_lon(explicit_lat, explicit_lon):
        out.update(lat=float(explicit_lat), lon=float(explicit_lon), location_source="manual")  # type: ignore[arg-type]
    elif valid_lat_lon(device.get("lat"), device.get("lon")):
        acc = device.get("accuracy_m")
        out.update(
            lat=float(device["lat"]),
            lon=float(device["lon"]),
            accuracy_m=float(acc) if _finite(acc) and float(acc) >= 0 else None,
            location_source="device",
        )
    elif valid_lat_lon(exif.get("lat"), exif.get("lon")):
        out.update(lat=float(exif["lat"]), lon=float(exif["lon"]), location_source="exif")

    if explicit_taken_at is not None:
        out.update(taken_at=as_utc(explicit_taken_at), taken_at_source="manual")
    elif parse_iso(device.get("captured_at")) is not None:
        out.update(taken_at=parse_iso(device.get("captured_at")), taken_at_source="device")
    elif parse_iso(exif.get("taken_at")) is not None:
        out.update(taken_at=parse_iso(exif.get("taken_at")), taken_at_source="exif")
    return out


def evidence_grade_for(record: dict[str, Any] | None) -> str:
    """Grade an evidence record, or ``none`` when the photo has none."""
    if not isinstance(record, dict):
        return "none"
    from app.core.photo_evidence import evidence_grade

    return evidence_grade(record)


# ── Map and timeline ────────────────────────────────────────────────────────


def to_geojson(photos: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """A GeoJSON FeatureCollection of the located photos (``[lon, lat]`` order, RFC 7946)."""
    features: list[dict[str, Any]] = []
    for p in photos:
        lat, lon = p.get("gps_lat"), p.get("gps_lon")
        if not valid_lat_lon(lat, lon):
            continue
        taken = p.get("taken_at")
        features.append(
            {
                "type": "Feature",
                "id": str(p.get("id")),
                "geometry": {"type": "Point", "coordinates": [round(float(lon), 7), round(float(lat), 7)]},
                "properties": {
                    "id": str(p.get("id")),
                    "caption": p.get("caption") or "",
                    "filename": p.get("filename") or "",
                    "taken_at": taken.isoformat() if isinstance(taken, datetime) else taken,
                    "source_module": p.get("source_module") or "documents",
                    "accuracy_m": p.get("gps_accuracy_m"),
                    "category": p.get("category") or "site",
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def group_timeline(photos: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group photos by capture day, newest day first, newest photo first inside a day.

    A photo without a capture time falls back to its upload time so it is never
    hidden; the bucket says so with ``undated`` counting those.
    """
    buckets: dict[str, dict[str, Any]] = {}
    for p in photos:
        moment = as_utc(p.get("taken_at"))
        undated = moment is None
        if moment is None:
            moment = as_utc(p.get("created_at"))
        key = moment.date().isoformat() if moment else "unknown"
        bucket = buckets.setdefault(key, {"date": key, "count": 0, "undated": 0, "photos": []})
        bucket["count"] += 1
        bucket["undated"] += 1 if undated else 0
        bucket["photos"].append((moment, p))
    out: list[dict[str, Any]] = []
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    for key in sorted(buckets, key=lambda k: (k != "unknown", k), reverse=True):
        bucket = buckets[key]
        ordered = sorted(bucket["photos"], key=lambda mp: (mp[0] or epoch, str(mp[1].get("id"))), reverse=True)
        bucket["photos"] = [p for _m, p in ordered]
        out.append(bucket)
    return out


# ── Cursor pagination ──────────────────────────────────────────────────────


def encode_cursor(sort_at: datetime, photo_id: str) -> str:
    """Opaque keyset cursor for ``ORDER BY sort_at DESC, id DESC``."""
    raw = json.dumps({"t": as_utc(sort_at).isoformat(), "i": photo_id}, separators=(",", ":"))  # type: ignore[union-attr]
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    """Decode :func:`encode_cursor`; a tampered or stale cursor reads as "from the start"."""
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        moment = parse_iso(data.get("t"))
        pid = str(data.get("i") or "")
    except (ValueError, binascii.Error, AttributeError, UnicodeDecodeError):
        return None
    if moment is None or not pid:
        return None
    return moment, pid


# ── AI suggestions ─────────────────────────────────────────────────────────


def clamp_confidence(value: Any) -> float | None:
    """A model's confidence as 0..1, or ``None`` when it is not a number."""
    if not _finite(value):
        return None
    v = float(value)
    if v > 1.0 and v <= 100.0:
        v = v / 100.0
    return max(0.0, min(1.0, v))


def _clean_tag(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    tag = " ".join(raw.strip().lower().split())[:MAX_TAG_LEN]
    return tag or None


def _clean_bbox(raw: Any) -> list[float] | None:
    if not isinstance(raw, list | tuple) or len(raw) != 4 or not all(_finite(v) for v in raw):
        return None
    x, y, w, h = (float(v) for v in raw)
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 < w <= 1.0 and 0.0 < h <= 1.0):
        return None
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]


def parse_ai_suggestions(
    parsed: Any,
    kinds: Iterable[str],
    *,
    allowed_targets: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    """Turn a model's JSON into suggestion rows, dropping anything malformed.

    Expected shape: ``{"caption": {"text", "confidence"}, "tags": {"tags": [...],
    "confidence"}, "progress": [{"target_kind", "target_id", "percent_observed",
    "confidence"}], "hazards": [{"hazard", "bbox", "confidence"}]}``. Every row
    needs a numeric confidence; a progress row needs a target the photo is
    already linked to, so the model can never point at a record it was not shown.
    """
    wanted = {k for k in kinds if k in AI_KINDS}
    if not isinstance(parsed, dict):
        return []
    allowed_targets = allowed_targets or {}
    out: list[dict[str, Any]] = []

    if "caption" in wanted and isinstance(parsed.get("caption"), dict):
        c = parsed["caption"]
        text = c.get("text")
        conf = clamp_confidence(c.get("confidence"))
        if isinstance(text, str) and text.strip() and conf is not None:
            out.append({"kind": "caption", "payload": {"text": text.strip()[:500]}, "confidence": conf})

    if "tags" in wanted and isinstance(parsed.get("tags"), dict):
        t = parsed["tags"]
        conf = clamp_confidence(t.get("confidence"))
        tags: list[str] = []
        for raw in t.get("tags") or []:
            tag = _clean_tag(raw)
            if tag and tag not in tags:
                tags.append(tag)
        if tags and conf is not None:
            out.append({"kind": "tags", "payload": {"tags": tags[:MAX_AI_TAGS]}, "confidence": conf})

    if "progress" in wanted and isinstance(parsed.get("progress"), list):
        for row in parsed["progress"]:
            if not isinstance(row, dict):
                continue
            kind, tid = row.get("target_kind"), str(row.get("target_id") or "")
            pct, conf = row.get("percent_observed"), clamp_confidence(row.get("confidence"))
            if kind not in allowed_targets or tid not in allowed_targets[kind]:
                continue
            if not _finite(pct) or not 0.0 <= float(pct) <= 100.0 or conf is None:
                continue
            out.append(
                {
                    "kind": "progress",
                    "payload": {"target_kind": kind, "target_id": tid, "percent_observed": round(float(pct), 1)},
                    "confidence": conf,
                }
            )

    if "hazard" in wanted and isinstance(parsed.get("hazards"), list):
        for row in parsed["hazards"]:
            if not isinstance(row, dict):
                continue
            hazard = row.get("hazard")
            conf = clamp_confidence(row.get("confidence"))
            if not isinstance(hazard, str) or not hazard.strip() or conf is None:
                continue
            out.append(
                {
                    "kind": "hazard",
                    "payload": {"hazard": hazard.strip()[:200], "bbox": _clean_bbox(row.get("bbox"))},
                    "confidence": conf,
                }
            )
    return out


def ai_prompt(kinds: Iterable[str], linked: dict[str, list[str]]) -> str:
    """The instruction sent with the image. Targets are listed so the model can only pick from them."""
    wanted = [k for k in kinds if k in AI_KINDS]
    parts = [
        "You are reviewing one construction-site photo for an estimator and a site manager.",
        "Reply with ONLY a JSON object. Give every item a confidence between 0 and 1.",
        "Never identify people. Describe work, materials, equipment and conditions only.",
    ]
    if "caption" in wanted:
        parts.append('"caption": {"text": "<one factual sentence>", "confidence": <0..1>}')
    if "tags" in wanted:
        parts.append('"tags": {"tags": ["<up to 8 short lower-case words>"], "confidence": <0..1>}')
    if "progress" in wanted and linked:
        listed = "; ".join(f"{kind}: {', '.join(ids)}" for kind, ids in linked.items() if ids)
        parts.append(
            '"progress": [{"target_kind": "<kind>", "target_id": "<id>", "percent_observed": <0..100>, '
            f'"confidence": <0..1>}}] using only these linked records: {listed}'
        )
    if "hazard" in wanted:
        parts.append(
            '"hazards": [{"hazard": "<short description>", "bbox": [x, y, w, h] as fractions of the image, '
            '"confidence": <0..1>}] for visible safety hazards only; an empty list when there are none'
        )
    return "\n".join(parts)


# ── Export ─────────────────────────────────────────────────────────────────


def sidecar(photo: dict[str, Any], links: list[dict[str, Any]], tags: list[str]) -> dict[str, Any]:
    """The ``photo-<id>.json`` record written next to each original in an export."""

    def _iso(value: Any) -> Any:
        return value.isoformat() if isinstance(value, datetime) else value

    return {
        "id": str(photo.get("id")),
        "project_id": str(photo.get("project_id")),
        "filename": photo.get("filename"),
        "caption": photo.get("caption"),
        "category": photo.get("category"),
        "taken_at": _iso(photo.get("taken_at")),
        "uploaded_at": _iso(photo.get("created_at")),
        "gps": (
            {"lat": photo.get("gps_lat"), "lon": photo.get("gps_lon"), "accuracy_m": photo.get("gps_accuracy_m")}
            if valid_lat_lon(photo.get("gps_lat"), photo.get("gps_lon"))
            else None
        ),
        "sha256": photo.get("sha256"),
        "width": photo.get("width"),
        "height": photo.get("height"),
        "source": {"module": photo.get("source_module") or "documents", "id": photo.get("source_id")},
        "zone": photo.get("zone"),
        "tags": sorted(set(tags)),
        "links": [{"kind": link["target_kind"], "id": link["target_id"]} for link in links],
        "evidence": (photo.get("metadata") or {}).get("evidence"),
    }


def archive_name(photo_id: str, filename: str | None) -> str:
    """Entry name of an original inside the export zip: unique, and never a path."""
    base = (filename or "photo.jpg").replace("\\", "/").rsplit("/", 1)[-1] or "photo.jpg"
    base = "".join(ch for ch in base if ch.isprintable() and ch not in ':*?"<>|')[:120] or "photo.jpg"
    return f"photos/{photo_id[:8]}_{base}"


# ── External photo extraction (backfill / event indexing) ─────────────────


def external_photo_entries(source_module: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    """The photo files one source record references, as index-row drafts.

    ``row`` is a plain dict of the source record. Punch items, field reports and
    progress entries keep a JSON list of storage paths; a diary photo is a row of
    its own with a URL. Blank and duplicate entries are dropped.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    if source_module == "daily_diary":
        path = str(row.get("file_url") or "").strip()
        if path:
            out.append(
                {
                    "file_path": path,
                    "source_id": str(row.get("id")),
                    "taken_at": as_utc(row.get("taken_at")),
                    "gps_lat": row.get("lat"),
                    "gps_lon": row.get("lng"),
                    "caption": row.get("description"),
                    "tags": [t for t in (row.get("tags") or []) if isinstance(t, str)],
                    "zone": row.get("location_label"),
                }
            )
        return out
    raw = row.get("photos") or []
    if not isinstance(raw, list):
        return out
    evidence = (
        ((row.get("metadata") or {}).get("photo_evidence") or {}) if isinstance(row.get("metadata"), dict) else {}
    )
    for entry in raw:
        path = entry.get("path") if isinstance(entry, dict) else entry
        if not isinstance(path, str) or not path.strip() or path in seen:
            continue
        seen.add(path)
        record = evidence.get(path) if isinstance(evidence, dict) else None
        location = (record or {}).get("location") or {}
        captured = parse_iso(((record or {}).get("captured_at") or {}).get("value"))
        out.append(
            {
                "file_path": path.strip(),
                "source_id": str(row.get("id")),
                "taken_at": captured or as_utc(row.get("recorded_at") or row.get("report_date")),
                "gps_lat": location.get("lat") if location else row.get("geo_lat"),
                "gps_lon": location.get("lon") if location else row.get("geo_lon"),
                "gps_accuracy_m": location.get("accuracy_m") if location else None,
                "caption": row.get("title"),
                "sha256": (record or {}).get("sha256"),
                "evidence": record,
                "tags": [],
                "zone": None,
            }
        )
    return out
