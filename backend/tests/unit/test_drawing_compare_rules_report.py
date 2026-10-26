# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rule set ``drawing_compare`` and the printable change report."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.drawing_compare.geometry import Rect
from app.modules.drawing_compare.pdf_export import build_change_report_pdf, thumbnail_flowable
from app.modules.drawing_compare.thumbnail import region_svg
from app.modules.drawing_compare.validators import (
    AlignmentPlausible,
    ChangesTriaged,
    DistinctRevisions,
    RegionsOnSheet,
    RelevantChangesFollowedUp,
)


def _ctx(comparison: dict, changes: list[dict] | None = None) -> ValidationContext:
    return ValidationContext(data={"comparison": comparison, "changes": changes or []}, project_id="p1")


_PDF = {
    "id": "c1",
    "source_kind": "pdf",
    "old_ref_id": "a",
    "new_ref_id": "b",
    "old_page": 1,
    "new_page": 1,
    "page_width": 1000.0,
    "page_height": 700.0,
    "alignment": {"method": "auto", "matrix": [1, 0, 0, 1, 0, 0], "confidence": 0.9},
}


@pytest.mark.asyncio
async def test_distinct_revisions() -> None:
    ok = await DistinctRevisions().validate(_ctx(_PDF))
    assert ok[0].passed
    same = await DistinctRevisions().validate(_ctx({**_PDF, "new_ref_id": "a"}))
    assert not same[0].passed and same[0].suggestion
    # Same document, another page, is a legitimate compare.
    pages = await DistinctRevisions().validate(_ctx({**_PDF, "new_ref_id": "a", "new_page": 2}))
    assert pages[0].passed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("alignment", "passes"),
    [
        ({"method": "auto", "matrix": [1, 0, 0, 1, 5, 5], "confidence": 0.9}, True),
        ({"method": "auto", "matrix": [1, 0, 0, 1, 5, 5], "confidence": 0.2}, False),
        ({"method": "manual", "matrix": [1, 0, 0, 1, 0, 0], "points_old": [[0, 0]], "points_new": [[0, 0]]}, False),
        ({"method": "none", "matrix": [3, 0, 0, 3, 0, 0]}, False),
        ({"method": "none", "matrix": [0, 0, 0, 0, 0, 0]}, False),
        ({"method": "none"}, False),
    ],
)
async def test_alignment_plausible(alignment: dict, passes: bool) -> None:
    results = await AlignmentPlausible().validate(_ctx({**_PDF, "alignment": alignment}))
    assert all(r.passed for r in results) is passes


@pytest.mark.asyncio
async def test_alignment_not_checked_for_dwg() -> None:
    results = await AlignmentPlausible().validate(_ctx({**_PDF, "source_kind": "dwg", "alignment": {}}))
    assert results[0].passed


@pytest.mark.asyncio
async def test_regions_on_sheet() -> None:
    good = {"id": "r1", "seq": 1, "x": 10, "y": 10, "w": 50, "h": 20}
    edge = {"id": "r2", "seq": 2, "x": 990, "y": 690, "w": 15, "h": 12}  # inside 1% tolerance
    off = {"id": "r3", "seq": 3, "x": 980, "y": 10, "w": 100, "h": 10}
    empty = {"id": "r4", "seq": 4, "x": 5, "y": 5, "w": 0, "h": 0}
    results = await RegionsOnSheet().validate(_ctx(_PDF, [good, edge]))
    assert [r.passed for r in results] == [True]
    results = await RegionsOnSheet().validate(_ctx(_PDF, [good, off, empty]))
    assert sorted(r.element_ref for r in results if not r.passed) == ["r3", "r4"]
    # DWG regions are in drawing units with no sheet to fall off.
    results = await RegionsOnSheet().validate(_ctx({**_PDF, "source_kind": "dwg"}, [off]))
    assert results[0].passed


@pytest.mark.asyncio
async def test_triage_and_follow_up() -> None:
    changes = [
        {"id": "a", "seq": 1, "status": "open"},
        {"id": "b", "seq": 2, "status": "relevant"},
        {"id": "c", "seq": 3, "status": "relevant", "rfi_id": "x"},
        {"id": "d", "seq": 4, "status": "not_relevant"},
        {"id": "e", "seq": 5, "status": "relevant", "comment": "  "},
    ]
    triage = await ChangesTriaged().validate(_ctx(_PDF, changes))
    assert not triage[0].passed and triage[0].details["open"] == [1]
    follow = await RelevantChangesFollowedUp().validate(_ctx(_PDF, changes))
    assert sorted(r.element_ref for r in follow) == ["b", "e"]
    done = [{"id": "a", "seq": 1, "status": "relevant", "flagged_at": datetime.now(UTC)}]
    assert (await ChangesTriaged().validate(_ctx(_PDF, done)))[0].passed
    assert (await RelevantChangesFollowedUp().validate(_ctx(_PDF, done)))[0].passed


def _change(seq: int, **kw: object) -> SimpleNamespace:
    base = {
        "seq": seq,
        "kind": "modified",
        "page": 1,
        "x": 10.0,
        "y": 20.0,
        "w": 30.0,
        "h": 40.0,
        "old_text": None,
        "new_text": None,
        "layer": None,
        "details": {},
        "thumbnail": None,
        "status": "open",
        "comment": None,
        "rfi_id": None,
        "markup_id": None,
        "flagged_at": None,
        "flagged_measurement_ids": [],
        "flagged_annotation_ids": [],
        "flagged_position_ids": [],
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _comparison(**kw: object) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "name": "A-101 C / B",
        "source_kind": "pdf",
        "old_label": "A-101.pdf",
        "new_label": "A-101 rev C.pdf",
        "old_revision": "B",
        "new_revision": "C",
        "old_page": 1,
        "new_page": 1,
        "alignment": {"method": "auto", "confidence": 0.82},
        "summary": {"total": 2, "added": 1, "modified": 0, "removed": 0, "text": 1},
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_report_renders_with_every_follow_up_and_thumbnail_kind() -> None:
    svg = region_svg(
        Rect(0, 0, 100, 100),
        context=[],
        old=[],
        new=[
            {
                "entity_type": "LINE",
                "layer": "0",
                "geometry_data": {"start": {"x": 0, "y": 0}, "end": {"x": 90, "y": 90}},
            }
        ],
    )
    changes = [
        _change(1, kind="added", thumbnail=svg, status="relevant", rfi_id="r1", markup_id="m1", comment="Wall moved"),
        _change(
            2,
            kind="text",
            old_text="3200",
            new_text="3400",
            status="relevant",
            flagged_at=datetime.now(UTC),
            flagged_measurement_ids=["a", "b"],
            flagged_position_ids=["p"],
            thumbnail="data:image/png;base64,iVBORw0KGgo=",
        ),
        _change(3, kind="modified", layer="A-WALL", details={"counts": {"added": 2, "removed": 1, "modified": 0}}),
    ]
    pdf = build_change_report_pdf(_comparison(), changes, project_name="Tower", rfi_numbers={"r1": "RFI-007"})
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1500


def test_report_without_changes_and_dwg_side_labels() -> None:
    pdf = build_change_report_pdf(_comparison(source_kind="dwg", alignment={"method": "none"}), [])
    assert pdf.startswith(b"%PDF")


def test_thumbnail_flowable_tolerates_garbage() -> None:
    assert thumbnail_flowable(None) == ""
    assert thumbnail_flowable("not a data url") == ""
    assert thumbnail_flowable("data:image/jpeg;base64," + base64.b64encode(b"nope").decode()) == ""
