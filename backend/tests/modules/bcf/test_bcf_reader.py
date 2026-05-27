# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Unit tests for :class:`app.modules.bcf.reader.BCFReader`.

The reader is pure-Python / stdlib (defusedxml + zipfile + xml.etree)
so the tests build .bcfzip archives in-memory — no database, no async
session, no FastAPI fixtures. Each test builds the smallest archive
that exercises its scenario.

Coverage matrix (matches the 18 cases called out in the task brief):

1.  minimal valid 1-topic 0-comments zip
2.  5-topic + 10-comment + 1-viewpoint each zip
3.  visibility decoding when DefaultVisibility=true + Exceptions list (hidden)
4.  visibility decoding when DefaultVisibility=false + Exceptions list (visible)
5.  ISO 8601 ``Z`` suffix parses
6.  ISO 8601 ``+02:00`` offset parses
7.  ISO 8601 naive (no tz) parses (assumed UTC)
8.  malformed XML inside one topic doesn't crash the file
9.  path-traversal raises BCFSecurityError
10. >100 MB uncompressed → BCFSecurityError
11. snapshot.png bytes attached when present
12. ServerAssignedId parsed onto ParsedTopic
13. comments inherit topic guid as parent
14. multiple viewpoints per topic preserved in order
15. missing required Title surfaces as parse_error
16. empty zip (only bcf.version) returns version + empty topics
17. unicode in Title / Description / Author preserved
18. ClippingPlanes list parsed
19. OrthogonalCamera + PerspectiveCamera both supported (combined)
"""

from __future__ import annotations

import io
import struct
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

import pytest

from app.modules.bcf.reader import (
    BCFFormatError,
    BCFReader,
    BCFSecurityError,
    ParsedTopic,
)

# ── tiny fixture helpers (no I/O, just byte composition) ──────────────────


def _minimal_png() -> bytes:
    """A 1×1 transparent PNG. The smallest legal PNG file possible.

    We compose the bytes by hand so the test has no Pillow dependency.
    """
    # PNG signature + IHDR + IDAT + IEND for a 1x1 truecolor with alpha.
    header = b"\x89PNG\r\n\x1a\n"
    # IHDR
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    ihdr_chunk = (
        struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + struct.pack(">I", 0xA8A1AE0A)  # precomputed CRC
    )
    # IDAT (deflate of one zero-byte scanline filter + 4 RGBA bytes)
    import zlib

    raw = b"\x00\x00\x00\x00\x00"  # filter=0, then RGBA=0x00000000
    idat_payload = zlib.compress(raw)
    idat_chunk = (
        struct.pack(">I", len(idat_payload))
        + b"IDAT"
        + idat_payload
        + struct.pack(">I", zlib.crc32(b"IDAT" + idat_payload))
    )
    # IEND
    iend_chunk = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", 0xAE426082)
    return header + ihdr_chunk + idat_chunk + iend_chunk


def _make_zip(entries: Iterable[tuple[str, bytes]]) -> bytes:
    """Build a zip in memory from (name, bytes) pairs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries:
            zf.writestr(name, payload)
    return buf.getvalue()


def _version_xml(v: str = "3.0") -> bytes:
    return f'<?xml version="1.0" encoding="utf-8"?><Version VersionId="{v}"/>'.encode()


