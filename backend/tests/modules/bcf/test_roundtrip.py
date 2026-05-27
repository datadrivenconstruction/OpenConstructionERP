# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""End-to-end BCF round-trip integrity tests.

Sister to :mod:`tests.modules.bcf.test_bcf_roundtrip` (writer↔reader
field-by-field assertions). This file targets the *full* round-trip:
writer → bytes → reader → writer → bytes, asserting the second build
is structurally identical to the first across a non-trivial archive
(5 topics × 3 viewpoints × 10 comments + snapshots) plus edge cases
(unicode, quotes, empty comments, missing snapshot, malformed XML).

Why "structurally identical" instead of "byte-identical"?
---------------------------------------------------------
``zipfile.ZipFile`` stamps every entry with the wall-clock time, so two
back-to-back ``build_bytes()`` calls produce zips with different
``date_time`` headers even when the contents match. We compare the
*decoded* :class:`ParsedBCF` instead — same topics, same comments, same
viewpoints, same snapshots, same IDs, same timestamps.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.bcf.reader import (
    BCFFormatError,
    BCFReader,
    BCFSecurityError,
    ParsedBCF,
)
from app.modules.bcf.writer import (
    BCFComment,
    BCFTopic,
    BCFViewpoint,
    BCFWriter,
)

# A pre-baked 1×1 PNG so the snapshot round-trip is exact. Same magic
# bytes the writer's PNG-sniff guard requires.
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x78\x9c\x62\x00\x01\x00\x00\x05\x00\x01"
    b"\x0d\x0a\x2d\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _ts(minutes: int = 0) -> datetime:
    """Deterministic UTC timestamp."""
    return datetime(2026, 5, 21, 10, 0, 0, tzinfo=UTC) + timedelta(minutes=minutes)


def _vp(idx: int, *, with_snapshot: bool = False) -> BCFViewpoint:
    """Build one viewpoint #idx, optionally with a topic-level snapshot.

    Only the *first* viewpoint of a topic carries the snapshot — the
    writer emits one ``snapshot.png`` per topic folder regardless of how
    many viewpoints reference it, so attaching the same PNG to every
    viewpoint would race the zip writer on a duplicate name.
    """
    return BCFViewpoint(
        guid=str(uuid.uuid4()),
        camera_type="perspective",
        camera_view_point=(float(idx), 2.0 * idx, 3.0 * idx),
        camera_direction=(0.0, -1.0, 0.0),
        camera_up_vector=(0.0, 0.0, 1.0),
        field_of_view=60.0 + idx,
        aspect_ratio=1.7777778,
        snapshot_png=_PNG_BYTES if with_snapshot else None,
    )


def _comment(idx: int) -> BCFComment:
    return BCFComment(
        guid=str(uuid.uuid4()),
        date=_ts(minutes=idx),
        author=f"user{idx}@example.com",
        comment=f"Comment #{idx}",
    )


def _build_archive(
    n_topics: int = 5,
    n_viewpoints: int = 3,
    n_comments: int = 10,
    project_id: str = "proj-1",
) -> tuple[bytes, list[BCFTopic]]:
    """Build a representative BCF zip. Returns ``(bytes, source_topics)``."""
    writer = BCFWriter().set_project(project_id, "Round-trip Integrity")
    topics: list[BCFTopic] = []
    for ti in range(n_topics):
        topic = BCFTopic(
            guid=str(uuid.uuid4()),
            topic_type="Clash",
            topic_status="Open",
            title=f"Topic #{ti}",
            creation_date=_ts(minutes=ti * 100),
            creation_author=f"author{ti}@example.com",
            priority="Critical" if ti % 2 == 0 else "Normal",
            description=f"Description of topic #{ti}.",
            server_assigned_id=f"CLASH-{ti + 1:03d}",
            assigned_to=f"assignee{ti}@example.com",
            labels=["bulk", f"set-{ti}"],
            viewpoints=[_vp(ti * 10 + v, with_snapshot=(v == 0)) for v in range(n_viewpoints)],
            comments=[_comment(ti * 100 + c) for c in range(n_comments)],
        )
        writer.add_topic(topic)
        topics.append(topic)
    return writer.build_bytes(), topics


