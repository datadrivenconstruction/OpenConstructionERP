"""Worked numbers of the quick massing from a short brief.

A 4-storey office of 2,400 m2 GFA, generator sources (model_params.TYPOLOGY office: storey 3.6 m, band 6.0 m,
corridor 1.8 m): depth 2 x 6.0 + 1.8 = 13.8 m, footprint 600 m2, width 43.48 m, perimeter 114.56 m.
Slabs: ground 600 + 3 suspended x 600 = 2,400 m2 (= GFA), flat roof 600 m2. Height 14.4 m, external wall
114.56 x 14.4 = 1,649.61 m2. Grid 7.2 m (defaults_for): 7 x 2 bays, 8 x 3 = 24 columns a storey.
Standard quality prices at the reference band median (cost_benchmark_reference.json office/din276 p50,
3,100 EUR/m2): 7,440,000 EUR, inside p10..p90. Window ratio and durations have no source: null and flagged.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.design import quick

OFFICE = {"building_type": "office", "gfa_m2": 2400, "storeys": 4, "country": "DE", "quality": "standard"}


def _q(result: dict, code: str) -> float:
    return next(x["value"] for x in result["model"]["quantities"] if x["code"] == code)


def test_office_2400_m2_four_storeys_geometry():
    r = quick.build(OFFICE)
    assert r["issues"] == []
    m = r["model"]
    assert m["footprint"] == {"width_m": 43.48, "depth_m": 13.8, "area_m2": 600.0}
    assert [lv["elevation_m"] for lv in m["levels"]] == [0.0, 3.6, 7.2, 10.8]
    assert m["height_m"] == pytest.approx(14.4)
    assert m["grid"] == {"spacing_m": 7.2, "bays_x": 7, "bays_y": 2, "columns_per_storey": 24}
    assert _q(r, "slab_ground") + _q(r, "slab_suspended") == pytest.approx(2400.0)
    assert _q(r, "roof") == pytest.approx(600.0)
    assert _q(r, "wall_ext_length") == pytest.approx(458.23)
    assert _q(r, "wall_ext") == pytest.approx(1649.61)
    assert _q(r, "openings") is None  # no sourced window ratio
    assert _q(r, "columns") == 96
    assert _q(r, "lifts") == 1
    assert m["inputs"]["depth_m"]["provenance"]["formula"] == "2 × band + corridor"


def test_every_quantity_has_provenance_or_a_flag():
    for x in quick.build(OFFICE)["model"]["quantities"]:
        assert x["provenance"]["source"] in {"brief", "generator", "formula"} or x["flag"] == "source_missing"


def test_window_ratio_from_brief_gives_openings():
    r = quick.build({**OFFICE, "wwr": 0.4})
    assert _q(r, "openings") == pytest.approx(659.85)


def test_office_cost_is_median_band_and_inside_benchmark():
    r = quick.build(OFFICE)
    c = r["cost"]
    assert c["currency"] == "EUR"
    assert Decimal(c["total"]) == Decimal("7440000")
    assert Decimal(c["per_m2"]) == Decimal("3100")
    assert c["benchmark"]["within"] is True
    assert c["benchmark"]["low"] == "2200" and c["benchmark"]["high"] == "4300"
    assert sum(Decimal(line["amount"]) for line in c["lines"]) == Decimal("7440000")
    walls = next(line for line in c["lines"] if line["code"] == "330")
    assert walls["quantity"] == pytest.approx(1649.61) and walls["unit"] == "m2"
    assert "office/din276/330/p50" in walls["provenance"]["ref"]
    assert Decimal(walls["amount"]) == Decimal("420") * 2400


def test_quality_moves_along_band():
    low = quick.build({**OFFICE, "quality": "economy"})["cost"]
    high = quick.build({**OFFICE, "quality": "high"})["cost"]
    assert Decimal(low["per_m2"]) == Decimal("2200") and Decimal(high["per_m2"]) == Decimal("4300")


def test_other_currency_needs_a_confirmed_rate():
    r = quick.build({**OFFICE, "currency": "USD"})
    assert r["cost"]["total"] is None and r["cost"]["reason"] == "currency"
    r = quick.build({**OFFICE, "currency": "USD", "fx_rate": "1.10"})
    assert r["cost"]["currency"] == "USD"
    assert Decimal(r["cost"]["total"]) == Decimal("8184000.00")


def test_type_without_sourced_defaults_needs_them_in_the_brief():
    brief = {"building_type": "warehouse", "gfa_m2": 5000, "storeys": 1, "country": "DE"}
    assert {i["code"] for i in quick.check(brief)} == {"source_missing"}
    r = quick.build({**brief, "floor_height_m": 10, "depth_m": 50})
    assert r["model"]["footprint"] == {"width_m": 100.0, "depth_m": 50.0, "area_m2": 5000.0}
    assert r["model"]["grid"] is None
    assert r["cost"]["total"] is None and r["cost"]["reason"] == "no_band_type"
    assert r["generator"] is False


def test_schedule_durations_without_source_are_empty_and_flagged():
    s = quick.build(OFFICE)["schedule"]
    assert s["total_days"] is None and s["reason"] == "rate_missing"
    assert all(p["days"] is None and p["flag"] == "rate_missing" for p in s["phases"])


def test_suggestions_name_their_source():
    sug = {s["pointer"]: s for s in quick.build(OFFICE)["suggestions"]}
    assert sug["floor_height_m"]["value"] == 3.6
    assert sug["floor_height_m"]["provenance"]["source"] == "generator"
    assert sug["min_clear_height_m"]["provenance"]["ref"].endswith("design_massing.json")
    assert "floor_height_m" not in {s["pointer"] for s in quick.build({**OFFICE, "floor_height_m": 3.3})["suggestions"]}


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        ({"storeys": 4, "max_height_m": 12}, "height_over_limit"),
        ({"plot_area_m2": 500}, "footprint_over_plot"),
        ({"floor_height_m": 2.6, "slab_zone_m": 0.35}, "clear_height_below_minimum"),
        ({"gfa_m2": 160, "storeys": 4}, "storey_too_small"),
        ({"wwr": 1.5}, "wwr_invalid"),
        ({"building_type": "residential_single", "storeys": 5}, "storeys_over_type_max"),
        ({"building_type": "castle"}, "unknown_type"),
        ({"gfa_m2": -1}, "gfa_invalid"),
    ],
)
def test_implausible_briefs_are_flagged(patch, code):
    issues = quick.check({**OFFICE, **patch})
    assert code in {i["code"] for i in issues}


def test_clear_height_minimum_comes_from_country_data_only():
    # 2.6 m storey less a 0.35 m slab zone from the brief leaves 2.25 m: under DE 2.40 m (MBO par. 47); no country, no rule
    brief = {**OFFICE, "floor_height_m": 2.6, "slab_zone_m": 0.35}
    assert "clear_height_below_minimum" not in {i["code"] for i in quick.check({**brief, "country": "ZZ"})}
    assert "clear_height_below_minimum" not in {i["code"] for i in quick.check({**OFFICE, "floor_height_m": 2.6})}


def test_rule_in_registry_reports_issues():
    import asyncio

    from app.core.validation.engine import ValidationContext
    from app.modules.design.validators import BriefPlausible

    ctx = ValidationContext(data={"quick_brief": {**OFFICE, "plot_area_m2": 500}}, metadata={"locale": "en"})
    res = asyncio.run(BriefPlausible().validate(ctx))
    assert any(not r.passed for r in res)


def test_frontend_fixture_is_the_real_output():
    import json
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[4] / "frontend/src/modules/design/data/quickOffice.fixture.json"
    if not fixture.exists():
        pytest.skip("frontend tree not beside the backend")
    assert json.loads(fixture.read_text(encoding="utf-8")) == json.loads(json.dumps(quick.build(OFFICE)))


@pytest.mark.parametrize(
    "patch",
    [{"depth_m": 0}, {"depth_m": -5}, {"floor_height_m": -3}, {"grid_m": 0}, {"slab_zone_m": 4}, {"max_height_m": 0}],
)
def test_non_positive_dimensions_are_refused_not_divided_by(patch):
    r = quick.build({**OFFICE, **patch})
    assert r["model"] is None
    assert "value_invalid" in {i["code"] for i in r["issues"]}


@pytest.mark.parametrize("country", ["US", "AE", None])
def test_a_market_without_its_own_band_gets_no_price(country):
    brief = {k: v for k, v in {**OFFICE, "country": country, "currency": "USD", "fx_rate": "1.1"}.items() if v}
    cost = quick.build(brief)["cost"]
    assert cost["total"] is None and cost["reason"] == "no_band_market" and cost["flag"] == "source_missing"
    assert cost["lines"] == []
