# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Riverside Yard geodesy block: 100.000 m on the ground is 99.975 m on the UTM 33N grid.

The course shows the projection scale, the elevation factor and their product at the site, and why a
setting-out crew working in grid coordinates must not tape ground distances unchanged (25.4 mm per 100 m).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("pyproj")

from app.modules.survey_core import geodesy  # noqa: E402

EXPECTED = json.loads(
    (
        Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside" / "expected.json"
    ).read_text(encoding="utf-8")
)
GEO = EXPECTED["geodesy"]


def test_block_matches_the_project_crs() -> None:
    assert GEO["epsg"] == EXPECTED["crs"]["epsg"]


def test_combined_scale_factor_at_the_site() -> None:
    site = GEO["site"]
    sf = geodesy.combined_scale_factor(GEO["epsg"], site["e"], site["n"], site["height_m"])
    assert sf.k == pytest.approx(GEO["projection_scale_k"], abs=5e-7)
    assert sf.elevation_factor == pytest.approx(GEO["elevation_factor"], abs=5e-8)
    assert sf.csf == pytest.approx(GEO["combined_scale_factor"], abs=5e-8)


def test_ground_to_grid_differs_at_the_millimetre_level() -> None:
    site = GEO["site"]
    sf = geodesy.combined_scale_factor(GEO["epsg"], site["e"], site["n"], site["height_m"])
    grid = sf.grid_from_ground(GEO["ground_m"])
    assert round(grid, 3) == GEO["grid_m"]
    assert round(geodesy.ground_grid_difference_mm(sf.csf, GEO["ground_m"]), 1) == GEO["difference_mm"]
    assert round(grid, 3) != GEO["ground_m"]


def test_elevation_factor_alone_is_below_a_millimetre_per_100_m() -> None:
    # 34.3 m above the ellipsoid shrinks 100 m by 0.54 mm; the projection scale does the rest.
    assert (1 - geodesy.elevation_factor(GEO["site"]["height_m"])) * 100_000 == pytest.approx(0.54, abs=0.01)
