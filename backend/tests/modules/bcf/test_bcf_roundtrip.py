# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Writer ↔ Reader round-trip fidelity tests.

Sanity guarantee: every BCF 3.0 archive produced by our
:class:`BCFWriter` must be readable by :class:`BCFReader` with no field
loss. These tests are the safety net for the round-trip workflow with
Revit / ArchiCAD plugins — if a field round-trips here, it will survive
a real plugin too.

Cases:
    1. all 6 required Topic fields round-trip byte-for-byte
    2. comments — count + order + author + date all preserved
    3. viewpoints — camera coordinates preserve 6 decimals
    4. snapshot.png — byte-for-byte preservation
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.bcf.reader import BCFReader
from app.modules.bcf.writer import (
    BCFComment,
    BCFTopic,
    BCFViewpoint,
    BCFWriter,
)

# A pre-baked 1×1 PNG so the snapshot round-trip is exact.
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x78\x9c\x62\x00\x01\x00\x00\x05\x00\x01"
    b"\x0d\x0a\x2d\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _ts(year: int = 2026) -> datetime:
    """Deterministic UTC timestamp for round-trip stability."""
    return datetime(year, 5, 21, 10, 0, 0, tzinfo=UTC)


def test_roundtrip_required_topic_fields_preserved() -> None:
    """All six required Topic fields survive a writer→reader trip."""
    guid = uuid.uuid4().hex.replace("-", "")
    # Use a proper UUID — writer.py's _safe_dir requires hex/UUID shape.
    # Convert to canonical UUID-with-dashes form.
    guid = str(uuid.uuid4())

    topics = [
        BCFTopic(
            guid=guid,
            topic_type="Clash",
            topic_status="Open",
            title="Wall-1 × Pipe-1 (hard)",
            creation_date=_ts(),
            creation_author="alice@example.com",
            priority="Critical",
            description="A penetration of 0.05 m through wall.",
            assigned_to="bob@example.com",
            stage="Construction",
            server_assigned_id="CLASH-042",
            labels=["hard", "MEP-vs-STR"],
        )
        for _ in range(3)
    ]
    # Distinct guids per topic — writer rejects duplicates.
    for i, t in enumerate(topics):
        t.guid = str(uuid.uuid4())
        t.title = f"Topic #{i + 1}"
        t.server_assigned_id = f"CLASH-{i + 1:03d}"

    writer = BCFWriter().set_project("proj-1", "Round-trip Test")
    for t in topics:
        writer.add_topic(t)
    blob = writer.build_bytes()

    parsed = BCFReader.from_bytes(blob)
    assert parsed.version == "3.0"
    assert len(parsed.topics) == 3

    # Build a map by server_assigned_id for stable lookup.
    by_sid = {t.server_assigned_id: t for t in parsed.topics}
    for i, source in enumerate(topics):
        target = by_sid[source.server_assigned_id]
        # The 6 required fields.
        assert target.guid == source.guid.strip("{}").lower()
        assert target.topic_type == source.topic_type
        assert target.topic_status == source.topic_status
        assert target.title == source.title
        # CreationDate: ISO 8601 UTC round-trip — equality at second granularity.
        assert target.creation_date.utcoffset().total_seconds() == 0
        assert target.creation_date == source.creation_date
        assert target.creation_author == source.creation_author
        # Optionals that we set on every topic.
        assert target.priority == source.priority
        assert target.description == source.description
        assert target.server_assigned_id == source.server_assigned_id


def test_roundtrip_comments_preserve_count_order_author_date() -> None:
    """Comments preserve insertion order + per-field content."""
    guid = str(uuid.uuid4())
    base_dt = _ts()
    comments = [
        BCFComment(
            guid=str(uuid.uuid4()),
            date=base_dt + timedelta(minutes=i),
            author=f"user{i}@example.com",
            comment=f"Comment number {i}",
        )
        for i in range(7)
    ]
    topic = BCFTopic(
        guid=guid,
        topic_type="Clash",
        topic_status="Open",
        title="Comment round-trip",
        creation_date=base_dt,
        creation_author="alice@example.com",
        comments=comments,
    )
    blob = BCFWriter().set_project("p", "Comment RT").add_topic(topic).build_bytes()

    parsed = BCFReader.from_bytes(blob)
    assert len(parsed.topics) == 1
    target = parsed.topics[0]
    assert len(target.comments) == 7

    for i, (src, dst) in enumerate(zip(comments, target.comments, strict=True)):
        assert dst.guid == src.guid.strip("{}").lower(), f"comment {i} guid"
        assert dst.author == src.author, f"comment {i} author"
        assert dst.comment == src.comment, f"comment {i} text"
        # Dates: writer always serialises as UTC Z so the offset is 0.
        assert dst.date == src.date, f"comment {i} date"


