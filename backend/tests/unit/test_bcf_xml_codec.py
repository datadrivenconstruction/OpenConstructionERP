"""Unit tests for the hand-rolled BCF-XML codec (BCF 2.1 + 3.0).

Validates against the published buildingSMART BCF-XML element names
(``Markup``, ``Topic``, ``TopicGuid``-equivalent ``@Guid``,
``VisualizationInfo``, ``Components``, ``PerspectiveCamera``,
``OrthogonalCamera``) — not approximations.

No DB / network — pure codec roundtrip.
"""

from __future__ import annotations

import io
import uuid
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime

import pytest

from app.modules.bcf import bcf_xml

_PNG = b"\x89PNG\r\n\x1a\nFAKE"


def _sample_topic() -> bcf_xml.ParsedTopic:
    t = bcf_xml.ParsedTopic(
        guid=str(uuid.uuid4()),
        title="Clash: HVAC duct vs primary beam",
        description="The supply duct collides with the primary steel beam.",
        topic_type="Clash",
        topic_status="Open",
        priority="High",
        stage="Construction",
        index=42,
        assigned_to="bob@example.io",
        labels=["MEP", "Structure"],
        reference_links=["https://example.io/rfi/12"],
        creation_author="alice@example.io",
        creation_date=datetime(2026, 5, 18, 10, 0, 0, tzinfo=UTC),
        modified_author="bob@example.io",
        modified_date=datetime(2026, 5, 18, 12, 30, 0, tzinfo=UTC),
        due_date=datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC),
    )
    vp = bcf_xml.ParsedViewpoint(
        guid=str(uuid.uuid4()),
        camera_type="perspective",
        camera={
            "camera_view_point": {"x": 12.5, "y": -3.0, "z": 2.4},
            "camera_direction": {"x": 0.0, "y": 1.0, "z": 0.0},
            "camera_up_vector": {"x": 0.0, "y": 0.0, "z": 1.0},
        },
        components={
            "selection": ["2O2Fr$t4X7Zf8NOew3FNr", "1xS3BCk291UvhgP2dvNsgp"],
            "visible": [],
            "hidden": ["0aB9cD3eFGHijKlMnOpQrS"],
            "default_visibility": True,
        },
        field_of_view=55.0,
    )
    vp.snapshot_filename = "snapshot.png"
    vp.snapshot_bytes = _PNG
    t.viewpoints.append(vp)
    t.comments.append(
        bcf_xml.ParsedComment(
            guid=str(uuid.uuid4()),
            comment="Please reroute the duct above the beam.",
            author="alice@example.io",
            date=datetime(2026, 5, 18, 10, 30, 0, tzinfo=UTC),
            viewpoint_guid=vp.guid,
        )
    )
    return t


@pytest.mark.parametrize("version", ["2.1", "3.0"])
def test_roundtrip_is_lossless(version: str) -> None:
    """build → parse preserves every field we model, for both schemas."""
    topic = _sample_topic()
    archive = bcf_xml.build_bcfzip(
        version=version,
        project_id=str(uuid.uuid4()),
        project_name="Tower A",
        topics=[topic],
    )

    assert bcf_xml.detect_version(archive) == version

    result = bcf_xml.parse_bcfzip(archive)
    assert not result.has_errors, [(i.severity, i.code, i.message) for i in result.issues]
    assert result.detected_version == version
    assert len(result.topics) == 1

    pt = result.topics[0]
    assert pt.guid == topic.guid
    assert pt.title == topic.title
    assert pt.description == topic.description
    assert pt.topic_type == "Clash"
    assert pt.topic_status == "Open"
    assert pt.priority == "High"
    assert pt.stage == "Construction"
    assert pt.index == 42
    assert pt.assigned_to == "bob@example.io"
    assert sorted(pt.labels) == ["MEP", "Structure"]
    assert pt.reference_links == ["https://example.io/rfi/12"]
    assert pt.creation_author == "alice@example.io"
    assert pt.creation_date == topic.creation_date
    assert pt.modified_author == "bob@example.io"
    assert pt.due_date == topic.due_date

    assert len(pt.comments) == 1
    rc = pt.comments[0]
    assert rc.comment == "Please reroute the duct above the beam."
    assert rc.author == "alice@example.io"
    assert rc.viewpoint_guid == topic.viewpoints[0].guid

    assert len(pt.viewpoints) == 1
    rvp = pt.viewpoints[0]
    assert rvp.guid == topic.viewpoints[0].guid
    assert rvp.camera_type == "perspective"
    assert rvp.field_of_view == pytest.approx(55.0)
    assert rvp.camera["camera_view_point"] == {"x": 12.5, "y": -3.0, "z": 2.4}
    assert sorted(rvp.components["selection"]) == sorted(["2O2Fr$t4X7Zf8NOew3FNr", "1xS3BCk291UvhgP2dvNsgp"])
    assert rvp.components["hidden"] == ["0aB9cD3eFGHijKlMnOpQrS"]
    assert rvp.components["default_visibility"] is True
    assert rvp.snapshot_bytes == _PNG


