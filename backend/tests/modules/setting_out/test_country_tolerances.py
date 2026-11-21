# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Country tolerance data: every value names its source, and only its market sees it.

Covers ``core/country_data/site_tolerances.json`` (setting-out and monitoring profiles) and
``core/country_data/survey_tolerances.json`` (closure and corner classes).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.modules.monitoring import profiles as mon
from app.modules.setting_out import tolerances as tol
from app.modules.setting_out.service import tolerance_reference

DATA = Path(__file__).resolve().parents[3] / "app" / "core" / "country_data"
SITE = json.loads((DATA / "site_tolerances.json").read_text(encoding="utf-8"))
SURVEY = json.loads((DATA / "survey_tolerances.json").read_text(encoding="utf-8"))
COURSE = json.loads(
    (DATA.parent.parent / "modules" / "setting_out" / "demo" / "riverside" / "expected.json").read_text(
        encoding="utf-8"
    )
)["setting_out"]["country_profiles"]
STATUSES = {"verified", "to_verify"}


@pytest.fixture
def loaded() -> Iterator[None]:
    tol.clear_pack_tolerances()
    mon.clear_pack_profiles()
    tol.load_country_tolerances()
    mon.load_country_profiles()
    yield
    # Leave the registry as startup left it, for the API tests of the same process.
    tol.clear_pack_tolerances()
    mon.clear_pack_profiles()
    tol.load_country_tolerances()
    mon.load_country_profiles()


def test_every_setting_out_value_names_clause_edition_and_status(loaded: None) -> None:
    profiles = [p for c in SITE if not c.startswith("_") for p in tol.pack_profiles_for([c])]
    assert len(profiles) >= 8
    for p in profiles:
        assert p.key.startswith("pack:") and p.source == "pack" and p.country
        assert p.edition and p.reference.endswith(p.edition), p.key
        assert p.items, p.key
        for item, value in p.items.items():
            assert item in (*tol.ITEM_TYPES, "default"), (p.key, item)
            assert value.h_mm > 0 and value.clause and value.status in STATUSES, (p.key, item)


def test_every_monitoring_profile_names_clause_edition_and_status(loaded: None) -> None:
    profiles = [p for c in SITE if not c.startswith("_") for p in mon.pack_profiles_for([c])]
    assert {p.country for p in profiles} >= {"CN", "RU"}
    for p in profiles:
        assert p.edition and p.clause and p.status in STATUSES, p.key
        assert not p.thresholds.is_empty(), p.key


def test_every_closure_and_corner_class_names_source_edition_and_status() -> None:
    rows = [
        r
        for country, entry in SURVEY.items()
        if not country.startswith("_")
        for kind in ("closure_classes", "corner_classes")
        for r in entry.get(kind, [])
    ]
    assert len(rows) >= 15
    for r in rows:
        assert r["source"] and r["edition"] and r["status"] in STATUSES, r["key"]


def test_profiles_show_only_for_their_market(loaded: None) -> None:
    assert tol.pack_profiles_for(["*"]) == []
    assert mon.pack_profiles_for(["*"]) == []
    assert {p.key for p in tol.pack_profiles_for(["CN"])} == {"pack:cn_gb50204_2015"}
    assert all(p.country == "DE" for p in tol.pack_profiles_for(["DE"]))
    assert tol.builtin_profile("pack:cn_gb50204_2015", ["US"]) is None


def test_shared_european_profile_is_cited_per_country(loaded: None) -> None:
    names = {c: [p.name for p in tol.pack_profiles_for([c]) if p.key.endswith("_en_execution")] for c in ("DE", "FR")}
    assert names == {"DE": ["DIN EN 13670 / DIN EN 1090-2"], "FR": ["NF EN 13670 / NF EN 1090-2"]}


@pytest.mark.parametrize("country", ["CN", "US", "GB"])
def test_course_country_profiles(loaded: None, country: str) -> None:
    want = COURSE[country]
    profile = tol.builtin_profile(want["key"], [country])
    assert profile is not None and profile.edition == want["edition"]
    value = profile.for_item(want["item"])
    assert value is not None
    assert (value.h_mm, value.v_mm, value.status) == (want["h_mm"], want.get("v_mm"), want["status"])
    ref = tolerance_reference(profile, value)
    assert want["edition"] in ref and value.clause in ref and value.status in ref


def test_demo_reference_is_the_label_alone() -> None:
    value = tol.DEMO_PROFILE.for_item("column")
    assert tolerance_reference(tol.DEMO_PROFILE, value) == "Demo values, not a standard"


def test_din_18202_plan_tolerance_cites_table_1_not_the_angle_table(loaded: None) -> None:
    # DIN 18202:2019 Table 1 (limit deviations for dimensions) gives 20 mm for plan lengths over 6 to 15 m;
    # Table 2 is angular deviations and Table 3 flatness, so neither may be cited for a plan length.
    profile = tol.builtin_profile("pack:de_din18202_2019", ["DE"])
    assert profile is not None
    for item in ("grid_line", "default"):
        value = profile.for_item(item)
        assert value is not None and value.h_mm == 20
        assert "Table 1 row 1" in value.clause and "Table 2" not in value.clause