def _markup_xml(
    *,
    guid: str,
    title: str = "Topic title",
    creation_date: str = "2026-05-21T10:00:00Z",
    creation_author: str = "alice@example.com",
    topic_type: str = "Clash",
    topic_status: str = "Open",
    server_assigned_id: str | None = None,
    priority: str | None = None,
    description: str | None = None,
    labels: list[str] | None = None,
    comments: list[dict] | None = None,
    viewpoints: list[dict] | None = None,
) -> bytes:
    """Compose a markup.bcf body matching the BCF 3.0 markup.xsd surface."""
    attrs = f'Guid="{guid}" TopicType="{topic_type}" TopicStatus="{topic_status}"'
    if server_assigned_id is not None:
        attrs += f' ServerAssignedId="{server_assigned_id}"'

    parts = [f"<Topic {attrs}>"]
    parts.append(f"<Title>{title}</Title>")
    if priority:
        parts.append(f"<Priority>{priority}</Priority>")
    if labels:
        parts.append("<Labels>")
        for lab in labels:
            parts.append(f"<Label>{lab}</Label>")
        parts.append("</Labels>")
    parts.append(f"<CreationDate>{creation_date}</CreationDate>")
    parts.append(f"<CreationAuthor>{creation_author}</CreationAuthor>")
    if description:
        parts.append(f"<Description>{description}</Description>")
    for c in comments or []:
        parts.append(f'<Comment Guid="{c["guid"]}">')
        parts.append(f"<Date>{c.get('date', '2026-05-21T11:00:00Z')}</Date>")
        parts.append(f"<Author>{c.get('author', 'commenter')}</Author>")
        parts.append(f"<Comment>{c.get('comment', 'comment text')}</Comment>")
        if "viewpoint_guid" in c:
            parts.append(f'<Viewpoint Guid="{c["viewpoint_guid"]}"/>')
        parts.append("</Comment>")
    if viewpoints:
        parts.append("<Viewpoints>")
        for vp in viewpoints:
            parts.append(f'<ViewPoint Guid="{vp["guid"]}">')
            parts.append(f"<Viewpoint>{vp['guid']}.bcfv</Viewpoint>")
            if vp.get("snapshot"):
                parts.append(f"<Snapshot>{vp['snapshot']}</Snapshot>")
            parts.append("</ViewPoint>")
        parts.append("</Viewpoints>")
    parts.append("</Topic>")
    return ('<?xml version="1.0" encoding="utf-8"?><Markup>' + "".join(parts) + "</Markup>").encode("utf-8")


def _visinfo_xml(
    guid: str,
    *,
    camera: str = "perspective",
    visible: list[str] | None = None,
    hidden: list[str] | None = None,
    selection: list[str] | None = None,
    default_visibility: bool = True,
    clipping_planes: list[tuple[tuple[float, float, float], tuple[float, float, float]]] | None = None,
) -> bytes:
    parts = [f'<VisualizationInfo Guid="{guid}">']
    if selection or visible or hidden:
        parts.append("<Components>")
        if selection:
            parts.append("<Selection>")
            for g in selection:
                parts.append(f'<Component IfcGuid="{g}"/>')
            parts.append("</Selection>")
        # Visibility / Exceptions
        if visible or hidden:
            dv = "true" if default_visibility else "false"
            parts.append(f'<Visibility DefaultVisibility="{dv}">')
            exc = hidden if default_visibility else visible
            if exc:
                parts.append("<Exceptions>")
                for g in exc:
                    parts.append(f'<Component IfcGuid="{g}"/>')
                parts.append("</Exceptions>")
            parts.append("</Visibility>")
        parts.append("</Components>")

    if camera == "perspective":
        parts.append("<PerspectiveCamera>")
        parts.append("<CameraViewPoint><X>1.0</X><Y>2.0</Y><Z>3.0</Z></CameraViewPoint>")
        parts.append("<CameraDirection><X>0.0</X><Y>1.0</Y><Z>0.0</Z></CameraDirection>")
        parts.append("<CameraUpVector><X>0.0</X><Y>0.0</Y><Z>1.0</Z></CameraUpVector>")
        parts.append("<FieldOfView>60.0</FieldOfView>")
        parts.append("<AspectRatio>1.7777778</AspectRatio>")
        parts.append("</PerspectiveCamera>")
    elif camera == "orthogonal":
        parts.append("<OrthogonalCamera>")
        parts.append("<CameraViewPoint><X>4.0</X><Y>5.0</Y><Z>6.0</Z></CameraViewPoint>")
        parts.append("<CameraDirection><X>0.0</X><Y>-1.0</Y><Z>0.0</Z></CameraDirection>")
        parts.append("<CameraUpVector><X>0.0</X><Y>0.0</Y><Z>1.0</Z></CameraUpVector>")
        parts.append("<ViewToWorldScale>2.5</ViewToWorldScale>")
        parts.append("<AspectRatio>1.5</AspectRatio>")
        parts.append("</OrthogonalCamera>")

    if clipping_planes:
        parts.append("<ClippingPlanes>")
        for loc, dirn in clipping_planes:
            parts.append("<ClippingPlane>")
            parts.append(f"<Location><X>{loc[0]}</X><Y>{loc[1]}</Y><Z>{loc[2]}</Z></Location>")
            parts.append(f"<Direction><X>{dirn[0]}</X><Y>{dirn[1]}</Y><Z>{dirn[2]}</Z></Direction>")
            parts.append("</ClippingPlane>")
        parts.append("</ClippingPlanes>")

    parts.append("</VisualizationInfo>")
    return ('<?xml version="1.0" encoding="utf-8"?>' + "".join(parts)).encode("utf-8")