@pytest.mark.parametrize("version", ["2.1", "3.0"])
def test_archive_contains_spec_named_members(version: str) -> None:
    """The .bcfzip carries spec-named members + spec element names."""
    topic = _sample_topic()
    archive = bcf_xml.build_bcfzip(
        version=version,
        project_id="proj-1",
        project_name="P",
        topics=[topic],
    )
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        names = set(zf.namelist())
        assert "bcf.version" in names
        assert "project.bcfp" in names
        assert f"{topic.guid}/markup.bcf" in names
        vp_guid = topic.viewpoints[0].guid
        assert f"{topic.guid}/{vp_guid}.bcfv" in names
        assert f"{topic.guid}/snapshot.png" in names

        # bcf.version uses the spec element + attribute names.
        ver_root = ET.fromstring(zf.read("bcf.version"))
        assert ver_root.tag == "Version"
        assert ver_root.get("VersionId") == version
        if version == "2.1":
            assert ver_root.find("DetailedVersion") is not None
        else:
            assert ver_root.find("DetailedVersion") is None

        # markup.bcf uses Markup/Topic/@Guid/Title (BCF-XML names).
        markup = ET.fromstring(zf.read(f"{topic.guid}/markup.bcf"))
        assert markup.tag == "Markup"
        topic_el = markup.find("Topic")
        assert topic_el is not None
        assert topic_el.get("Guid") == topic.guid
        assert topic_el.get("TopicStatus") == "Open"
        assert topic_el.find("Title") is not None

        # viewpoint .bcfv uses VisualizationInfo/Components/PerspectiveCamera.
        vis = ET.fromstring(zf.read(f"{topic.guid}/{vp_guid}.bcfv"))
        assert vis.tag == "VisualizationInfo"
        assert vis.find("Components") is not None
        assert vis.find("PerspectiveCamera") is not None


def test_orthogonal_camera_roundtrip() -> None:
    """An orthogonal-camera viewpoint roundtrips its ViewToWorldScale."""
    topic = bcf_xml.ParsedTopic(guid=str(uuid.uuid4()), title="Ortho view")
    topic.viewpoints.append(
        bcf_xml.ParsedViewpoint(
            guid=str(uuid.uuid4()),
            camera_type="orthogonal",
            camera={
                "camera_view_point": {"x": 0.0, "y": 0.0, "z": 10.0},
                "camera_direction": {"x": 0.0, "y": 0.0, "z": -1.0},
                "camera_up_vector": {"x": 0.0, "y": 1.0, "z": 0.0},
            },
            view_to_world_scale=2.5,
        )
    )
    archive = bcf_xml.build_bcfzip(version="3.0", project_id="p", project_name="n", topics=[topic])
    result = bcf_xml.parse_bcfzip(archive)
    assert not result.has_errors
    rvp = result.topics[0].viewpoints[0]
    assert rvp.camera_type == "orthogonal"
    assert rvp.view_to_world_scale == pytest.approx(2.5)


def test_detect_version_on_unknown_returns_none() -> None:
    """A non-BCF zip yields ``None`` from :func:`detect_version`."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "not bcf")
    assert bcf_xml.detect_version(buf.getvalue()) is None


def test_parse_non_zip_raises_bcfparseerror() -> None:
    """A payload that is not a ZIP raises :class:`BCFParseError`."""
    with pytest.raises(bcf_xml.BCFParseError):
        bcf_xml.parse_bcfzip(b"this is definitely not a zip file")


def test_parse_zip_without_markup_reports_error_not_raises() -> None:
    """A ZIP with no markup.bcf → structured error, no exception."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bcf.version", b'<?xml version="1.0"?><Version VersionId="3.0"/>')
        zf.writestr("random.txt", b"junk")
    result = bcf_xml.parse_bcfzip(buf.getvalue())
    assert result.has_errors
    assert any(i.code == "no_topics" for i in result.issues)
    assert result.topics == []


def test_parse_malformed_markup_xml_is_reported() -> None:
    """A topic dir whose markup.bcf is not well-formed XML is reported."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bcf.version", b'<?xml version="1.0"?><Version VersionId="2.1"/>')
        zf.writestr("abc/markup.bcf", b"<Markup><Topic Guid='x'>unclosed")
    result = bcf_xml.parse_bcfzip(buf.getvalue())
    assert result.has_errors
    assert any(i.code in ("markup_xml_error", "markup_invalid") for i in result.issues)


def test_version_mismatch_forced_parse() -> None:
    """A 2.1 archive can be force-parsed as 3.0 without crashing."""
    topic = _sample_topic()
    archive = bcf_xml.build_bcfzip(version="2.1", project_id="p", project_name="n", topics=[topic])
    result = bcf_xml.parse_bcfzip(archive, forced_version="3.0")
    assert result.detected_version == "3.0"
    assert not result.has_errors
    assert result.topics[0].guid == topic.guid