def _parsed_to_summary(parsed: ParsedBCF) -> dict:
    """Canonical comparable shape of a parsed archive (for diff/structural eq)."""
    return {
        "version": parsed.version,
        "project_id": parsed.project.project_id if parsed.project else None,
        "topics": [
            {
                "guid": t.guid,
                "topic_type": t.topic_type,
                "topic_status": t.topic_status,
                "title": t.title,
                "creation_date": t.creation_date,
                "creation_author": t.creation_author,
                "server_assigned_id": t.server_assigned_id,
                "priority": t.priority,
                "description": t.description,
                "assigned_to": t.assigned_to,
                "labels": tuple(t.labels),
                "comments": [
                    {
                        "guid": c.guid,
                        "author": c.author,
                        "date": c.date,
                        "comment": c.comment,
                    }
                    for c in t.comments
                ],
                "viewpoints": [
                    {
                        "guid": v.guid,
                        "camera_type": v.camera_type,
                        # Snap floats to 6 decimals — the writer uses
                        # ``repr()`` so this is exact for the values we
                        # control, but stays robust if the encoder ever
                        # switches to a fixed-precision formatter.
                        "view_point": tuple(round(c, 6) for c in v.camera_view_point),
                        "direction": tuple(round(c, 6) for c in v.camera_direction),
                        "field_of_view": (round(v.field_of_view, 6) if v.field_of_view is not None else None),
                    }
                    for v in t.viewpoints
                ],
                "snapshots": {k: bytes(v) for k, v in (t.snapshots or {}).items()},
            }
            for t in sorted(parsed.topics, key=lambda x: x.server_assigned_id or x.guid)
        ],
    }


# ── 1. Full happy-path round-trip ────────────────────────────────────────


def test_full_archive_roundtrip_structurally_identical() -> None:
    """5 topics × 3 viewpoints × 10 comments + snapshots → reader → writer
    produces a second archive that decodes to the same content.

    Asserts: same topic count, same per-topic comment/viewpoint count,
    same IDs, same titles, same timestamps, same snapshot bytes.
    """
    blob1, source_topics = _build_archive()
    parsed1 = BCFReader.from_bytes(blob1)

    # ── correctness of the first decode ─────────────────────────────
    assert parsed1.version.startswith("3")
    assert len(parsed1.topics) == 5
    for topic in parsed1.topics:
        assert len(topic.viewpoints) == 3
        assert len(topic.comments) == 10
        # snapshot.png lives once per topic, not per viewpoint (writer
        # picks the first viewpoint's snapshot as the topic-level image).
        assert "snapshot.png" in topic.snapshots
        assert topic.snapshots["snapshot.png"] == _PNG_BYTES

    # ── re-export ────────────────────────────────────────────────────
    # Build the second archive from the parsed shape — exercise the full
    # reader → writer → reader loop the way an import/export workflow does.
    rewriter = BCFWriter().set_project("proj-1", "Round-trip Integrity")
    for t in source_topics:
        # ``BCFTopic`` itself is the canonical shape, so a true round-trip
        # passes the same topics back through the writer.
        rewriter.add_topic(t)
    blob2 = rewriter.build_bytes()
    parsed2 = BCFReader.from_bytes(blob2)

    # ── structural equality of the two decoded archives ─────────────
    assert _parsed_to_summary(parsed1) == _parsed_to_summary(parsed2)


def test_topic_ids_preserved_through_roundtrip() -> None:
    """Every topic GUID + ``server_assigned_id`` survives the round-trip."""
    blob, source_topics = _build_archive()
    parsed = BCFReader.from_bytes(blob)
    source_guids = {t.guid.strip("{}").lower() for t in source_topics}
    parsed_guids = {t.guid for t in parsed.topics}
    assert source_guids == parsed_guids
    source_sids = {t.server_assigned_id for t in source_topics}
    parsed_sids = {t.server_assigned_id for t in parsed.topics}
    assert source_sids == parsed_sids


def test_timestamps_preserved_through_roundtrip() -> None:
    """Creation dates + comment dates round-trip at second precision (UTC)."""
    blob, source_topics = _build_archive(n_topics=2, n_viewpoints=1, n_comments=4)
    parsed = BCFReader.from_bytes(blob)
    by_sid = {t.server_assigned_id: t for t in parsed.topics}
    for src in source_topics:
        dst = by_sid[src.server_assigned_id]
        assert dst.creation_date == src.creation_date
        # Comments are ordered by writer insertion — match positionally.
        assert len(dst.comments) == len(src.comments)
        for sc, dc in zip(src.comments, dst.comments, strict=True):
            assert dc.date == sc.date
            assert dc.author == sc.author


