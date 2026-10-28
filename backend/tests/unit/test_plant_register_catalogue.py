# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Catalogue kind ``plant_register``, the message bundle and the one-list grep tests (rules 1, 12, 20)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.modules.plant_register.catalogue import (
    CATALOGUE_DIR,
    PLANT_KIND,
    PlantCatalogue,
    register_plant_kind,
    validate_plant_catalogue,
)

MODULES = Path(__file__).resolve().parents[2] / "app" / "modules"
SPEC_CLASSES = {
    "power_transformer", "distribution_transformer", "mv_switchgear", "lv_switchboard", "generator", "ups",
    "battery_storage", "chiller", "cooling_tower", "boiler", "heat_pump", "ahu", "lift", "escalator",
    "sprinkler_pump", "bms_controls", "facade_unit", "structural_steel_package", "process_unit",
    "crane_permanent", "kitchen_equipment", "medical_equipment", "it_core_network",
}  # fmt: skip


def _raw() -> dict:
    return json.loads((CATALOGUE_DIR / "neutral.json").read_text(encoding="utf-8"))


def test_shipped_catalogue_loads_through_the_governance_registry() -> None:
    from app.modules.project_governance.catalogue_kinds import catalogue_kinds, get_catalogue_kind

    register_plant_kind()
    assert PLANT_KIND in catalogue_kinds()
    cat = get_catalogue_kind(PLANT_KIND).get_shipped("neutral")
    assert isinstance(cat, PlantCatalogue)
    assert {c.code for c in cat.component_classes} == SPEC_CLASSES
    assert cat.step_codes()[0] == "supply" and cat.step_codes()[-1] == "document"


def test_every_shipped_lead_time_is_unconfirmed_with_an_as_of_date() -> None:
    for c in _raw()["component_classes"]:
        lw = c["typical_lead_weeks"]
        assert lw["review_status"] == "unconfirmed", c["code"]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", lw["as_of"]), c["code"]


def test_a_verified_lead_time_in_a_shipped_file_is_rejected() -> None:
    body = _raw()
    body["component_classes"][0]["typical_lead_weeks"]["review_status"] = "verified"
    errors = validate_plant_catalogue(PlantCatalogue.model_validate(body), "shipped")
    assert any("shipped lead time must be unconfirmed" in e for e in errors)


def test_verified_without_source_url_is_rejected_and_routes_carry_sources() -> None:
    body = _raw()
    for r in body["procurement_routes"]:
        if r["review_status"] == "verified":
            assert r["source_url"].startswith("https://"), r["code"]
    body["procurement_routes"][0]["source_url"] = None
    errors = validate_plant_catalogue(PlantCatalogue.model_validate(body), "shipped")
    assert any("verified without source_url" in e for e in errors)


def test_every_owner_furnished_route_has_a_country_alias() -> None:
    body = _raw()
    for r in body["procurement_routes"]:
        if r["code"].startswith("owner_furnished"):
            assert r["aliases"], r["code"]


def test_duplicate_codes_and_inverted_ranges_are_rejected() -> None:
    body = _raw()
    body["component_classes"].append(dict(body["component_classes"][0]))
    body["component_classes"][1]["typical_lead_weeks"] = {
        **body["component_classes"][1]["typical_lead_weeks"],
        "min": 99,
        "max": 3,
    }
    errors = validate_plant_catalogue(PlantCatalogue.model_validate(body), "shipped")
    assert any("duplicate code power_transformer" in e for e in errors)
    assert any("min > max" in e for e in errors)


def test_expert_estimate_is_not_market_evidence() -> None:
    sources = {s["code"]: s for s in _raw()["lead_time_sources"]}
    assert sources["expert_estimate"]["market_evidence"] is False
    assert all(s["market_evidence"] for k, s in sources.items() if k != "expert_estimate")
    assert sources["supplier_quote"]["evidence_rank"] == 1


