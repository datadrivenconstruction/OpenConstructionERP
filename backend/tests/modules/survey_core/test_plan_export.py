# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The printed plan: DXF layers in grid metres, paper by market, the fitting scale and grid convergence."""

from __future__ import annotations

import io

import ezdxf
import pytest

from app.modules.survey_core.plan_export import (
    default_paper,
    dxf_layer_name,
    fit_scale,
    grid_convergence_deg,
    parse_layers,
    to_plan_dxf,
)

LAYERS = [
    {
        "id": "parcels",
        "aci": 3,
        "features": [
            {"kind": "polygon", "coords": [[389000, 5819060], [389040, 5819060], [389040, 5819100]], "label": "R-01"},
            {"kind": "line", "coords": [[0, 0]], "label": "too short"},
            {"kind": "blob", "coords": [[0, 0]]},
        ],
    },
    {"id": "control", "features": [{"kind": "point", "coords": [[389010.5, 5819020.25, 31.2]], "label": "CP1"}]},
]


def test_dxf_has_a_layer_per_plan_layer_in_grid_metres() -> None:
    data = to_plan_dxf(parse_layers(LAYERS), 500, ["Riverside", "SV-001 A", "1:500"])
    doc = ezdxf.read(io.StringIO(data.decode("utf-8")))
    names = {layer.dxf.name for layer in doc.layers}
    assert {"PLAN_PARCELS", "PLAN_CONTROL", "PLAN_TITLE"} <= names
    msp = doc.modelspace()
    poly = next(iter(msp.query("LWPOLYLINE")))
    assert poly.closed and poly.dxf.layer == "PLAN_PARCELS"
    assert [tuple(round(v, 3) for v in p[:2]) for p in poly.get_points()][0] == (389000.0, 5819060.0)
    point = next(iter(msp.query("POINT")))
    assert tuple(point.dxf.location) == pytest.approx((389010.5, 5819020.25, 31.2))
    # 2 mm on paper at 1:500 is 1 m on the ground.
    cp1 = next(t for t in msp.query("TEXT") if t.dxf.text == "CP1")
    assert cp1.dxf.height == pytest.approx(1.0)


def test_layer_names_are_cad_safe() -> None:
    assert dxf_layer_name("pointcloud heat") == "PLAN_POINTCLOUD_HEAT"
    assert dxf_layer_name("") == "PLAN_MISC"


def test_paper_follows_the_market() -> None:
    assert default_paper(["US"]) == "ANSI_B"
    assert default_paper(["DE"]) == "A3"
    assert default_paper(["*"]) == "A3"
    assert default_paper([], "CA") == "ANSI_B"


def test_fit_scale_picks_the_largest_scale_that_fits() -> None:
    # A3 frame: 420 - 40 - 60 = 320 mm wide, 257 mm high. 140 x 80 m fits at 1:500 (280 x 160 mm).
    assert fit_scale((140.0, 80.0), "A3") == 500
    assert fit_scale((170.0, 80.0), "A3") == 1000
    assert fit_scale((10.0, 10.0), "A3") == 100


def test_convergence_on_utm_33n() -> None:
    # East of the central meridian (15 E) in the north the convergence is positive.
    gamma = grid_convergence_deg(32633, 600000.0, 5819000.0)
    assert gamma is not None and 0.5 < gamma < 2.0
    assert grid_convergence_deg(32633, 500000.0, 5819000.0) == pytest.approx(0.0, abs=1e-6)
    assert grid_convergence_deg(None, 0, 0) is None