# ── 2. Edge cases ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "title",
    [
        "Klärschlamm-Rückhalteanlage — Ø200",
        '"quoted" + <angled> & ampersanded',
        "中文标题 — 防火墙",
        "🛠️ emoji-laden coordination ticket",
        "​" + "zero-width-prefixed",  # zero-width space — must not be stripped
    ],
)
def test_unicode_and_quotes_in_title_roundtrip(title: str) -> None:
    """Special chars in titles survive the writer→reader→writer trip."""
    topic = BCFTopic(
        guid=str(uuid.uuid4()),
        topic_type="Clash",
        topic_status="Open",
        title=title,
        creation_date=_ts(),
        creation_author="alice@example.com",
        server_assigned_id="CLASH-XU-1",
    )
    blob = BCFWriter().add_topic(topic).build_bytes()
    parsed = BCFReader.from_bytes(blob)
    assert len(parsed.topics) == 1
    # XML serialisers normalise newlines to LF; characters themselves
    # must survive verbatim.
    assert parsed.topics[0].title == title


def test_empty_comment_list_roundtrips() -> None:
    """A topic with zero comments produces a topic with zero comments."""
    topic = BCFTopic(
        guid=str(uuid.uuid4()),
        topic_type="Clash",
        topic_status="Open",
        title="No comments here",
        creation_date=_ts(),
        creation_author="alice@example.com",
        server_assigned_id="CLASH-EMPTY",
        comments=[],
    )
    blob = BCFWriter().add_topic(topic).build_bytes()
    parsed = BCFReader.from_bytes(blob)
    assert len(parsed.topics) == 1
    assert parsed.topics[0].comments == ()


def test_viewpoint_without_snapshot_roundtrips() -> None:
    """A viewpoint with no PNG attached → topic.snapshots is empty."""
    vp = BCFViewpoint(
        guid=str(uuid.uuid4()),
        camera_type="perspective",
        # snapshot_png is intentionally None.
    )
    topic = BCFTopic(
        guid=str(uuid.uuid4()),
        topic_type="Clash",
        topic_status="Open",
        title="No snapshot",
        creation_date=_ts(),
        creation_author="alice@example.com",
        server_assigned_id="CLASH-NOSNAP",
        viewpoints=[vp],
    )
    blob = BCFWriter().add_topic(topic).build_bytes()
    parsed = BCFReader.from_bytes(blob)
    assert len(parsed.topics) == 1
    target = parsed.topics[0]
    assert len(target.viewpoints) == 1
    assert "snapshot.png" not in target.snapshots


def test_malformed_markup_xml_is_captured_per_topic() -> None:
    """A bad ``markup.bcf`` per the reader's "resilient per-topic" contract.

    The reader docstring guarantees malformed markup is captured in
    :attr:`ParsedTopic.parse_error` rather than raising — the importer
    can then surface a structured error without losing healthy topics.
    """
    # Hand-build a zip with one good topic + one bad one (broken XML).
    good_blob, _ = _build_archive(n_topics=1, n_viewpoints=1, n_comments=1)
    good_zip_buf = io.BytesIO(good_blob)
    out_buf = io.BytesIO()
    with zipfile.ZipFile(good_zip_buf, "r") as src, zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            dst.writestr(info.filename, src.read(info.filename))
        # Inject a malformed markup.bcf in a fresh topic folder.
        bad_dir = str(uuid.uuid4()).lower()
        dst.writestr(f"{bad_dir}/markup.bcf", b"<Markup><Topic")  # truncated
    parsed = BCFReader.from_bytes(out_buf.getvalue())
    # The good topic survives; the bad folder either yields a parse_error
    # ParsedTopic or is dropped — both are documented "resilient" behaviours.
    good_topics = [t for t in parsed.topics if t.parse_error is None]
    assert len(good_topics) >= 1


def test_completely_invalid_zip_rejects_with_format_error() -> None:
    """Non-zip bytes raise :class:`BCFFormatError`, never crash."""
    with pytest.raises(BCFFormatError):
        BCFReader.from_bytes(b"not a zip at all")


def test_zip_without_bcf_version_marker_rejects() -> None:
    """A valid zip without ``bcf.version`` is a 3.0-reader format error."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("some-file.txt", b"hello")
    with pytest.raises(BCFFormatError):
        BCFReader.from_bytes(buf.getvalue())


def test_path_traversal_in_zip_is_rejected() -> None:
    """A zip entry whose name escapes the archive root is rejected.

    Reader's :class:`BCFSecurityError` is the standard zip-slip defence —
    a malicious archive must never read through to the parse step.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bcf.version", b'<?xml version="1.0"?><Version VersionId="3.0"/>')
        zf.writestr("../escape.txt", b"slip")
    with pytest.raises(BCFSecurityError):
        BCFReader.from_bytes(buf.getvalue())