def test_roundtrip_viewpoint_camera_preserves_6_decimals() -> None:
    """Camera coordinates survive the writer→reader trip to ≥6 decimals."""
    guid = str(uuid.uuid4())
    vguid = str(uuid.uuid4())
    # Six-decimal coords — round-trip should be exact (writer uses repr()).
    view_point = (1.234567, -2.345678, 3.456789)
    direction = (0.111111, 0.222222, -0.333333)
    up = (0.0, 0.0, 1.0)
    vp = BCFViewpoint(
        guid=vguid,
        camera_type="perspective",
        camera_view_point=view_point,
        camera_direction=direction,
        camera_up_vector=up,
        field_of_view=72.345,
        aspect_ratio=1.777778,
    )
    topic = BCFTopic(
        guid=guid,
        topic_type="Clash",
        topic_status="Open",
        title="Camera RT",
        creation_date=_ts(),
        creation_author="alice@example.com",
        viewpoints=[vp],
    )
    blob = BCFWriter().add_topic(topic).build_bytes()
    parsed = BCFReader.from_bytes(blob)
    target_vp = parsed.topics[0].viewpoints[0]
    assert target_vp.camera_type == "perspective"
    for src, dst in zip(view_point, target_vp.camera_view_point, strict=True):
        assert round(dst, 6) == round(src, 6)
    for src, dst in zip(direction, target_vp.camera_direction, strict=True):
        assert round(dst, 6) == round(src, 6)
    assert round(target_vp.field_of_view or 0.0, 6) == round(72.345, 6)
    assert round(target_vp.aspect_ratio or 0.0, 6) == round(1.777778, 6)


def test_roundtrip_snapshot_png_byte_for_byte() -> None:
    """A PNG attached to a viewpoint round-trips exactly."""
    guid = str(uuid.uuid4())
    vguid = str(uuid.uuid4())
    vp = BCFViewpoint(
        guid=vguid,
        camera_type="perspective",
        snapshot_png=_PNG_BYTES,
    )
    topic = BCFTopic(
        guid=guid,
        topic_type="Clash",
        topic_status="Open",
        title="PNG RT",
        creation_date=_ts(),
        creation_author="alice@example.com",
        viewpoints=[vp],
    )
    blob = BCFWriter().add_topic(topic).build_bytes()
    parsed = BCFReader.from_bytes(blob)
    target = parsed.topics[0]
    assert "snapshot.png" in target.snapshots
    assert target.snapshots["snapshot.png"] == _PNG_BYTES


def test_roundtrip_visibility_components_inverted_correctly() -> None:
    """The writer's "shorter-list" visibility encoding inverts cleanly.

    writer.py picks whichever of ``visible`` / ``hidden`` is shorter and
    flips ``DefaultVisibility`` to match. The reader must invert this
    back: the same input list comes out the same side it went in.
    """
    guid = str(uuid.uuid4())
    vguid = str(uuid.uuid4())
    # Lots more hidden than visible → writer emits visible as the
    # exceptions block with DefaultVisibility=false.
    visible_ids = ["VIS_A", "VIS_B"]
    hidden_ids = [f"HID_{i:03d}" for i in range(50)]
    vp = BCFViewpoint(
        guid=vguid,
        camera_type="perspective",
        visible=visible_ids,
        hidden=hidden_ids,
    )
    topic = BCFTopic(
        guid=guid,
        topic_type="Clash",
        topic_status="Open",
        title="Visibility RT",
        creation_date=_ts(),
        creation_author="alice@example.com",
        viewpoints=[vp],
    )
    blob = BCFWriter().add_topic(topic).build_bytes()
    parsed = BCFReader.from_bytes(blob)
    target_vp = parsed.topics[0].viewpoints[0]
    # The writer emits whichever side is shorter; reader recovers that side.
    # Since visible (2) is shorter than hidden (50), the writer emits
    # visible as exceptions w/ DefaultVisibility=false. Reader sees
    # default_visibility=False + visible list populated.
    assert target_vp.default_visibility is False
    assert set(target_vp.visible) == set(visible_ids)
    assert target_vp.hidden == ()
