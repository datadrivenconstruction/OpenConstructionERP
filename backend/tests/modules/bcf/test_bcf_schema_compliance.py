# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Hand-coded BCF 3.0 schema compliance probe.

The buildingSMART BCF 3.0 XSD set lives at
https://github.com/buildingSMART/BCF-XML/blob/release_3_0/Schemas/. We
keep a hand-coded "required-element" checker here rather than pulling
the live XSD because:

1. lxml is not a hard backend dependency (CLAUDE.md philosophy 1
   "lightweight & simple"), and a network fetch in a unit test is
   flaky on a fresh CI runner;
2. the BCF 3.0 markup.xsd only mandates a handful of elements per
   topic / viewpoint — see the spec's "Topic minimum" and "Camera
   choice" rules. We assert those directly.

If lxml is installed in the runner we *also* parse the XML with
``lxml.etree`` to catch any non-stdlib well-formedness drift.
"""

from __future__ import annotations

import io
import uuid
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime

import pytest

from app.modules.bcf.writer import (
    BCFComment,
    BCFTopic,
    BCFViewpoint,
    BCFWriter,
    build_markup_xml,
    build_visinfo_xml,
)

# Required Topic elements per markup.xsd (Topic minimum).
_TOPIC_REQUIRED_ELEMENTS: tuple[str, ...] = (
    "Title",
    "CreationDate",
    "CreationAuthor",
)
# Required Topic attributes.
_TOPIC_REQUIRED_ATTRS: tuple[str, ...] = ("Guid", "TopicType", "TopicStatus")

# Required Comment elements.
_COMMENT_REQUIRED_ELEMENTS: tuple[str, ...] = ("Date", "Author", "Comment")
_COMMENT_REQUIRED_ATTRS: tuple[str, ...] = ("Guid",)


def _ts() -> datetime:
    return datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)


def _full_topic() -> BCFTopic:
    return BCFTopic(
        guid=str(uuid.uuid4()),
        topic_type="Clash",
        topic_status="Open",
        title="Schema compliance probe",
        creation_date=_ts(),
        creation_author="probe@example.com",
        priority="Normal",
        description="Schema-compliance integration test fixture.",
        comments=[
            BCFComment(
                guid=str(uuid.uuid4()),
                date=_ts(),
                author="probe@example.com",
                comment="Initial review note.",
            ),
        ],
        viewpoints=[
            BCFViewpoint(
                guid=str(uuid.uuid4()),
                camera_type="perspective",
                camera_view_point=(5.0, 5.0, 1.7),
                camera_direction=(-1.0, 0.0, 0.0),
                camera_up_vector=(0.0, 0.0, 1.0),
                field_of_view=60.0,
                selection=["3$5XB7$gv5DOC9NlSk7P4z"],
                visible=["a", "b"],
                hidden=["x", "y", "z", "w", "v"],
            )
        ],
    )


# ── markup.bcf required-elements / required-attrs probe ─────────────────


def test_markup_topic_required_attributes_present() -> None:
    raw = build_markup_xml(_full_topic())
    root = ET.fromstring(raw)
    topic = root.find("Topic")
    assert topic is not None, "markup.bcf must have a <Topic> element"
    for attr in _TOPIC_REQUIRED_ATTRS:
        assert topic.get(attr), f"Topic@{attr} is required by markup.xsd"


def test_markup_topic_required_child_elements_present() -> None:
    raw = build_markup_xml(_full_topic())
    root = ET.fromstring(raw)
    topic = root.find("Topic")
    for tag in _TOPIC_REQUIRED_ELEMENTS:
        assert topic.find(tag) is not None, f"<{tag}> is required by markup.xsd"


def test_markup_comment_required_fields_present() -> None:
    raw = build_markup_xml(_full_topic())
    root = ET.fromstring(raw)
    c = root.find("Topic/Comment")
    assert c is not None
    for attr in _COMMENT_REQUIRED_ATTRS:
        assert c.get(attr), f"Comment@{attr} is required by markup.xsd"
    for tag in _COMMENT_REQUIRED_ELEMENTS:
        assert c.find(tag) is not None, f"Comment <{tag}> is required by markup.xsd"


def test_markup_well_formed_xml() -> None:
    raw = build_markup_xml(_full_topic())
    # ET.fromstring would have raised on malformed XML.
    root = ET.fromstring(raw)
    # Re-serialise round-trip — must be lossless for elements we care about.
    again = ET.tostring(root, encoding="utf-8")
    again_root = ET.fromstring(again)
    assert again_root.find("Topic/Title").text == "Schema compliance probe"


# ── viewpoint.bcfv camera-choice rule ────────────────────────────────────


def test_visinfo_exactly_one_camera() -> None:
    """BCF 3.0 visinfo.xsd requires exactly one camera (xs:choice)."""
    t = _full_topic()
    raw = build_visinfo_xml(t.viewpoints[0])
    root = ET.fromstring(raw)
    cam_count = sum(1 for c in root if c.tag in ("PerspectiveCamera", "OrthogonalCamera"))
    assert cam_count == 1


def test_visinfo_camera_vector_children_ordered() -> None:
    """All BCF vectors are <X/><Y/><Z/> in that exact order."""
    t = _full_topic()
    raw = build_visinfo_xml(t.viewpoints[0])
    root = ET.fromstring(raw)
    cam = root.find("PerspectiveCamera")
    for vec_tag in ("CameraViewPoint", "CameraDirection", "CameraUpVector"):
        el = cam.find(vec_tag)
        assert el is not None, vec_tag
        children = [c.tag for c in el]
        assert children == ["X", "Y", "Z"]


def test_visinfo_visibility_default_attribute_boolean() -> None:
    t = _full_topic()
    raw = build_visinfo_xml(t.viewpoints[0])
    root = ET.fromstring(raw)
    vis = root.find("Components/Visibility")
    assert vis.get("DefaultVisibility") in ("true", "false")


def test_visinfo_guid_attribute_set() -> None:
    """visinfo.xsd: VisualizationInfo@Guid is required in BCF 3.0."""
    t = _full_topic()
    raw = build_visinfo_xml(t.viewpoints[0])
    root = ET.fromstring(raw)
    assert root.tag == "VisualizationInfo"
    assert root.get("Guid")


# ── lxml-strict probe (optional) ─────────────────────────────────────────


def test_lxml_strict_well_formedness_if_available() -> None:
    """If lxml is installed, re-parse every emitted XML doc with it."""
    lxml_etree = pytest.importorskip("lxml.etree")
    t = _full_topic()
    # Whole-archive blob.
    blob = BCFWriter().set_project("p1", "P1").add_topic(t).build_bytes()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        xml_members = [
            n
            for n in zf.namelist()
            if n.endswith(".xml")
            or n.endswith(".bcf")
            or n.endswith(".bcfv")
            or n == "bcf.version"
            or n == "project.bcfp"
        ]
        assert xml_members
        for name in xml_members:
            data = zf.read(name)
            # Will raise if not well-formed.
            lxml_etree.fromstring(data)


# ── archive layout probe ────────────────────────────────────────────────


def test_full_archive_layout_matches_bcf_3_0_spec() -> None:
    t = _full_topic()
    blob = BCFWriter().set_project("p1", "P1").add_topic(t).build_bytes()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
    assert "bcf.version" in names
    assert "extensions.xml" in names
    assert "project.bcfp" in names
    # markup + bcfv per topic
    assert any(n.endswith("markup.bcf") for n in names)
    assert any(n.endswith(".bcfv") for n in names)


def test_archive_is_a_valid_zip() -> None:
    blob = BCFWriter().add_topic(_full_topic()).build_bytes()
    # Will raise on a malformed archive.
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        bad = zf.testzip()
    assert bad is None
