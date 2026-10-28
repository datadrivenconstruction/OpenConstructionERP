"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Punch photo evidence and the BCF round-trip (real PostgreSQL session)."""

from __future__ import annotations

import io
import uuid

from PIL import Image

from app.core.photo_evidence import DeviceCapture, build_evidence_record
from app.core.storage import module_uploads_dir
from app.modules.bcf import bcf_xml
from app.modules.punchlist.bcf_bridge import (
    evidence_comment_guid,
    export_punch_bcf,
    import_punch_bcf,
    photo_viewpoint_guid,
    status_from_bcf,
    status_to_bcf,
)
from app.modules.punchlist.models import PunchItem
from app.modules.punchlist.service import PHOTO_EVIDENCE_KEY, PunchListService
from app.modules.punchlist.validators import PunchClosurePhotoRule, PunchPhotoEvidenceRule


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (0, 120, 0)).save(buf, format="PNG")
    return buf.getvalue()


async def _item(session, project_id, **kw) -> PunchItem:
    item = PunchItem(
        project_id=project_id,
        title=kw.pop("title", "Cracked tile"),
        description="Lobby floor",
        priority=kw.pop("priority", "high"),
        status=kw.pop("status", "open"),
        photos=[],
        metadata_={},
        reopen_history=[],
        **kw,
    )
    session.add(item)
    await session.flush()
    return item


async def _add_photo(session, item: PunchItem) -> str:
    data = _png()
    name = f"{item.id}_{uuid.uuid4().hex[:6]}.png"
    folder = module_uploads_dir("punchlist", "photos")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    path = f"punchlist/photos/{name}"
    record = build_evidence_record(
        data, path=path, device=DeviceCapture(lat=52.5, lon=13.4, accuracy_m=5.0, heading_deg=90.0)
    )
    await PunchListService(session).add_photo(item.id, path, record)
    return path


async def test_add_photo_stores_evidence_and_pins_unpinned_item(session, project_id):
    item = await _item(session, project_id)
    path = await _add_photo(session, item)
    await session.refresh(item)
    assert item.photos == [path]
    record = item.metadata_[PHOTO_EVIDENCE_KEY][path]
    assert record["location"]["accuracy_m"] == 5.0
    assert (item.geo_lat, item.geo_lon) == (52.5, 13.4)
    assert item.metadata_["geo_source"] == "photo:device"


async def test_photo_never_moves_an_existing_pin_and_removal_drops_evidence(session, project_id):
    item = await _item(session, project_id, geo_lat=1.5, geo_lon=2.5)
    path = await _add_photo(session, item)
    await session.refresh(item)
    assert (item.geo_lat, item.geo_lon) == (1.5, 2.5)
    await PunchListService(session).remove_photo(item.id, 0)
    await session.refresh(item)
    assert item.photos == []
    assert path not in item.metadata_.get(PHOTO_EVIDENCE_KEY, {})


async def test_bcf_export_keeps_ids_and_carries_photos_and_evidence(session, project_id):
    item = await _item(session, project_id, status="resolved", category="finishing")
    path = await _add_photo(session, item)
    archive, count = await export_punch_bcf(session, project_id, version="3.0")
    assert count == 1
    parsed = bcf_xml.parse_bcfzip(archive)
    topic = parsed.topics[0]
    assert topic.guid == str(item.id)
    assert topic.topic_status == "Resolved"
    assert "punchlist" in topic.labels and "finishing" in topic.labels
    assert topic.viewpoints[0].guid == photo_viewpoint_guid(item.id, path)
    assert topic.viewpoints[0].snapshot_bytes
    assert any(c.guid == evidence_comment_guid(item.id, path) for c in topic.comments)


async def test_bcf_round_trip_is_idempotent(session, project_id):
    item = await _item(session, project_id)
    await _add_photo(session, item)
    archive, _ = await export_punch_bcf(session, project_id)
    report = await import_punch_bcf(session, project_id, archive, user_id=None)
    assert report.status in ("passed", "warnings"), report.issues
    assert not [i for i in report.issues if i["code"] == "status_needs_signoff"]
    assert (report.created, report.updated, report.photos_added, report.comments_added) == (0, 1, 0, 0)
    await session.refresh(item)
    assert len(item.photos) == 1