def _make_uuid() -> str:
    return str(uuid.uuid4())


# ── 1. minimal 1-topic archive ────────────────────────────────────────────


def test_reader_parses_minimal_1_topic_archive() -> None:
    guid = _make_uuid()
    data = _make_zip(
        [
            ("bcf.version", _version_xml()),
            (f"{guid}/markup.bcf", _markup_xml(guid=guid)),
        ]
    )
    parsed = BCFReader.from_bytes(data)
    assert parsed.version == "3.0"
    assert len(parsed.topics) == 1
    t = parsed.topics[0]
    assert t.guid == guid
    assert t.title == "Topic title"
    assert t.topic_type == "Clash"
    assert t.topic_status == "Open"
    assert t.creation_author == "alice@example.com"
    assert isinstance(t.creation_date, datetime)


# ── 2. 5 topics × 10 comments × 1 viewpoint each ──────────────────────────


def test_reader_parses_5_topics_with_comments_and_viewpoints() -> None:
    entries: list[tuple[str, bytes]] = [("bcf.version", _version_xml())]
    seen_guids: list[str] = []
    for _ in range(5):
        tguid = _make_uuid()
        seen_guids.append(tguid)
        vguid = _make_uuid()
        comments = [{"guid": _make_uuid(), "comment": f"comment {i} on {tguid}"} for i in range(10)]
        viewpoints = [{"guid": vguid}]
        entries.append(
            (
                f"{tguid}/markup.bcf",
                _markup_xml(guid=tguid, comments=comments, viewpoints=viewpoints),
            )
        )
        entries.append((f"{tguid}/{vguid}.bcfv", _visinfo_xml(vguid)))
    data = _make_zip(entries)
    parsed = BCFReader.from_bytes(data)
    assert len(parsed.topics) == 5
    for topic in parsed.topics:
        assert len(topic.comments) == 10
        assert len(topic.viewpoints) == 1
        # camera populated from .bcfv
        assert topic.viewpoints[0].camera_type == "perspective"


# ── 3. visibility decode: DefaultVisibility=true + Exceptions ─────────────


def test_visibility_default_true_with_exceptions_marks_them_hidden() -> None:
    """DefaultVisibility=true → Exceptions list is the HIDDEN set."""
    tguid = _make_uuid()
    vguid = _make_uuid()
    data = _make_zip(
        [
            ("bcf.version", _version_xml()),
            (
                f"{tguid}/markup.bcf",
                _markup_xml(guid=tguid, viewpoints=[{"guid": vguid}]),
            ),
            (
                f"{tguid}/{vguid}.bcfv",
                _visinfo_xml(
                    vguid,
                    hidden=["GUID_A", "GUID_B"],
                    default_visibility=True,
                ),
            ),
        ]
    )
    parsed = BCFReader.from_bytes(data)
    vp = parsed.topics[0].viewpoints[0]
    assert vp.default_visibility is True
    assert vp.hidden == ("GUID_A", "GUID_B")
    assert vp.visible == ()


# ── 4. visibility decode: DefaultVisibility=false + Exceptions ────────────


def test_visibility_default_false_with_exceptions_marks_them_visible() -> None:
    """DefaultVisibility=false → Exceptions list is the VISIBLE set."""
    tguid = _make_uuid()
    vguid = _make_uuid()
    data = _make_zip(
        [
            ("bcf.version", _version_xml()),
            (
                f"{tguid}/markup.bcf",
                _markup_xml(guid=tguid, viewpoints=[{"guid": vguid}]),
            ),
            (
                f"{tguid}/{vguid}.bcfv",
                _visinfo_xml(
                    vguid,
                    visible=["GUID_X", "GUID_Y"],
                    default_visibility=False,
                ),
            ),
        ]
    )
    parsed = BCFReader.from_bytes(data)
    vp = parsed.topics[0].viewpoints[0]
    assert vp.default_visibility is False
    assert vp.visible == ("GUID_X", "GUID_Y")
    assert vp.hidden == ()


