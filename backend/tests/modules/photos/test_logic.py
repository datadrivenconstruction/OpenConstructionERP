"""Pure photo logic: EXIF capture, precedence, GPS privacy, GeoJSON, timeline, AI parsing, export, thumbnails.

None of these touch the database, so they run with ``--noconftest`` as well.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.photos import logic


def _jpeg(
    *, gps: tuple[float, float] | None = None, taken: str | None = None, size: tuple[int, int] = (64, 48)
) -> bytes:
    from PIL import Image

    img = Image.new("RGB", size, (120, 90, 60))
    exif = Image.Exif()
    if taken:
        exif.get_ifd(0x8769)[36867] = taken
    if gps:
        lat, lon = gps

        def dms(v: float) -> tuple[float, float, float]:
            v = abs(v)
            d = int(v)
            m = int((v - d) * 60)
            s = round(((v - d) * 60 - m) * 60, 4)
            return (float(d), float(m), float(s))

        exif.get_ifd(0x8825).update(
            {1: "N" if lat >= 0 else "S", 2: dms(lat), 3: "E" if lon >= 0 else "W", 4: dms(lon)}
        )
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


# ── EXIF and precedence ─────────────────────────────────────────────────


def test_exif_date_and_gps_are_read_from_a_camera_file() -> None:
    from app.core.match_service.extractors.photo import extract_exif_datetime, extract_exif_gps

    content = _jpeg(gps=(52.52, 13.405), taken="2026:10:30 08:15:00")
    lat, lon = extract_exif_gps(content)
    assert lat == pytest.approx(52.52, abs=1e-4)
    assert lon == pytest.approx(13.405, abs=1e-4)
    taken = extract_exif_datetime(content)
    assert taken is not None
    assert (taken.year, taken.month, taken.day, taken.hour, taken.minute) == (2026, 10, 30, 8, 15)


def test_typed_values_beat_device_and_device_beats_exif() -> None:
    exif = {"lat": 48.1, "lon": 11.5, "taken_at": "2026-10-01T07:00:00+00:00"}
    device = {"lat": 52.5, "lon": 13.4, "accuracy_m": 8.0, "captured_at": "2026-10-02T09:00:00Z"}

    only_exif = logic.resolve_capture(exif=exif)
    assert (only_exif["lat"], only_exif["location_source"], only_exif["taken_at_source"]) == (48.1, "exif", "exif")

    with_device = logic.resolve_capture(device=device, exif=exif)
    assert with_device["location_source"] == "device"
    assert with_device["accuracy_m"] == 8.0
    assert with_device["taken_at"] == datetime(2026, 10, 2, 9, 0, tzinfo=UTC)

    typed = logic.resolve_capture(
        explicit_lat=40.0, explicit_lon=-3.7, explicit_taken_at=datetime(2026, 9, 1, 12, 0), device=device, exif=exif
    )
    assert typed["location_source"] == "manual"
    assert typed["taken_at"].tzinfo is not None
    assert typed["taken_at_source"] == "manual"


def test_no_capture_time_is_never_invented() -> None:
    result = logic.resolve_capture(device={"lat": 0.0, "lon": 0.0})
    assert result["taken_at"] is None
    assert result["location_source"] is None  # 0,0 is not a site


def test_gps_is_stripped_from_the_stored_file_unless_the_deployer_keeps_it(monkeypatch) -> None:
    from app.core.match_service.extractors.photo import extract_exif_gps
    from app.core.photo_evidence import prepare_stored_photo
    from app.modules.documents.service import _keep_photo_gps

    content = _jpeg(gps=(52.52, 13.405))
    monkeypatch.delenv("OE_PHOTO_KEEP_EXIF_GPS", raising=False)
    assert _keep_photo_gps() is False
    stored, exif, original_hash = prepare_stored_photo(content)
    assert extract_exif_gps(stored) is None
    assert exif["lat"] == pytest.approx(52.52, abs=1e-4)
    assert original_hash is not None

    monkeypatch.setenv("OE_PHOTO_KEEP_EXIF_GPS", "true")
    assert _keep_photo_gps() is True
    kept, _exif, kept_hash = prepare_stored_photo(content)
    assert kept == content
    assert kept_hash is None


# ── Map and timeline ────────────────────────────────────────────────────


def test_geojson_is_valid_rfc7946_and_skips_unlocated_photos() -> None:
    photos = [
        {"id": "a", "gps_lat": 52.5, "gps_lon": 13.4, "taken_at": datetime(2026, 10, 1, tzinfo=UTC)},
        {"id": "b", "gps_lat": None, "gps_lon": None},
        {"id": "c", "gps_lat": 0.0, "gps_lon": 0.0},
        {"id": "d", "gps_lat": 95.0, "gps_lon": 13.4},
    ]
    fc = logic.to_geojson(photos)
    assert fc["type"] == "FeatureCollection"
    assert [f["id"] for f in fc["features"]] == ["a"]
    feature = fc["features"][0]
    assert feature["geometry"] == {"type": "Point", "coordinates": [13.4, 52.5]}
    assert feature["properties"]["taken_at"] == "2026-10-01T00:00:00+00:00"
    json.dumps(fc)  # serialisable as is


def test_timeline_groups_newest_day_first_and_keeps_undated_photos() -> None:
    d = datetime(2026, 10, 3, 9, tzinfo=UTC)
    photos = [
        {"id": "1", "taken_at": d - timedelta(days=2)},
        {"id": "2", "taken_at": d},
        {"id": "3", "taken_at": d + timedelta(hours=5)},
        {"id": "4", "taken_at": None, "created_at": d - timedelta(days=1)},
    ]
    days = logic.group_timeline(photos)
    assert [day["date"] for day in days] == ["2026-10-03", "2026-10-02", "2026-10-01"]
    assert [p["id"] for p in days[0]["photos"]] == ["3", "2"]
    assert days[1]["undated"] == 1


def test_cursor_round_trips_and_a_tampered_cursor_restarts() -> None:
    moment = datetime(2026, 10, 3, 9, tzinfo=UTC)
    cursor = logic.encode_cursor(moment, "abc")
    assert logic.decode_cursor(cursor) == (moment, "abc")
    assert logic.decode_cursor("not-base64!!") is None
    assert logic.decode_cursor(None) is None


# ── AI parsing ──────────────────────────────────────────────────────────


def test_ai_answer_is_cleaned_row_by_row() -> None:
    parsed = {
        "caption": {"text": "  Rebar placed in slab bay 3 ", "confidence": 0.82},
        "tags": {"tags": ["Rebar", "rebar", "  slab  ", 5], "confidence": 0.7},
        "progress": [
            {"target_kind": "boq_position", "target_id": "p1", "percent_observed": 60, "confidence": 0.5},
            {"target_kind": "boq_position", "target_id": "foreign", "percent_observed": 60, "confidence": 0.9},
            {"target_kind": "boq_position", "target_id": "p1", "percent_observed": 160, "confidence": 0.9},
        ],
        "hazards": [{"hazard": "Open edge without guardrail", "bbox": [0.1, 0.2, 0.3, 0.4], "confidence": 74}],
    }
    rows = logic.parse_ai_suggestions(parsed, logic.AI_KINDS, allowed_targets={"boq_position": {"p1"}})
    by_kind = {r["kind"]: r for r in rows}
    assert by_kind["caption"]["payload"] == {"text": "Rebar placed in slab bay 3"}
    assert by_kind["tags"]["payload"] == {"tags": ["rebar", "slab"]}
    assert [r for r in rows if r["kind"] == "progress"] == [
        {
            "kind": "progress",
            "payload": {"target_kind": "boq_position", "target_id": "p1", "percent_observed": 60.0},
            "confidence": 0.5,
        }
    ]
    assert by_kind["hazard"]["confidence"] == pytest.approx(0.74)


@pytest.mark.parametrize(
    "parsed",
    [None, "free text", [], {"caption": {"text": "x"}}, {"caption": {"text": "", "confidence": 0.9}}, {"tags": []}],
)
def test_bad_ai_json_yields_no_suggestion(parsed) -> None:
    assert logic.parse_ai_suggestions(parsed, logic.AI_KINDS) == []


def test_prompt_lists_only_linked_targets_and_forbids_identifying_people() -> None:
    prompt = logic.ai_prompt(["progress", "hazard"], {"boq_position": ["p1"]})
    assert "boq_position: p1" in prompt
    assert "Never identify people" in prompt


# ── Export and extraction ───────────────────────────────────────────────


def test_sidecar_carries_provenance_and_archive_names_stay_inside_the_zip() -> None:
    record = logic.sidecar(
        {
            "id": "1234abcd-0000",
            "project_id": "p",
            "filename": "IMG_1.jpg",
            "gps_lat": 52.5,
            "gps_lon": 13.4,
            "source_module": "punchlist",
            "source_id": "item-1",
            "metadata": {"evidence": {"grade": "full"}},
        },
        [{"target_kind": "punch_item", "target_id": "item-1"}],
        ["b", "a", "a"],
    )
    assert record["source"] == {"module": "punchlist", "id": "item-1"}
    assert record["tags"] == ["a", "b"]
    assert record["links"] == [{"kind": "punch_item", "id": "item-1"}]
    assert record["evidence"] == {"grade": "full"}
    assert logic.archive_name("1234abcd-0000", "../../etc/passwd") == "photos/1234abcd_passwd"


def test_external_entries_from_a_punch_item_keep_evidence_and_drop_duplicates() -> None:
    row = {
        "id": "item-1",
        "title": "Crack in wall",
        "photos": ["punchlist/photos/a.jpg", "punchlist/photos/a.jpg", "", None, {"path": "punchlist/photos/b.jpg"}],
        "metadata": {
            "photo_evidence": {
                "punchlist/photos/a.jpg": {
                    "sha256": "ff",
                    "location": {"lat": 52.5, "lon": 13.4, "accuracy_m": 6.0},
                    "captured_at": {"value": "2026-10-01T10:00:00+00:00"},
                }
            }
        },
    }
    entries = logic.external_photo_entries("punchlist", row)
    assert [e["file_path"] for e in entries] == ["punchlist/photos/a.jpg", "punchlist/photos/b.jpg"]
    assert entries[0]["sha256"] == "ff"
    assert entries[0]["gps_accuracy_m"] == 6.0
    assert entries[0]["taken_at"] == datetime(2026, 10, 1, 10, tzinfo=UTC)


def test_diary_photo_maps_its_own_columns() -> None:
    row = {"id": "d1", "file_url": "daily_diary/x.jpg", "lat": 1.5, "lng": 2.5, "description": "Pour", "tags": ["a"]}
    (entry,) = logic.external_photo_entries("daily_diary", row)
    assert (entry["gps_lat"], entry["gps_lon"], entry["caption"]) == (1.5, 2.5, "Pour")


# ── Thumbnail job and export zip, against fakes ─────────────────────────


class _FakeSession:
    def __init__(self, photo):
        self.photo = photo

    async def get(self, _model, _id):
        return self.photo

    async def flush(self):
        return None


def _photo(tmp_path: Path, content: bytes, **extra) -> SimpleNamespace:
    import uuid

    photo_id = uuid.uuid4()
    path = tmp_path / f"{photo_id.hex}.jpg"
    path.write_bytes(content)
    base = {
        "id": photo_id,
        "project_id": uuid.uuid4(),
        "filename": "p.jpg",
        "file_path": str(path),
        "thumbnail_path": None,
        "thumb_status": "pending",
        "width": None,
        "height": None,
        "sha256": None,
        "caption": None,
        "category": "site",
        "tags": [],
        "taken_at": None,
        "created_at": datetime(2026, 10, 1, tzinfo=UTC),
        "gps_lat": None,
        "gps_lon": None,
        "gps_accuracy_m": None,
        "source_module": "documents",
        "source_id": None,
        "zone": None,
        "metadata_": {},
    }
    base.update(extra)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_thumbnail_job_marks_ready_and_records_size(tmp_path, monkeypatch) -> None:
    import app.modules.documents.service as docs
    from app.modules.photos import jobs

    photo = _photo(tmp_path, _jpeg(size=(800, 600)))
    monkeypatch.setattr(docs, "PHOTO_THUMB_BASE", tmp_path / "thumbs")
    monkeypatch.setattr(jobs, "resolve_photo_file", lambda p: Path(p.file_path))
    assert await jobs.make_thumbnail(_FakeSession(photo), photo.id) == "ready"
    assert Path(photo.thumbnail_path).is_file()
    assert (photo.width, photo.height) == (800, 600)
    assert photo.sha256


@pytest.mark.asyncio
async def test_thumbnail_job_refuses_an_image_over_the_pixel_cap(tmp_path, monkeypatch) -> None:
    import app.modules.documents.service as docs
    from app.modules.photos import jobs

    photo = _photo(tmp_path, _jpeg(size=(400, 400)))
    monkeypatch.setattr(docs, "MAX_PHOTO_PIXELS", 100 * 100)
    monkeypatch.setattr(docs, "PHOTO_THUMB_BASE", tmp_path / "thumbs")
    monkeypatch.setattr(jobs, "resolve_photo_file", lambda p: Path(p.file_path))
    assert await jobs.make_thumbnail(_FakeSession(photo), photo.id) == "failed"
    assert photo.thumb_status == "failed"
    assert photo.thumbnail_path is None


@pytest.mark.asyncio
async def test_thumbnail_job_marks_a_missing_file_failed(tmp_path, monkeypatch) -> None:
    from app.modules.photos import jobs

    photo = _photo(tmp_path, b"x")
    monkeypatch.setattr(jobs, "resolve_photo_file", lambda p: None)
    assert await jobs.make_thumbnail(_FakeSession(photo), photo.id) == "failed"


@pytest.mark.asyncio
async def test_export_zip_holds_originals_sidecars_and_manifest(tmp_path, monkeypatch) -> None:
    import app.modules.file_tags.service as file_tags
    from app.modules.photos import service as svc

    content = _jpeg()
    present = _photo(tmp_path, content, caption="Slab pour", gps_lat=52.5, gps_lon=13.4)
    gone = _photo(tmp_path, b"", filename="gone.jpg")
    monkeypatch.setattr(svc, "resolve_photo_file", lambda p: Path(p.file_path) if p is present else None)

    async def _no_tags(*_a, **_k):
        return {}

    monkeypatch.setattr(file_tags, "tags_by_files", _no_tags)
    service = svc.PhotosService(_FakeSession(None))

    async def _links(ids):
        return {i: [] for i in ids}

    monkeypatch.setattr(service.repo, "links_for", _links)
    dest = tmp_path / "out.zip"
    summary = await service.build_export_zip(present.project_id, [present, gone], dest)
    assert summary["photo_count"] == 2
    assert summary["missing_files"] == 1
    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
        record = json.loads(zf.read(f"photo-{present.id}.json"))
        original = zf.read(record["file"])
    assert f"photo-{gone.id}.json" in names
    assert original == content
    assert record["caption"] == "Slab pour"
    assert record["gps"]["lat"] == 52.5
    assert manifest["missing_files"] == [str(gone.id)]
