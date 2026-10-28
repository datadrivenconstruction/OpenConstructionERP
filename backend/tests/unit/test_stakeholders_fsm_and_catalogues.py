# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠State machines and the shipped ``stakeholder_framework`` catalogues (SPEC sections 2, 3, 7 and 8.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.stakeholders.catalogue import (
    CATALOGUE_DIR,
    FRAMEWORK_KIND,
    StakeholderFramework,
    list_frameworks,
    register_kind,
    validate_framework,
)
from app.modules.stakeholders.fsm import COMMITMENT_FSM, EVENT_FSM, MANDATE_TARGETS, PLAN_FSM

# ── state machines (table driven) ─────────────────────────────────────────

COMMITMENT_TABLE = [
    ("proposed", "agreed", True),
    ("proposed", "in_progress", False),
    ("proposed", "fulfilled", False),
    ("proposed", "verified", False),
    ("agreed", "in_progress", True),
    ("agreed", "fulfilled", True),
    ("agreed", "verified", False),
    ("in_progress", "fulfilled", True),
    ("fulfilled", "verified", True),
    ("fulfilled", "in_progress", True),
    ("proposed", "withdrawn", True),
    ("agreed", "withdrawn", True),
    ("fulfilled", "withdrawn", False),
    ("verified", "in_progress", False),
    ("withdrawn", "agreed", False),
    ("agreed", "breached", True),
    ("proposed", "breached", False),
    ("breached", "fulfilled", True),
    ("breached", "verified", False),
]


@pytest.mark.parametrize(("src", "dst", "ok"), COMMITMENT_TABLE)
def test_commitment_transitions(src: str, dst: str, ok: bool) -> None:
    assert COMMITMENT_FSM.has_transition(src, dst) is ok


def test_commitment_terminals_and_mandate_targets() -> None:
    assert COMMITMENT_FSM.is_terminal("verified")
    assert COMMITMENT_FSM.is_terminal("withdrawn")
    assert not COMMITMENT_FSM.is_terminal("breached")
    assert set(MANDATE_TARGETS) == {"agreed", "withdrawn"}


@pytest.mark.parametrize(
    ("src", "dst", "ok"),
    [
        ("planned", "active", True),
        ("active", "paused", True),
        ("paused", "active", True),
        ("planned", "completed", False),
        ("completed", "active", False),
        ("cancelled", "planned", False),
    ],
)
def test_plan_item_transitions(src: str, dst: str, ok: bool) -> None:
    assert PLAN_FSM.has_transition(src, dst) is ok


@pytest.mark.parametrize(
    ("src", "dst", "ok"),
    [
        ("planned", "held", True),
        ("planned", "cancelled", True),
        ("held", "planned", False),
        ("cancelled", "held", False),
    ],
)
def test_event_transitions(src: str, dst: str, ok: bool) -> None:
    assert EVENT_FSM.has_transition(src, dst) is ok


# ── shipped catalogues ───────────────────────────────────────────────────

SHIPPED = sorted(p.stem for p in CATALOGUE_DIR.glob("*.json"))


def _raw(fid: str) -> dict:
    return json.loads((CATALOGUE_DIR / f"{fid}.json").read_text(encoding="utf-8"))


def test_the_four_frameworks_ship() -> None:
    assert SHIPPED == ["de_public_participation", "elf_module_framework", "neutral", "uk_planning_consultation"]


@pytest.mark.parametrize("fid", SHIPPED)
def test_every_shipped_framework_validates(fid: str) -> None:
    fw = StakeholderFramework.model_validate(_raw(fid))
    assert validate_framework(fw, "shipped") == []


@pytest.mark.parametrize("fid", SHIPPED)
def test_every_statutory_ref_has_url_and_review_status(fid: str) -> None:
    for f in _raw(fid)["participation_formats"]:
        for ref in f["statutory_refs"]:
            assert ref["url"].startswith("https://"), (fid, f["code"])
            assert ref["review_status"] in ("verified", "unconfirmed"), (fid, f["code"])


@pytest.mark.parametrize("fid", SHIPPED)
def test_every_shipped_item_has_an_i18n_key_in_the_message_catalogue(fid: str) -> None:
    from app.modules.stakeholders.messages import is_key_present

    keys: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("name_key", "promise_key") and v:
                    keys.append(v)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(_raw(fid))
    missing = [k for k in keys if not is_key_present(k, "en") or not is_key_present(k, "de")]
    assert missing == []


def test_spec_vocabulary_is_shipped() -> None:
    fw = StakeholderFramework.model_validate(_raw("neutral"))
    cats = {c.code for c in fw.stakeholder_categories}
    assert {"municipality", "grid_operator", "neighbour", "public", "permitting_authority"} <= cats
    assert {c.code for c in fw.stakeholder_categories if c.private_person} == {"neighbour", "public"}
    assert [p.code for p in sorted(fw.participation_levels, key=lambda p: p.order)] == [
        "inform",
        "consult",
        "involve",
        "collaborate",
        "empower",
    ]
    assert {m.code for m in fw.analysis_methods} == {
        "power_interest",
        "salience",
        "engagement_level",
        "attitude",
        "influence",
    }
    assert fw.decision_type("order_award").commitment_type == "works"
    assert fw.decision_type("stakeholder_commitment").approval_target_kind is None


