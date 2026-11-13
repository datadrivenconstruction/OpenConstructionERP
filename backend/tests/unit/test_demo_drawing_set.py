"""The demo drawing set parses through the DWG Takeoff path and stays coherent."""

import pytest

pytest.importorskip("ezdxf")

from app.modules.dwg_takeoff.dxf_processor import parse_dxf  # noqa: E402
from app.scripts.demo_drawing_set import TYPES, build_drawing_set, floor_rooms, opening_counts  # noqa: E402


@pytest.fixture(scope="module")
def parsed(tmp_path_factory: pytest.TempPathFactory) -> dict:
    path = tmp_path_factory.mktemp("set") / "set.dxf"
    build_drawing_set(str(path))
    assert path.stat().st_size < 5_000_000
    return parse_dxf(str(path))


def test_set_has_eight_titled_sheets(parsed: dict) -> None:
    texts = {e["geometry_data"].get("text") for e in parsed["entities"] if e["entity_type"] == "TEXT"}
    for number in ("A-001", "A-101", "A-102", "A-103", "A-201", "A-301", "A-302", "A-501"):
        assert number in texts
    assert parsed["units"] == "mm"


def test_layers_are_architectural(parsed: dict) -> None:
    names = {layer["name"] for layer in parsed["layers"]}
    assert {"A-WALL", "A-DOOR", "A-GLAZ", "A-FURN", "A-DIMS", "A-GRID", "A-ANNO-TEXT", "A-AREA"} <= names


def test_blocks_travel_with_their_inserts(parsed: dict) -> None:
    blocks = {e.get("block") for e in parsed["entities"] if e.get("block")}
    assert {"FURN_BED_DOUBLE", "FIXT_WC", "SYMB_NORTH"} <= blocks


def test_schedule_counts_every_opening_type() -> None:
    counts = opening_counts()
    assert set(counts) == set(TYPES)
    assert counts["D1"] == 1  # one building entrance
    assert counts["D2"] == 6  # one per apartment


def test_rooms_have_plausible_areas() -> None:
    for name, x0, y0, x1, y1 in floor_rooms():
        area = (x1 - x0) * (y1 - y0) / 1e6
        assert 5 < area < 45, name