# ── 5/6/7. ISO 8601 parsing — Z, +02:00, naive ────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected_tz"),
    [
        ("2026-05-21T10:00:00Z", UTC),
        ("2026-05-21T10:00:00+02:00", "offset"),
        ("2026-05-21T10:00:00", UTC),  # naive → assumed UTC
    ],
)
def test_iso8601_variants_parse(raw: str, expected_tz) -> None:
    tguid = _make_uuid()
    data = _make_zip(
        [
            ("bcf.version", _version_xml()),
            (
                f"{tguid}/markup.bcf",
                _markup_xml(guid=tguid, creation_date=raw),
            ),
        ]
    )
    parsed = BCFReader.from_bytes(data)
    cd = parsed.topics[0].creation_date
    assert cd is not None
    assert cd.tzinfo is not None
    if expected_tz is UTC:
        assert cd.utcoffset().total_seconds() == 0
    else:
        # +02:00 offset preserved by datetime.fromisoformat
        assert cd.utcoffset().total_seconds() == 2 * 3600


# ── 8. malformed XML in one topic isolated as parse_error ─────────────────


def test_one_malformed_markup_does_not_kill_the_archive() -> None:
    good_guid = _make_uuid()
    bad_guid = _make_uuid()
    data = _make_zip(
        [
            ("bcf.version", _version_xml()),
            (f"{good_guid}/markup.bcf", _markup_xml(guid=good_guid)),
            (f"{bad_guid}/markup.bcf", b"<not-a-valid-xml<<>>"),
        ]
    )
    parsed = BCFReader.from_bytes(data)
    assert len(parsed.topics) == 2
    by_err = {t.parse_error is None: t for t in parsed.topics}
    assert True in by_err  # at least one good topic
    assert False in by_err  # at least one bad
    bad_topic = by_err[False]
    assert (
        "not well-formed" in (bad_topic.parse_error or "").lower()
        or "syntax" in (bad_topic.parse_error or "").lower()
        or "xml" in (bad_topic.parse_error or "").lower()
    )


# ── 9. path-traversal raises BCFSecurityError ─────────────────────────────


def test_path_traversal_entry_raises_security_error() -> None:
    """A zip member with `..` in its path must abort the parse."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bcf.version", _version_xml())
        zf.writestr("../etc/passwd", b"pwned")
    with pytest.raises(BCFSecurityError):
        BCFReader.from_bytes(buf.getvalue())


# ── 10. uncompressed > 100 MB → BCFSecurityError ──────────────────────────


def test_uncompressed_oversize_archive_raises_security_error() -> None:
    """Use a tiny reader cap so we don't actually allocate 100 MB."""
    reader = BCFReader(max_total_bytes=1024)  # 1 KiB cap
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bcf.version", _version_xml())
        # Highly compressible payload that decompresses past the cap.
        zf.writestr("big.bin", b"A" * (10 * 1024))
    # The raw zip is small; the post-decompression total isn't.
    # First test: raw payload still under the byte cap → it's the
    # uncompressed total that trips the limit.
    with pytest.raises(BCFSecurityError):
        reader.parse(buf.getvalue())


def test_raw_payload_oversize_raises_security_error() -> None:
    """A raw byte payload over the cap is refused before zip opens."""
    reader = BCFReader(max_total_bytes=10)
    with pytest.raises(BCFSecurityError):
        reader.parse(b"x" * 100)


# ── 11. snapshot.png bytes attached ───────────────────────────────────────


def test_snapshot_png_bytes_attached_to_topic() -> None:
    tguid = _make_uuid()
    vguid = _make_uuid()
    png = _minimal_png()
    data = _make_zip(
        [
            ("bcf.version", _version_xml()),
            (
                f"{tguid}/markup.bcf",
                _markup_xml(
                    guid=tguid,
                    viewpoints=[{"guid": vguid, "snapshot": "snapshot.png"}],
                ),
            ),
            (f"{tguid}/{vguid}.bcfv", _visinfo_xml(vguid)),
            (f"{tguid}/snapshot.png", png),
        ]
    )
    parsed = BCFReader.from_bytes(data)
    t = parsed.topics[0]
    assert "snapshot.png" in t.snapshots
    assert t.snapshots["snapshot.png"] == png


# ── 12. ServerAssignedId parsed ───────────────────────────────────────────


def test_server_assigned_id_parsed() -> None:
    tguid = _make_uuid()
    data = _make_zip(
        [
            ("bcf.version", _version_xml()),
            (
                f"{tguid}/markup.bcf",
                _markup_xml(guid=tguid, server_assigned_id="CLASH-042"),
            ),
        ]
    )
    parsed = BCFReader.from_bytes(data)
    assert parsed.topics[0].server_assigned_id == "CLASH-042"