def test_elf_framework_routes_commitments_through_approval() -> None:
    fw = StakeholderFramework.model_validate(_raw("elf_module_framework"))
    assert fw.decision_type("stakeholder_commitment").approval_target_kind == "stakeholder_commitment"


def test_de_and_uk_ship_their_statutory_formats() -> None:
    de = StakeholderFramework.model_validate(_raw("de_public_participation"))
    uk = StakeholderFramework.model_validate(_raw("uk_planning_consultation"))
    assert de.format("early_public_participation_baugb_3_1").statutory_refs[0].review_status == "unconfirmed"
    assert uk.format("community_consultation_socc").statutory_refs[0].ref == "Planning Act 2008 s47"


# ── validator catches what the schema cannot (framework_scales_valid) ────────


def _mutated(**changes) -> StakeholderFramework:
    raw = _raw("neutral")
    raw.update(changes)
    return StakeholderFramework.model_validate(raw)


def test_validator_refuses_two_template_deciders() -> None:
    raw = _raw("neutral")
    raw["mandate_template"].append(
        {"decision_type": "order_award", "holder_kind": "role", "holder_code": "project_manager", "letter": "D"}
    )
    errors = validate_framework(StakeholderFramework.model_validate(raw), "tenant")
    assert any("2 deciders for order_award" in e for e in errors)


def test_validator_refuses_rule_bounds_outside_the_scale_and_undeclared_classes() -> None:
    raw = _raw("neutral")
    pi = next(m for m in raw["analysis_methods"] if m["code"] == "power_interest")
    pi["rules"][0]["when"]["power"] = {"gte": 9}
    pi["rules"][1]["classification"] = "invented"
    errors = validate_framework(StakeholderFramework.model_validate(raw), "tenant")
    assert any("bound 9 outside power" in e for e in errors)
    assert any("class invented not declared" in e for e in errors)


def test_validator_refuses_unknown_level_and_required_type_without_decider() -> None:
    raw = _raw("neutral")
    raw["participation_formats"][0]["default_level"] = "shout"
    raw["mandate_template"] = [r for r in raw["mandate_template"] if r["decision_type"] != "gate_decision"]
    errors = validate_framework(StakeholderFramework.model_validate(raw), "tenant")
    assert any("unknown level shout" in e for e in errors)
    assert any("required decision type gate_decision has no decider" in e for e in errors)


def test_statutory_ref_without_url_is_a_schema_error() -> None:
    raw = _raw("de_public_participation")
    fmt = next(f for f in raw["participation_formats"] if f["statutory_refs"])
    fmt["statutory_refs"][0]["url"] = ""
    with pytest.raises(ValueError):
        StakeholderFramework.model_validate(raw)


def test_kind_registers_with_module_one() -> None:
    from app.modules.project_governance.catalogue_kinds import catalogue_kinds

    register_kind()
    assert FRAMEWORK_KIND in catalogue_kinds()
    assert {f.id for f in list_frameworks()} == set(SHIPPED)


def test_the_country_default_is_the_answer_of_the_governance_port() -> None:
    """Asked through the real port: the shipped framework that claims the country, else neutral."""
    from app.modules.stakeholders.catalogue import default_framework_pin

    versions = {f.id: f.version for f in list_frameworks()}
    for country, expected in (("de", "de_public_participation"), ("GB", "uk_planning_consultation")):
        source, fid, version = default_framework_pin(country)
        assert (source, fid) == ("shipped", expected), country
        # The port may name the version; when it does it is the shipped one.
        assert version in (None, versions[expected]), country
    assert default_framework_pin("FR") == ("shipped", "neutral", None)
    assert default_framework_pin(None) == ("shipped", "neutral", None)


def test_without_an_answer_of_the_port_every_country_gets_the_neutral_framework(monkeypatch) -> None:
    """The module has no country rule of its own left: silence of the port is neutral, for Germany too."""
    from app.modules.project_governance import public
    from app.modules.stakeholders import catalogue
    from app.modules.stakeholders.catalogue import FRAMEWORK_KIND, default_framework_pin

    asked: list[tuple[str, str | None]] = []

    def no_opinion(kind, country_code=None, subdivision_code=None):
        asked.append((kind, country_code))

    monkeypatch.setattr(public, "default_catalogue_pin", no_opinion)
    for country in ("de", "GB", "FR", None):
        assert default_framework_pin(country) == ("shipped", "neutral", None), country
    assert asked == [(FRAMEWORK_KIND, c) for c in ("de", "GB", "FR", None)]

    monkeypatch.setattr(
        public,
        "default_catalogue_pin",
        lambda kind, country_code=None, subdivision_code=None: public.CataloguePin("pack", "acme_people", 3),
    )
    assert default_framework_pin("de") == ("pack", "acme_people", 3)

    assert not hasattr(catalogue, "default_framework_id_for_country")
    module = Path(catalogue.__file__).parent
    for path in sorted(module.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        # Reading the regional packs or matching a framework's countries is the port's work.
        assert "regional_packs" not in source and "packs_for_country" not in source, path.name
        assert ".jurisdiction_countries" not in source, path.name