async def test_bcf_import_updates_status_but_not_signoff_states(session, project_id):
    item = await _item(session, project_id, status="in_progress")
    topic = bcf_xml.ParsedTopic(
        guid=str(item.id), title="Cracked tile (fixed)", topic_status="Resolved", priority="Critical"
    )
    archive = bcf_xml.build_bcfzip(version="2.1", project_id=str(project_id), project_name="P", topics=[topic])
    report = await import_punch_bcf(session, project_id, archive, user_id=None)
    await session.refresh(item)
    assert item.status == "resolved" and item.resolved_at is not None
    assert item.priority == "critical" and item.title == "Cracked tile (fixed)"

    topic.topic_status = "Closed"
    archive = bcf_xml.build_bcfzip(version="2.1", project_id=str(project_id), project_name="P", topics=[topic])
    report = await import_punch_bcf(session, project_id, archive, user_id=None)
    await session.refresh(item)
    assert item.status == "resolved"
    assert report.status == "warnings"
    assert "status_needs_signoff" in {i["code"] for i in report.issues}


async def test_bcf_import_creates_items_with_the_topic_guid_and_snapshot_photo(session, project_id):
    guid = str(uuid.uuid4())
    vp = bcf_xml.ParsedViewpoint(guid=str(uuid.uuid4()), snapshot_filename="snapshot.png", snapshot_bytes=_png())
    comment = bcf_xml.ParsedComment(guid=str(uuid.uuid4()), comment="Seen on walk-through", author="site")
    topic = bcf_xml.ParsedTopic(
        guid=guid, title="Loose handrail", labels=["punchlist"], viewpoints=[vp], comments=[comment]
    )
    archive = bcf_xml.build_bcfzip(version="2.1", project_id=str(project_id), project_name="P", topics=[topic])
    report = await import_punch_bcf(session, project_id, archive, user_id="u1")
    assert report.created == 1 and report.photos_added == 1 and report.comments_added == 1
    item = await session.get(PunchItem, uuid.UUID(guid))
    assert item is not None and item.project_id == project_id
    assert item.metadata_[PHOTO_EVIDENCE_KEY][item.photos[0]]["imported_from"] == "bcf"
    # A second import of the same archive adds nothing.
    again = await import_punch_bcf(session, project_id, archive, user_id="u1")
    assert (again.created, again.photos_added, again.comments_added) == (0, 0, 0)


async def test_bcf_import_of_another_projects_item_creates_a_new_one(session, project_id):
    other = await _item(session, uuid.uuid4())
    topic = bcf_xml.ParsedTopic(guid=str(other.id), title="Copied issue")
    archive = bcf_xml.build_bcfzip(version="2.1", project_id=str(project_id), project_name="P", topics=[topic])
    report = await import_punch_bcf(session, project_id, archive, user_id=None)
    assert report.created == 1
    assert report.item_ids[0] != str(other.id)
    assert {i["code"] for i in report.issues} >= {"foreign_item"}


async def test_bad_archive_reports_errors():
    report = await import_punch_bcf(None, uuid.uuid4(), b"not a zip", user_id=None)  # type: ignore[arg-type]
    assert report.status == "errors"


def test_status_mapping_round_trips():
    for status in ("open", "assigned", "in_progress", "resolved", "verified", "closed"):
        assert status_from_bcf(status_to_bcf(status)) == status
    assert status_from_bcf("Active") == "in_progress"
    assert status_from_bcf("whatever") is None


async def test_validation_rules_flag_closed_items_without_or_with_weak_photos():
    from app.core.validation.engine import ValidationContext

    data = {
        "items": [
            {"id": "a", "title": "A", "status": "closed", "photos": []},
            {"id": "b", "title": "B", "status": "verified", "photos": ["p"], "photo_evidence": [None]},
            {"id": "c", "title": "C", "status": "resolved", "photos": ["p"], "photo_evidence": [{"grade": "full"}]},
            {"id": "d", "title": "D", "status": "open", "photos": []},
        ]
    }
    ctx = ValidationContext(data=data)
    closure = await PunchClosurePhotoRule().validate(ctx)
    assert [(r.element_ref, r.passed) for r in closure] == [("a", False), ("b", True), ("c", True)]
    evidence = await PunchPhotoEvidenceRule().validate(ctx)
    assert [(r.element_ref, r.passed) for r in evidence] == [("b", False), ("c", True)]