@pytest.mark.parametrize("locale", ["en", "de"])
def test_every_catalogue_label_and_error_code_has_a_message(locale: str) -> None:
    from app.modules.plant_register.messages import is_key_present

    keys = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("name_key", "description_key") and v:
                    keys.append(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(_raw())
    src = "\n".join(p.read_text(encoding="utf-8") for p in (MODULES / "plant_register").glob("*.py"))
    codes = set(re.findall(r'(?:PlantError|conflict|forbidden|not_found)\(\s*"([a-z_]+)"', src))
    codes |= set(re.findall(r'(?:blocked\(\[|out\.append\(|errors\.append\()\s*"([a-z_]+)"', src))
    codes |= {"lead_time_without_enquiry_date", "enquiry_date_in_future", "response_before_enquiry"}
    codes |= {"route_inconsistent_with_package_plan", "decision_paper_needs_two_options", "transition_blocked"}
    keys += [f"plant.errors.{c}" for c in codes]
    missing = [k for k in keys if not is_key_present(k, locale=locale)]
    assert not missing, missing


def _model_columns(pattern: str) -> list[str]:
    hits = []
    rx = re.compile(rf"^\s+({pattern})\s*:\s*Mapped", re.MULTILINE)
    for path in MODULES.glob("*/models.py"):
        for m in rx.finditer(path.read_text(encoding="utf-8")):
            hits.append(f"{path.parent.name}.{m.group(1)}")
    return sorted(hits)


def test_rule_1_no_new_module_adds_a_long_lead_column() -> None:
    """The plant register is the only long-lead list; submittals keep theirs for contractor items."""
    assert _model_columns(r"long_lead\w*") == [
        "plant_register.long_lead_override",
        "plant_register.long_lead_override_reason",
        "submittals.long_lead",
    ]


# A lead time that is NOT the lead time of a plant item: a different thing under a similar name.
_OTHER_LEAD_TIMES = {
    "procurement.lead_time_days": "requisition call-off at execution time",
    "supplier_catalogs.lead_time_days": "catalogue entry, a quote source of rank supplier_catalogue",
    "submittals.lead_time_weeks": "contractor submittals, read-only when linked to a plant item",
    "property_dev.lead_time_days": "sales lead-to-contract time, not procurement",
    "procurement_concept.lead_time_days": "time a whole contract package needs from award to start, not one item",
    "procurement_concept.lead_time_signal_days": "what a market sounding said about a package, an observation",
}


# A lead time of its own that a row keeps as a FALLBACK, for the case that the row is not in the register.
# Sanctioned one by one: the module must also link the row to a plant item and read the register for a
# linked row (the second test below), so one item never has two figures.
_FALLBACK_LEAD_TIMES = {
    "commitment_release.lead_time_days": "a commitment for something that is not plant (a works package, a service)",
    "delivery_model.lead_time_days": "an owner-furnished item the register does not hold",
    "delivery_model.enquiry_date": "the enquiry behind that fallback lead time",
}


def test_the_demo_item_another_module_takes_over_can_still_change_its_route() -> None:
    """PL-002 becomes the owner-furnished demo item: the delivery model sets its route after this seed.

    ``set_route`` refuses ``route_frozen`` from ``ordered`` on, so the seed
    must leave this one before the order, on a healthy and on a before-gate
    project alike (the before-gate story only ever stops earlier).
    """
    from app.modules.plant_register import calc
    from app.modules.plant_register.seed import _ITEMS

    spec = next(spec for spec in _ITEMS if spec["code"] == "PL-002")
    assert not calc.is_ordered(spec["reach"]), spec["reach"]


def _reads_the_plant_item(module: str) -> bool:
    """Whether ``module`` can link its row to a plant item and reads that item's dates from the register."""
    root = MODULES / module
    models = (root / "models.py").read_text(encoding="utf-8")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    return bool(re.search(r"^\s+plant_item_id\s*:\s*Mapped", models, re.MULTILINE)) and "plant_item_dates" in source


def _lead_time_columns() -> set[str]:
    return set(_model_columns(r"lead_time\w*|enquiry_date")) - {"plant_register.enquiry_date"}


def test_rule_12_no_module_keeps_its_own_lead_time_copy() -> None:
    """``commitment_lead_time_duplicated``: the lead time of a plant item lives on its quote.

    Every lead time and enquiry date column outside the register is pinned by
    name, in one of two lists. ``_OTHER_LEAD_TIMES``: a different thing under
    a similar name. ``_FALLBACK_LEAD_TIMES``: a row that may also stand for
    something outside the register keeps its own figure for that case. A NEW
    column of this kind fails here until somebody decides which it is.
    """
    columns = _lead_time_columns()
    new = sorted(columns - set(_OTHER_LEAD_TIMES) - set(_FALLBACK_LEAD_TIMES))
    assert not new, (
        f"{new}: a new lead time or enquiry date outside the plant register. If the thing may be a plant item, "
        "link the row (plant_item_id), read plant_register.reads.plant_item_dates when it is linked and add the "
        "column to _FALLBACK_LEAD_TIMES; if it is a different thing, add it to _OTHER_LEAD_TIMES. Either way "
        "with the reason."
    )
    # An entry for a column that is gone would keep excusing the next column of that name.
    pinned = {**_OTHER_LEAD_TIMES, **_FALLBACK_LEAD_TIMES}
    stale = sorted(c for c in pinned if c not in columns and (MODULES / c.split(".")[0]).is_dir())
    assert not stale, stale


def test_rule_12_a_fallback_lead_time_comes_with_the_link_to_the_plant_item() -> None:
    """A module that keeps a fallback lead time also links to the plant item and reads the register for it."""
    modules = sorted({c.split(".")[0] for c in _FALLBACK_LEAD_TIMES if (MODULES / c.split(".")[0]).is_dir()})
    unlinked = [module for module in modules if not _reads_the_plant_item(module)]
    assert not unlinked, (
        f"{unlinked}: keeps a lead time of its own without the link. Declare plant_item_id on the model and read "
        "plant_register.reads.plant_item_dates (or plant_items_dates) for a linked row."
    )
