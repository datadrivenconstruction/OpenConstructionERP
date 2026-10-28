"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Demo story override of the plant register seeder: pure merge/validation and the shipped Ludwigsburg file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.plant_register import seed
from app.modules.plant_register.catalogue import shipped_default

REPO = Path(__file__).resolve().parents[3]
STORY_FILE = (
    REPO
    / "packs/eleven-areas-framework/src/openconstructionerp_eleven_areas_framework/demo"
    / "school-ludwigsburg-plant_register.json"
)


@pytest.fixture(scope="module")
def codes() -> dict[str, set[str]]:
    return seed._catalogue_codes()


@pytest.fixture(scope="module")
def shipped() -> dict:
    return json.loads(STORY_FILE.read_text(encoding="utf-8"))


def _item(**over: object) -> dict:
    base = {
        "code": "PL-001",
        "title": "Heat pump",
        "class": "heat_pump",
        "quantity": "1",
        "need_days": 100,
        "reach": "enquired",
    }
    return {**base, **over}


def test_no_story_changes_nothing(codes: dict[str, set[str]]) -> None:
    assert seed.resolve_story(None, codes) == {}
    assert seed.resolve_story({}, codes) == {}


def test_valid_item_table_is_taken(codes: dict[str, set[str]]) -> None:
    out = seed.resolve_story({"items": [_item(), _item(code="PL-002", slot="held")]}, codes)
    assert [i["code"] for i in out["items"]] == ["PL-001", "PL-002"]
    assert out["items"][1]["slot"] == "held"
    assert out["items"][0]["quotes"] == [] and out["items"][0]["spares"] == []


@pytest.mark.parametrize(
    "bad",
    [
        _item(**{"class": "not_a_class"}),
        _item(quantity="many"),
        _item(reach="flying"),
        _item(need_days="soon"),
        _item(redundancy="3N"),
        _item(slot="maybe"),
        _item(quotes=[["supplier_quote", "x", -1, None, 5, 3, "from_order"]]),
        _item(quotes=[["unknown_source", "x", -1, None, 3, 5, "from_order"]]),
        _item(spares=[["no_such_category", "x", "1", "set"]]),
    ],
)
def test_malformed_item_keeps_the_default_table(codes: dict[str, set[str]], bad: dict) -> None:
    assert "items" not in seed.resolve_story({"items": [_item(), bad]}, codes)


def test_duplicate_item_code_keeps_default(codes: dict[str, set[str]]) -> None:
    assert "items" not in seed.resolve_story({"items": [_item(), _item()]}, codes)


def test_language_map_title_follows_locale(codes: dict[str, set[str]]) -> None:
    story = {"items": [_item(title={"en": "Heat pump", "de": "Waermepumpe"})]}
    assert seed.resolve_story(story, codes, "de")["items"][0]["title"] == "Waermepumpe"
    assert seed.resolve_story(story, codes, "en")["items"][0]["title"] == "Heat pump"


def test_limits_need_every_step_and_known_parties(codes: dict[str, set[str]]) -> None:
    good = dict.fromkeys(codes["delivery_limit_steps"], "supplier")
    assert seed.resolve_story({"limits": good}, codes)["limits"] == good
    assert "limits" not in seed.resolve_story({"limits": {"supply": "supplier"}}, codes)
    assert "limits" not in seed.resolve_story({"limits": {**good, "accept": "nobody"}}, codes)


def test_day_counts(codes: dict[str, set[str]]) -> None:
    assert seed.resolve_story({"mobilisation_days": 200}, codes)["MOBILISATION_DAYS"] == 200
    assert "MOBILISATION_DAYS" not in seed.resolve_story({"mobilisation_days": -1}, codes)
    assert "GATE_TARGET_DAYS" not in seed.resolve_story({"gate_target_days": "7"}, codes)


def test_slot_overrides_and_bad_state(codes: dict[str, set[str]]) -> None:
    ok = seed.resolve_story({"slots": {"held": {"vendor_name": "A", "convert_by_days": 30}}}, codes)
    assert ok["slots"]["held"] == {"vendor_name": "A", "convert_by_days": 30}
    assert "slots" not in seed.resolve_story({"slots": {"booked": {}}}, codes)
    assert "slots" not in seed.resolve_story({"slots": {"held": {"reservation_fee": "lots"}}}, codes)


def test_shipped_story_resolves_completely(shipped: dict, codes: dict[str, set[str]]) -> None:
    for locale in ("en", "de"):
        out = seed.resolve_story(shipped, codes, locale)
        for key in ("items", "limits", "paper", "slots", "it_services", "site_plant"):
            assert key in out, f"{key} of the shipped story is malformed or missing"


def test_shipped_story_content(shipped: dict, codes: dict[str, set[str]]) -> None:
    out = seed.resolve_story(shipped, codes)
    items = {i["code"]: i for i in out["items"]}
    # The commitment release slot item links to PL-001; the delivery model supplies PL-002.
    assert items["PL-001"]["class"] == "heat_pump" and items["PL-001"].get("slot") == "held"
    assert items["PL-002"].get("paper") and items["PL-002"]["class"] == "kitchen_equipment"
    # One held slot (free of charge, converted by the order) and one requested.
    assert {i.get("slot") for i in items.values()} >= {"held", "requested"}
    assert "cancelled" in {i["reach"] for i in items.values()}
    paper = out["paper"]
    quotes_b = items["PL-002"]["quotes"]
    assert max(o["lead_weeks"] for o in paper["options"]) >= max(q[5] for q in quotes_b)
    # The seeder's own default constants for the slot windows are not contradicted.
    assert out["slots"]["held"]["convert_by_days"] == 45
    # Only one item flagged as decision paper.
    assert sum(1 for i in out["items"] if i.get("paper")) == 1
    # Every catalogue code used exists in the shipped catalogue.
    cat = shipped_default()
    assert all(cat.component_class(i["class"]) is not None for i in out["items"])


def test_shipped_story_text_hygiene() -> None:
    text = STORY_FILE.read_text(encoding="utf-8")
    assert "\u2014" not in text and "\u2013" not in text
