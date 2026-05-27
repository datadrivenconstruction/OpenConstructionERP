# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Tests for :mod:`app.modules.bcf.writer` — the BCF 3.0 zip builder.

Coverage matrix
---------------
* zip layout (bcf.version / extensions.xml / project.bcfp / per-topic dir)
* version document is BCF 3.0
* extensions.xml carries default TopicTypes / TopicStatuses / Priorities
* markup.bcf well-formed XML with required fields
* viewpoint.bcfv well-formed XML with exactly one camera
* visibility shorter-list optimisation (visible-shorter, hidden-shorter,
  symmetric — both halves of the rule)
* deterministic byte output for the same input
* GUID safety — paths can't escape the archive root
* dataclass validation (duplicate guids, missing fields)
* default extension override via add_extension_list
* snapshot PNG bytes are written verbatim
* PNG magic-number gate rejects non-PNG payloads
* orthogonal camera path
"""

from __future__ import annotations

import io
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime

import pytest

from app.modules.bcf.writer import (
    BCF_VERSION,
    BCFComment,
    BCFTopic,
    BCFViewpoint,
    BCFWriter,
    build_markup_xml,
    build_project_xml,
    build_version_xml,
    build_visinfo_xml,
    synthesize_viewpoint_from_centroid,
)

# 1x1 transparent PNG — used for snapshot-write tests.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63000100000005000100b5d4f8a30000000049454e44ae"
    "426082"
)


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, 0, 0, tzinfo=UTC)


def _new_guid() -> str:
    return str(uuid.uuid4())


def _make_topic(
    *,
    title: str = "Wall vs Pipe clash",
    creation_author: str = "tester@example.com",
    comments: int = 0,
    viewpoints: int = 0,
) -> BCFTopic:
    """Build a BCFTopic with N comments and M viewpoints attached."""
    t = BCFTopic(
        guid=_new_guid(),
        topic_type="Clash",
        topic_status="Open",
        title=title,
        creation_date=_utc(2026, 5, 21),
        creation_author=creation_author,
        priority="Major",
        description="Auto-generated clash for the BCF writer test suite.",
    )
    for i in range(comments):
        t.comments.append(
            BCFComment(
                guid=_new_guid(),
                date=_utc(2026, 5, 21),
                author=f"author-{i}@example.com",
                comment=f"Comment {i} body — needs follow-up.",
            )
        )
    for i in range(viewpoints):
        t.viewpoints.append(
            BCFViewpoint(
                guid=_new_guid(),
                camera_type="perspective",
                camera_view_point=(1.0 + i, 2.0, 3.0),
                camera_direction=(0.0, -1.0, 0.0),
                camera_up_vector=(0.0, 0.0, 1.0),
                field_of_view=55.0,
                selection=[f"2O2Fr$t4X7Zf8NOew3FN{i}"],
            )
        )
    return t


# ── 1. Version document ───────────────────────────────────────────────────


def test_version_xml_declares_bcf_3_0() -> None:
    raw = build_version_xml()
    root = ET.fromstring(raw)
    assert root.tag == "Version"
    assert root.get("VersionId") == "3.0"
    assert BCF_VERSION == "3.0"


# ── 2. Default zip layout ────────────────────────────────────────────────


def test_writer_zip_layout_minimal() -> None:
    w = BCFWriter().set_project("proj-42", "Test Project")
    w.add_topic(_make_topic(viewpoints=1))
    blob = w.build_bytes()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())
    assert "bcf.version" in names
    assert "extensions.xml" in names
    assert "project.bcfp" in names
    # exactly one topic folder with markup + bcfv
    topic_dirs = {n.split("/", 1)[0] for n in names if "/" in n}
    assert len(topic_dirs) == 1
    folder = next(iter(topic_dirs))
    assert f"{folder}/markup.bcf" in names
    assert any(n.endswith(".bcfv") for n in names)


def test_writer_three_topics_two_comments_one_viewpoint_each() -> None:
    w = BCFWriter().set_project("p1", "Three-topic project")
    for _ in range(3):
        w.add_topic(_make_topic(comments=2, viewpoints=1))
    blob = w.build_bytes()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        markup_names = [n for n in zf.namelist() if n.endswith("markup.bcf")]
        bcfv_names = [n for n in zf.namelist() if n.endswith(".bcfv")]
    assert len(markup_names) == 3
    assert len(bcfv_names) == 3


# ── 3. extensions.xml ────────────────────────────────────────────────────


def test_extensions_xml_has_default_enums() -> None:
    w = BCFWriter()
    w.add_topic(_make_topic())
    blob = w.build_bytes()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        raw = zf.read("extensions.xml")
    root = ET.fromstring(raw)
    topic_types_container = root.find("TopicTypes")
    assert topic_types_container is not None
    values = {el.text for el in topic_types_container.findall("TopicType")}
    assert {"Issue", "Information", "Clash"}.issubset(values)
    statuses_container = root.find("TopicStatuses")
    statuses = {el.text for el in statuses_container.findall("TopicStatus")}
    assert {"Open", "Closed"}.issubset(statuses)
    priorities_container = root.find("Priorities")
    priorities = {el.text for el in priorities_container.findall("Priority")}
    assert {"Critical", "Major", "Normal", "Minor"}.issubset(priorities)


def test_extensions_xml_override() -> None:
    w = BCFWriter()
    w.add_extension_list("Stages", ["Design", "Tender", "Construction"])
    w.add_topic(_make_topic())
    blob = w.build_bytes()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        raw = zf.read("extensions.xml")
    root = ET.fromstring(raw)
    stages = root.find("Stages")
    assert stages is not None
    texts = [el.text for el in stages.findall("Stage")]
    assert texts == ["Design", "Tender", "Construction"]


def test_extensions_unknown_kind_rejected() -> None:
    w = BCFWriter()
    with pytest.raises(ValueError, match="Unknown extension list"):
        w.add_extension_list("Foobars", ["x", "y"])


# ── 4. markup.bcf well-formed XML + required fields ──────────────────────


def test_markup_bcf_required_fields_present() -> None:
    t = _make_topic(comments=2)
    raw = build_markup_xml(t)
    root = ET.fromstring(raw)
    topic_el = root.find("Topic")
    assert topic_el is not None
    assert topic_el.get("Guid")
    assert topic_el.get("TopicType") == "Clash"
    assert topic_el.get("TopicStatus") == "Open"
    assert topic_el.findtext("Title") == t.title
    assert topic_el.findtext("CreationDate", "").endswith("Z")
    assert topic_el.findtext("CreationAuthor") == t.creation_author
    comments = topic_el.findall("Comment")
    assert len(comments) == 2
    for c_el in comments:
        assert c_el.get("Guid")
        assert c_el.findtext("Date", "").endswith("Z")
        assert c_el.findtext("Author")
        assert c_el.find("Comment") is not None


def test_markup_bcf_viewpoint_reference() -> None:
    t = _make_topic(viewpoints=1)
    raw = build_markup_xml(t)
    root = ET.fromstring(raw)
    vps = root.find("Topic/Viewpoints")
    assert vps is not None
    vp = vps.find("ViewPoint")
    assert vp is not None and vp.get("Guid")
    ref = vp.findtext("Viewpoint", "")
    assert ref.endswith(".bcfv")


def test_markup_iso_dates_utc_z_suffix() -> None:
    t = _make_topic()
    t.modified_date = _utc(2026, 5, 22)
    t.modified_author = "editor@example.com"
    raw = build_markup_xml(t)
    root = ET.fromstring(raw)
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$",
        root.find("Topic").findtext("CreationDate"),
    )


# ── 5. viewpoint.bcfv ────────────────────────────────────────────────────


def test_visinfo_xml_perspective_camera() -> None:
    vp = BCFViewpoint(
        guid=_new_guid(),
        camera_type="perspective",
        camera_view_point=(1.0, 2.0, 3.0),
        camera_direction=(0.0, -1.0, 0.0),
        camera_up_vector=(0.0, 0.0, 1.0),
        field_of_view=50.0,
    )
    raw = build_visinfo_xml(vp)
    root = ET.fromstring(raw)
    assert root.tag == "VisualizationInfo"
    pc = root.find("PerspectiveCamera")
    assert pc is not None
    assert root.find("OrthogonalCamera") is None
    assert pc.findtext("FieldOfView") is not None
    # Vector children in stable order: X, Y, Z.
    vp_el = pc.find("CameraViewPoint")
    children = [c.tag for c in vp_el]
    assert children == ["X", "Y", "Z"]


def test_visinfo_xml_orthogonal_camera() -> None:
    vp = BCFViewpoint(
        guid=_new_guid(),
        camera_type="orthogonal",
        view_to_world_scale=2.5,
    )
    raw = build_visinfo_xml(vp)
    root = ET.fromstring(raw)
    oc = root.find("OrthogonalCamera")
    assert oc is not None
    assert root.find("PerspectiveCamera") is None
    assert oc.findtext("ViewToWorldScale") is not None
    assert oc.findtext("AspectRatio") is not None


# ── 6. Visibility shorter-list optimisation ──────────────────────────────


def test_visibility_visible_shorter_emits_visible_as_exceptions() -> None:
    vp = BCFViewpoint(
        guid=_new_guid(),
        visible=["v1", "v2"],  # 2 entries
        hidden=["h1", "h2", "h3", "h4"],  # 4 entries → visible is shorter
    )
    raw = build_visinfo_xml(vp)
    root = ET.fromstring(raw)
    vis = root.find("Components/Visibility")
    assert vis is not None
    # Shorter list = visible → DefaultVisibility=false, Exceptions=visible.
    assert vis.get("DefaultVisibility") == "false"
    exc = vis.find("Exceptions")
    assert exc is not None
    guids = {c.get("IfcGuid") for c in exc.findall("Component")}
    assert guids == {"v1", "v2"}


def test_visibility_hidden_shorter_emits_hidden_as_exceptions() -> None:
    vp = BCFViewpoint(
        guid=_new_guid(),
        visible=["v1", "v2", "v3", "v4", "v5"],
        hidden=["h1"],
    )
    raw = build_visinfo_xml(vp)
    root = ET.fromstring(raw)
    vis = root.find("Components/Visibility")
    assert vis.get("DefaultVisibility") == "true"
    exc = vis.find("Exceptions")
    guids = {c.get("IfcGuid") for c in exc.findall("Component")}
    assert guids == {"h1"}


def test_visibility_only_visible_list_flips_default() -> None:
    vp = BCFViewpoint(guid=_new_guid(), visible=["a", "b"], hidden=[])
    raw = build_visinfo_xml(vp)
    root = ET.fromstring(raw)
    vis = root.find("Components/Visibility")
    # A "visible" list with no hidden means "default-invisible, these are
    # the exceptions"  → DefaultVisibility=false.
    assert vis.get("DefaultVisibility") == "false"


def test_visibility_only_hidden_list_keeps_default() -> None:
    vp = BCFViewpoint(guid=_new_guid(), visible=[], hidden=["a", "b"])
    raw = build_visinfo_xml(vp)
    root = ET.fromstring(raw)
    vis = root.find("Components/Visibility")
    assert vis.get("DefaultVisibility") == "true"


# ── 7. Determinism ───────────────────────────────────────────────────────


def test_writer_deterministic_for_same_input() -> None:
    # Topic with stable GUIDs/dates so the output bytes don't drift.
    fixed_guid = "11111111-2222-3333-4444-555555555555"
    fixed_vp = "66666666-7777-8888-9999-aaaaaaaaaaaa"

    def _topic():
        t = BCFTopic(
            guid=fixed_guid,
            topic_type="Clash",
            topic_status="Open",
            title="Deterministic",
            creation_date=_utc(2026, 5, 21),
            creation_author="t@example.com",
        )
        t.viewpoints.append(
            BCFViewpoint(
                guid=fixed_vp,
                camera_type="perspective",
                selection=["A1", "B2"],
            )
        )
        return t

    a = BCFWriter().set_project("p", "P").add_topic(_topic()).build_bytes()
    b = BCFWriter().set_project("p", "P").add_topic(_topic()).build_bytes()
    # Zip files have a CRC + modification timestamp per entry. Compare the
    # XML members instead so we test our determinism, not zipfile's.
    with zipfile.ZipFile(io.BytesIO(a)) as za, zipfile.ZipFile(io.BytesIO(b)) as zb:
        for name in sorted(za.namelist()):
            assert za.read(name) == zb.read(name), f"non-deterministic content for {name!r}"


# ── 8. GUID safety ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_guid",
    [
        "../../../etc/passwd",
        "topic/with/slash",
        "spaces are bad",
        "",
    ],
)
def test_unsafe_topic_guid_rejected(bad_guid: str) -> None:
    t = _make_topic()
    t.guid = bad_guid
    w = BCFWriter()
    with pytest.raises(ValueError):
        w.add_topic(t)


def test_hex_signature_guid_accepted() -> None:
    # The clash module uses a 16-hex SHA-1 prefix as a stable id.
    sig = "deadbeefcafebabe"
    t = _make_topic()
    t.guid = sig
    w = BCFWriter().set_project("p", "P")
    w.add_topic(t)  # must not raise
    blob = w.build_bytes()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
    assert any(n.startswith(f"{sig}/") for n in names)


# ── 9. Required field / duplicate validation ─────────────────────────────


def test_duplicate_topic_guid_rejected() -> None:
    g = _new_guid()
    t1 = _make_topic()
    t1.guid = g
    t2 = _make_topic()
    t2.guid = g
    w = BCFWriter()
    w.add_topic(t1)
    with pytest.raises(ValueError, match="duplicate"):
        w.add_topic(t2)


def test_missing_required_field_rejected() -> None:
    t = _make_topic()
    t.title = ""
    with pytest.raises(ValueError, match="title"):
        BCFWriter().add_topic(t)


# ── 10. PNG snapshot ─────────────────────────────────────────────────────


def test_snapshot_png_written() -> None:
    vp = BCFViewpoint(guid=_new_guid(), snapshot_png=_PNG_BYTES)
    t = _make_topic()
    t.viewpoints.append(vp)
    blob = BCFWriter().add_topic(t).build_bytes()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        png_entries = [n for n in zf.namelist() if n.endswith("snapshot.png")]
        assert png_entries
        assert zf.read(png_entries[0]) == _PNG_BYTES


def test_non_png_snapshot_rejected() -> None:
    vp = BCFViewpoint(guid=_new_guid(), snapshot_png=b"not-a-png")
    t = _make_topic()
    t.viewpoints.append(vp)
    w = BCFWriter().add_topic(t)
    with pytest.raises(ValueError, match="not a PNG"):
        w.build_bytes()


# ── 11. project.bcfp ─────────────────────────────────────────────────────


def test_project_bcfp_carries_id_and_name() -> None:
    raw = build_project_xml("proj-123", "My Coordination Project")
    root = ET.fromstring(raw)
    assert root.tag == "ProjectInfo"
    proj = root.find("Project")
    assert proj.get("ProjectId") == "proj-123"
    assert proj.findtext("Name") == "My Coordination Project"


def test_project_optional_omitted_when_unset() -> None:
    blob = BCFWriter().add_topic(_make_topic()).build_bytes()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        assert "project.bcfp" not in zf.namelist()


# ── 12. Convenience: synthesize viewpoint ────────────────────────────────


def test_synthesize_viewpoint_default_camera() -> None:
    vp = synthesize_viewpoint_from_centroid((10.0, 20.0, 5.0))
    assert vp.camera_type == "perspective"
    # 5m back along -Y, slightly elevated.
    assert vp.camera_view_point[1] == pytest.approx(20.0 - 5.0)
    assert vp.camera_up_vector == (0.0, 0.0, 1.0)


def test_synthesize_viewpoint_with_selection() -> None:
    vp = synthesize_viewpoint_from_centroid((0.0, 0.0, 0.0), selection=["IFC-1", "IFC-2"])
    assert vp.selection == ["IFC-1", "IFC-2"]
