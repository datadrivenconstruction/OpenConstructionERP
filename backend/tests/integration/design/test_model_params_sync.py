"""The model panel's copy of the generator limits matches the editor sources it was taken from.

tools/overlay.py copies rules.json and spec.rs into generator/ beside the tests; without them it skips."""

import json
import re
from pathlib import Path

import pytest

from app.modules.design import model_params as mp

GEN = Path(__file__).resolve().parent / "generator"
RULES, SPEC = GEN / "rules.json", GEN / "spec.rs"
pytestmark = pytest.mark.skipif(not (RULES.exists() and SPEC.exists()), reason="generator sources not copied")

RUST_TYPOLOGY = {"House": "house", "ApartmentSection": "apartment_section", "Office": "office", "School": "school"}
FLOORS_RULE = {
    "house": "massing.floors_max_house",
    "school": "massing.floors_max_school",
    "apartment_section": "massing.floors_max_tall",
    "office": "massing.floors_max_tall",
}
MAX_STOREYS = 200  # crates/gen/src/project/mod.rs slots::MAX_STOREYS


@pytest.fixture(scope="module")
def rules() -> dict:
    return {r["id"]: r for r in json.loads(RULES.read_text(encoding="utf-8"))["rules"]}


@pytest.fixture(scope="module")
def spec() -> str:
    return SPEC.read_text(encoding="utf-8")


def test_typology_defaults_match_spec_rs(spec):
    body = spec[spec.index("fn defaults(t: Typology)") :]
    for rust, typ in RUST_TYPOLOGY.items():
        block = re.search(rf"Typology::{rust} => Defaults \{{(.*?)\}}", body, re.S).group(1)
        got = {k: float(v) for k, v in re.findall(r"(height|band|corridor): ([\d.]+)", block)}
        _, height, band, corridor = mp.TYPOLOGY[typ]
        assert (height, band, corridor) == (got["height"], got["band"], got["corridor"]), typ


def test_max_floors_match_rules(rules):
    for typ, rule in FLOORS_RULE.items():
        assert mp.TYPOLOGY[typ][0] == min(int(rules[rule]["default"]), MAX_STOREYS), typ


def test_param_ranges_match_rules(rules):
    by_id = {p.id: p for p in mp.params_for({}, "apartment_section")}
    for pid, rule in (
        ("floor_height", "massing.floor_height"),
        ("width", "massing.width"),
        ("grid", "grid.span"),
        ("roof_slope", "massing.roof_slope"),
    ):
        assert (by_id[pid].min, by_id[pid].max) == (rules[rule]["min"], rules[rule]["max"]), pid
    assert mp.defaults_for("office", 4)["/structure/grid_m"] == rules["grid.span"]["default"]
    assert mp.defaults_for("office", 4)["/envelope/roof_slope_deg"] == rules["massing.roof_slope"]["default"]
    assert rules["depth.band"]["min"] == mp.BAND_MIN


def test_apartment_cap_matches_rules_and_spec_rs(rules, spec):
    r = rules["room.apartments_max"]
    assert (r["default"], r["max"]) == (mp.APARTMENTS_DEFAULT, mp.APARTMENTS_TOP)
    assert rules["room.apartment_frontage"]["default"] == mp.APARTMENT_FRONTAGE
    assert re.search(r"const HALL_MAX: f64 = ([\d.]+);", spec).group(1) == f"{mp.HALL_MAX:g}.0"
    assert "let sides = 2.0;" in spec  # flats on both sides of the corridor
    assert mp.apartments_cap({"massing": {"footprint": {"width_m": 34}}}) == 12
    assert mp.apartments_cap({"massing": {"footprint": {"width_m": 9}}}) == 2
    assert mp.apartments_cap({"massing": {"footprint": {"width_m": 200}}}) == 80
    assert mp.apartments_cap({}) == 12


def test_roof_choices_are_ones_the_generator_reads(spec):
    for roof in mp.params_for({}, "office")[-2].options:
        assert f'Some("{roof}")' in spec, roof
