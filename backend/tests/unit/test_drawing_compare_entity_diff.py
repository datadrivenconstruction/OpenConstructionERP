# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Entity-level diff of two DWG/DXF revisions and its clustering into regions."""

from __future__ import annotations

import base64

from app.modules.drawing_compare.entity_diff import cluster_entity_changes, diff_entities
from app.modules.drawing_compare.geometry import Rect
from app.modules.drawing_compare.thumbnail import records_in, region_svg


def _line(x1: float, y1: float, x2: float, y2: float, layer: str = "A-WALL") -> dict:
    return {
        "entity_type": "LINE",
        "layer": layer,
        "color": "#ffffff",
        "geometry_data": {"start": {"x": x1, "y": y1}, "end": {"x": x2, "y": y2}},
    }


def _text(x: float, y: float, value: str, layer: str = "A-DIMS") -> dict:
    return {
        "entity_type": "TEXT",
        "layer": layer,
        "geometry_data": {"insert": {"x": x, "y": y}, "text": value, "height": 2.5, "font": "arial"},
    }


def _base() -> list[dict]:
    # A 10 x 10 m room plus a dimension text; a far-away frame line fixes the extent.
    return [
        _line(0, 0, 10000, 0),
        _line(10000, 0, 10000, 10000),
        _line(10000, 10000, 0, 10000),
        _line(0, 10000, 0, 0),
        _text(5000, -500, "10000"),
        _line(-50000, -50000, 50000, -50000, layer="FRAME"),
    ]


def test_identical_revisions_have_no_changes() -> None:
    result = diff_entities(_base(), _base())
    assert result.changes == []
    assert result.unchanged == 6
    assert result.counts() == {"added": 0, "removed": 0, "modified": 0, "unchanged": 6}


def test_export_round_off_and_presentation_keys_do_not_count() -> None:
    new = _base()
    new[0]["geometry_data"]["end"]["x"] = 10000.0000004
    new[0]["color"] = "#ff0000"
    new[4]["geometry_data"]["font"] = "romans"
    result = diff_entities(_base(), new)
    assert result.changes == []


def test_added_removed_and_modified_are_told_apart() -> None:
    old = _base()
    new = _base()
    new.append(_line(4000, 0, 4000, 10000))  # a new partition wall
    del new[1]  # the east wall is gone ...
    new.append(_line(12000, 0, 12000, 10000))  # ... and rebuilt 2 m further east
    new[3] = _text(5000, -500, "12000")  # the dimension follows
    result = diff_entities(old, new)
    counts = result.counts()
    assert counts["unchanged"] == 4
    modified = [c for c in result.changes if c.change == "modified"]
    assert len(modified) == 1
    assert (modified[0].old_text, modified[0].new_text) == ("10000", "12000")
    assert counts["added"] == 2
    assert counts["removed"] == 1
    removed = next(c for c in result.changes if c.change == "removed")
    assert removed.layer == "A-WALL"
    by_layer = {(r["layer"], r["entity_type"]): r for r in result.by_layer()}
    assert by_layer[("A-WALL", "LINE")] == {
        "layer": "A-WALL",
        "entity_type": "LINE",
        "added": 2,
        "removed": 1,
        "modified": 0,
    }
    assert by_layer[("A-DIMS", "TEXT")]["modified"] == 1


def test_moved_endpoint_reads_as_modified_not_add_remove() -> None:
    new = _base()
    new[0] = _line(0, 0, 10300, 0)  # same start, end stretched
    result = diff_entities(_base(), new)
    assert [c.change for c in result.changes] == ["modified"]


def test_duplicates_pair_off_one_by_one() -> None:
    old = [*_base(), _line(1, 1, 2, 2), _line(1, 1, 2, 2)]
    new = [*_base(), _line(1, 1, 2, 2)]
    result = diff_entities(old, new)
    assert result.counts()["removed"] == 1
    assert result.counts()["unchanged"] == 7


def test_records_without_entity_type_are_ignored() -> None:
    result = diff_entities([{"foo": 1}, "x", None], [_line(0, 0, 1, 1)])
    assert result.old_total == 0
    assert result.counts()["added"] == 1


def test_cluster_merges_nearby_changes_and_classifies_regions() -> None:
    old = _base()
    new = _base()
    new.append(_line(4000, 0, 4000, 10000))
    new.append(_line(4200, 0, 4200, 10000))  # wall pair 200 apart -> one region
    new[4] = _text(5000, -500, "12000")
    new.append(_line(-45000, -45000, -44000, -45000, layer="NOTES"))
    result = diff_entities(old, new)
    regions = cluster_entity_changes(result.changes, gap=600)
    kinds = sorted(r.kind for r in regions)
    assert kinds == ["added", "added", "text"]
    walls = next(r for r in regions if r.counts["added"] == 2)
    assert walls.layer == "A-WALL"
    assert walls.box.x == 4000 and walls.box.w == 200
    text = next(r for r in regions if r.kind == "text")
    assert (text.old_text, text.new_text) == ("10000", "12000")
    # Regions with most entities come first.
    assert regions[0] is walls


def test_cluster_mixed_region_reads_modified_and_min_size_pads_points() -> None:
    old = [*_base(), _line(100, 100, 100, 100)]
    new = [*_base(), _line(3000, 3000, 3000, 3000)]
    result = diff_entities(old, new, match_radius=1)
    regions = cluster_entity_changes(result.changes, gap=10_000, min_size=50)
    assert len(regions) == 1
    assert regions[0].kind == "modified"
    tiny = cluster_entity_changes(diff_entities(_base(), [*_base(), _line(7, 7, 7, 7)]).changes, gap=1, min_size=50)
    assert tiny[0].box.w == 50 and tiny[0].box.h == 50


def test_region_svg_draws_old_red_new_blue() -> None:
    region = Rect(0, 0, 10000, 10000)
    url = region_svg(region, context=_base(), old=[_line(0, 0, 10, 10)], new=[_text(5, 5, "X")])
    assert url.startswith("data:image/svg+xml;base64,")
    svg = base64.b64decode(url.split(",", 1)[1]).decode()
    assert "#dc2626" in svg and "#2563eb" in svg and "#9ca3af" in svg
    assert len(records_in(_base(), Rect(9000, 9000, 2000, 2000))) == 2