# ── 13. comments inherit topic guid as parent (via topic.comments) ────────


def test_comments_are_attached_to_their_topic() -> None:
    tguid = _make_uuid()
    cguid_a = _make_uuid()
    cguid_b = _make_uuid()
    data = _make_zip(
        [
            ("bcf.version", _version_xml()),
            (
                f"{tguid}/markup.bcf",
                _markup_xml(
                    guid=tguid,
                    comments=[
                        {"guid": cguid_a, "comment": "first"},
                        {"guid": cguid_b, "comment": "second"},
                    ],
                ),
            ),
        ]
    )
    parsed = BCFReader.from_bytes(data)
    t = parsed.topics[0]
    assert [c.guid for c in t.comments] == [cguid_a, cguid_b]
    assert [c.comment for c in t.comments] == ["first", "second"]


# ── 14. multiple viewpoints preserved in declaration order ────────────────


def test_multiple_viewpoints_preserve_order() -> None:
    tguid = _make_uuid()
    v1 = _make_uuid()
    v2 = _make_uuid()
    v3 = _make_uuid()
    data = _make_zip(
        [
            ("bcf.version", _version_xml()),
            (
                f"{tguid}/markup.bcf",
                _markup_xml(
                    guid=tguid,
                    viewpoints=[{"guid": v1}, {"guid": v2}, {"guid": v3}],
                ),
            ),
            (f"{tguid}/{v1}.bcfv", _visinfo_xml(v1, camera="perspective")),
            (f"{tguid}/{v2}.bcfv", _visinfo_xml(v2, camera="orthogonal")),
            (f"{tguid}/{v3}.bcfv", _visinfo_xml(v3, camera="perspective")),
        ]
    )
    parsed = BCFReader.from_bytes(data)
    guids = [vp.guid for vp in parsed.topics[0].viewpoints]
    assert guids == [v1, v2, v3]


# ── 15. missing Title → parse_error on that topic ─────────────────────────


def test_missing_required_title_surfaces_as_parse_error() -> None:
    tguid = _make_uuid()
    # A markup with a Topic element but NO <Title>.
    body = (
        '<?xml version="1.0" encoding="utf-8"?><Markup>'
        f'<Topic Guid="{tguid}" TopicType="Clash" TopicStatus="Open">'
        "<CreationDate>2026-05-21T10:00:00Z</CreationDate>"
        "<CreationAuthor>alice@example.com</CreationAuthor>"
        "</Topic></Markup>"
    ).encode()
    data = _make_zip(
        [
            ("bcf.version", _version_xml()),
            (f"{tguid}/markup.bcf", body),
        ]
    )
    parsed = BCFReader.from_bytes(data)
    assert len(parsed.topics) == 1
    t = parsed.topics[0]
    assert t.parse_error is not None
    assert "Title" in t.parse_error
    assert tguid in t.parse_error


# ── 16. empty zip (only bcf.version) ──────────────────────────────────────


def test_empty_archive_returns_version_and_empty_topics() -> None:
    data = _make_zip([("bcf.version", _version_xml())])
    parsed = BCFReader.from_bytes(data)
    assert parsed.version == "3.0"
    assert parsed.topics == ()
    assert parsed.project is None


# ── 17. unicode round-trip ────────────────────────────────────────────────


def test_unicode_in_title_description_author_preserved() -> None:
    tguid = _make_uuid()
    data = _make_zip(
        [
            ("bcf.version", _version_xml()),
            (
                f"{tguid}/markup.bcf",
                _markup_xml(
                    guid=tguid,
                    title="Конфликт стен — Mauerkollision — 衝突",
                    description="🚨 Description with emoji + Ωmega",
                    creation_author="Müller@Тест.рф",
                ),
            ),
        ]
    )
    parsed = BCFReader.from_bytes(data)
    t = parsed.topics[0]
    assert t.title == "Конфликт стен — Mauerkollision — 衝突"
    assert t.description == "🚨 Description with emoji + Ωmega"
    assert t.creation_author == "Müller@Тест.рф"


# ── 18. ClippingPlanes list parsed ────────────────────────────────────────


