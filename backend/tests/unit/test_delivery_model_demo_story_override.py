"""Demo story override of the delivery model seeder: pure merge/validation and the shipped Ludwigsburg file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.delivery_model import seed

REPO = Path(__file__).resolve().parents[3]
PACK = REPO / "packs/eleven-areas-framework/src/openconstructionerp_eleven_areas_framework"
STORY_FILE = PACK / "demo/school-ludwigsburg-delivery_model.json"
FORMS_FILE = PACK / "catalogues/delivery_forms/eleven_areas_framework.json"


@pytest.fixture(scope="module")
def shipped() -> dict:
    return json.loads(STORY_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def catalogue() -> dict:
    return json.loads(FORMS_FILE.read_text(encoding="utf-8"))


def test_no_story_changes_nothing() -> None:
    assert seed.resolve_story(None) == {}
    assert seed.resolve_story({}) == {}


def test_forms_to_compare_default_and_preferred() -> None:
    have = ["a", "design_bid_build_single", "design_build", "cm_at_risk", "z"]
    assert seed.forms_to_compare(have) == ["design_bid_build_single", "design_build", "cm_at_risk"]
    assert seed.forms_to_compare(have, ["z", "unknown", "a"]) == ["z", "a", "design_bid_build_single"]


def test_item_dates_follow_offsets() -> None:
    from datetime import date

    today = date(2026, 1, 1)
    default = seed.item_dates(today, pre_construction=True)
    moved = seed.item_dates(today, pre_construction=True, award=seed.AWARD + 5, start=seed.START + 5)
    assert (moved["package_need"] - default["package_need"]).days == 5
    assert (moved["switchboard_need"] - default["switchboard_need"]).days == 5


def test_malformed_keys_are_ignored() -> None:
    story = {
        "forms": [],
        "rationales": {"x": ""},
        "owner_capability": {"public_client": "yes"},
        "risks": ["ok", 3],
        "ground_rationale": "",
        "ofi_first": {"description": "x", "item_kind": "gadget", "lead_time_days": 5},
        "ofi_second": {"description": "x"},
        "plant_item": "",
        "award_days": -4,
        "start_days": True,
    }
    assert seed.resolve_story(story) == {}


def test_owner_capability_is_merged_over_the_default() -> None:
    out = seed.resolve_story({"owner_capability": {"public_client": True}})
    assert out["owner_capability"]["public_client"] is True
    assert out["owner_capability"]["funding_source"] == seed.OWNER_CAPABILITY["funding_source"]


def test_language_map_follows_locale() -> None:
    story = {"rationales": {"design_build": {"en": "english", "de": "deutsch"}}}
    assert seed.resolve_story(story, "de")["rationales"]["design_build"] == "deutsch"
    assert seed.resolve_story(story, "fr")["rationales"]["design_build"] == "english"


def test_shipped_story_resolves_completely(shipped: dict) -> None:
    for locale in ("en", "de"):
        out = seed.resolve_story(shipped, locale)
        for key in ("forms", "rationales", "owner_capability", "risks", "ground_rationale", "ofi_first", "ofi_second"):
            assert key in out, f"{key} of the shipped story is malformed or missing"
    assert out["plant_item"] == "PL-002"


def test_shipped_story_codes_exist_in_the_catalogue(shipped: dict, catalogue: dict) -> None:
    forms = {f["code"] for f in catalogue["forms"]}
    risks = {r["code"] for r in catalogue["risk_categories"]}
    assert set(shipped["forms"]) <= forms
    assert len(shipped["forms"]) == 3 and len(set(shipped["forms"])) == 3
    assert set(shipped["rationales"]) <= forms
    # Whichever form leads the comparison, there is a rationale for it.
    assert set(shipped["rationales"]) == set(shipped["forms"])
    assert set(shipped["risks"]) <= risks
    assert "public_client" in shipped["owner_capability"] and shipped["owner_capability"]["public_client"] is True


def test_shipped_story_names_the_plant_item_the_register_story_holds(shipped: dict) -> None:
    register = json.loads((PACK / "demo/school-ludwigsburg-plant_register.json").read_text(encoding="utf-8"))
    items = {i["code"]: i for i in register["items"]}
    item = items[shipped["plant_item"]]
    # The route of the item must still be open when the delivery model links it.
    assert item["reach"] in {"identified", "specified", "enquired", "route_set"}


def test_shipped_story_text_hygiene() -> None:
    text = STORY_FILE.read_text(encoding="utf-8")
    assert "\u2014" not in text and "\u2013" not in text


def test_bad_scores_are_dropped_and_good_ones_kept() -> None:
    assert "scores" not in seed.resolve_story({"scores": {"f": {"c": 6}}})
    assert "scores" not in seed.resolve_story({"scores": {"f": {"c": True}}})
    assert "scores" not in seed.resolve_story({"scores": []})
    assert seed.resolve_story({"scores": {"f": {"c": 4}}})["scores"] == {"f": {"c": 4}}


def test_story_scores_become_rows_for_compared_forms_and_known_criteria_only() -> None:
    rows = seed.story_score_rows({"a": "id-a"}, ["c1"], {"a": {"c1": 4, "nope": 2}, "b": {"c1": 5}})
    assert rows == [{"option_id": "id-a", "criterion_code": "c1", "score": 4}]


def test_trade_lots_lead_the_shipped_school_comparison(shipped, catalogue) -> None:
    """The school story is VOB/A trade lots, so the form the seeder proposes must be the split one."""
    from decimal import Decimal

    from app.modules.delivery_model.rules import weighted_totals

    story = seed.resolve_story(shipped, "de")
    weights = {c["code"]: Decimal(str(c["default_weight"])) for c in catalogue["criteria"]}
    forms = story["forms"]
    scores = {
        (form, c["code"]): story["scores"].get(form, {}).get(c["code"], c["scores"][form])
        for form in forms
        for c in catalogue["criteria"]
    }
    totals = weighted_totals(weights, forms, scores)
    assert max(forms, key=lambda f: totals[f]) == "design_bid_build_split"
    assert "design_bid_build_split" in story["rationales"]