def test_clipping_planes_parsed() -> None:
    tguid = _make_uuid()
    vguid = _make_uuid()
    data = _make_zip(
        [
            ("bcf.version", _version_xml()),
            (
                f"{tguid}/markup.bcf",
                _markup_xml(guid=tguid, viewpoints=[{"guid": vguid}]),
            ),
            (
                f"{tguid}/{vguid}.bcfv",
                _visinfo_xml(
                    vguid,
                    clipping_planes=[
                        ((1.0, 2.0, 3.0), (0.0, 0.0, 1.0)),
                        ((4.0, 5.0, 6.0), (1.0, 0.0, 0.0)),
                    ],
                ),
            ),
        ]
    )
    parsed = BCFReader.from_bytes(data)
    vp = parsed.topics[0].viewpoints[0]
    assert len(vp.clipping_planes) == 2
    assert vp.clipping_planes[0].location == (1.0, 2.0, 3.0)
    assert vp.clipping_planes[0].direction == (0.0, 0.0, 1.0)
    assert vp.clipping_planes[1].location == (4.0, 5.0, 6.0)


# ── 19. orthogonal + perspective both supported ───────────────────────────


def test_orthogonal_camera_supported() -> None:
    tguid = _make_uuid()
    vguid = _make_uuid()
    data = _make_zip(
        [
            ("bcf.version", _version_xml()),
            (
                f"{tguid}/markup.bcf",
                _markup_xml(guid=tguid, viewpoints=[{"guid": vguid}]),
            ),
            (f"{tguid}/{vguid}.bcfv", _visinfo_xml(vguid, camera="orthogonal")),
        ]
    )
    parsed = BCFReader.from_bytes(data)
    vp = parsed.topics[0].viewpoints[0]
    assert vp.camera_type == "orthogonal"
    assert vp.view_to_world_scale == 2.5
    assert vp.field_of_view is None
    assert vp.camera_view_point == (4.0, 5.0, 6.0)
    assert vp.aspect_ratio == 1.5


def test_perspective_camera_supported() -> None:
    tguid = _make_uuid()
    vguid = _make_uuid()
    data = _make_zip(
        [
            ("bcf.version", _version_xml()),
            (
                f"{tguid}/markup.bcf",
                _markup_xml(guid=tguid, viewpoints=[{"guid": vguid}]),
            ),
            (f"{tguid}/{vguid}.bcfv", _visinfo_xml(vguid, camera="perspective")),
        ]
    )
    parsed = BCFReader.from_bytes(data)
    vp = parsed.topics[0].viewpoints[0]
    assert vp.camera_type == "perspective"
    assert vp.field_of_view == 60.0
    assert vp.view_to_world_scale is None
    assert vp.aspect_ratio == 1.7777778


# ── Bonus: from_file reads a real .bcfzip from disk ───────────────────────


def test_from_file_round_trip(tmp_path: Path) -> None:
    tguid = _make_uuid()
    data = _make_zip(
        [
            ("bcf.version", _version_xml()),
            (f"{tguid}/markup.bcf", _markup_xml(guid=tguid)),
        ]
    )
    path = tmp_path / "topic.bcfzip"
    path.write_bytes(data)
    parsed = BCFReader.from_file(str(path))
    assert len(parsed.topics) == 1
    assert parsed.topics[0].guid == tguid


# ── Bonus: non-zip payload raises BCFFormatError ──────────────────────────


def test_non_zip_payload_raises_format_error() -> None:
    with pytest.raises(BCFFormatError):
        BCFReader.from_bytes(b"not a zip at all")


# ── Bonus: missing bcf.version → BCFFormatError ───────────────────────────


def test_archive_without_bcf_version_raises_format_error() -> None:
    data = _make_zip([("readme.txt", b"hello")])
    with pytest.raises(BCFFormatError):
        BCFReader.from_bytes(data)


# ── Bonus: too-many-entries cap ───────────────────────────────────────────


def test_too_many_entries_raises_security_error() -> None:
    reader = BCFReader(max_entries=3)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bcf.version", _version_xml())
        for i in range(5):
            zf.writestr(f"file_{i}.txt", b"x")
    with pytest.raises(BCFSecurityError):
        reader.parse(buf.getvalue())


# ── Sanity: ParsedTopic is frozen ─────────────────────────────────────────


def test_parsed_topic_is_frozen() -> None:
    t = ParsedTopic(
        guid="x",
        topic_type="Clash",
        topic_status="Open",
        title="t",
        creation_date=datetime(2026, 5, 21, tzinfo=UTC),
        creation_author="a",
    )
    with pytest.raises(Exception):
        t.title = "mutated"  # type: ignore[misc]
