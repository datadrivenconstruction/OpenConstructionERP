# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plug values in bid leveling, the checks on them, and the award route."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.validation.engine import rule_registry
from app.core.validation.messages import translate
from app.core.validation.rules import register_builtin_rules
from app.modules.bid_management import validators as checks
from app.modules.bid_management.award_route import SUBCONTRACT, SUPPLY, bid_package_route
from app.modules.bid_management.plugs import compute_plugs, plug_summary


def _line(qty: str = "10", mandatory: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), quantity=qty, is_mandatory=mandatory)


A, B, C, D = "A", "B", "C", "D"


def test_a_gap_priced_by_two_others_takes_their_median() -> None:
    line = _line()
    priced = {
        A: {},
        B: {line.id: ("100", "included")},
        C: {line.id: ("140", "included")},
        D: {line.id: ("200", "included")},
    }
    [plug] = compute_plugs([line], priced, estimate_rates={line.id: Decimal("50")})[A]
    assert (plug.amount, plug.source, plug.reason) == (Decimal("140.00"), "median", "missing")


def test_with_one_other_price_the_estimate_rate_wins() -> None:
    line = _line(qty="4")
    priced = {A: {line.id: ("0", "excluded")}, B: {line.id: ("900", "included")}}
    [plug] = compute_plugs([line], priced, estimate_rates={line.id: Decimal("200")})[A]
    assert (plug.amount, plug.source, plug.reason) == (Decimal("800.00"), "estimate", "excluded")


def test_without_estimate_a_single_other_bid_is_used_and_nothing_is_none() -> None:
    line = _line()
    priced = {A: {}, B: {line.id: ("900", "included")}}
    assert compute_plugs([line], priced)[A][0].source == "single_bid"
    lonely = {A: {}}
    [plug] = compute_plugs([line], lonely)[A]
    assert (plug.amount, plug.source) == (Decimal("0.00"), "none")
    assert plug_summary([plug]) == (Decimal("0.00"), 1, 1)


def test_manual_plug_wins_and_optional_lines_are_not_gaps() -> None:
    line, optional = _line(), _line(mandatory=False)
    priced = {A: {}, B: {line.id: ("100", "included")}, C: {line.id: ("300", "included")}}
    plugs = compute_plugs([line, optional], priced, manual={(A, line.id): (Decimal("250"), "site visit")})
    [plug] = plugs[A]
    assert (plug.amount, plug.source, plug.note) == (Decimal("250.00"), "manual", "site visit")
    assert plugs[B] == [] and plugs[C] == []


def test_plug_share_over_threshold_warns_and_under_it_does_not() -> None:
    payload = {
        "currency": "EUR",
        "bidders": [
            {"name": "Rheinbeton", "plug_total": "15000", "plugged_total": "100000"},
            {"name": "Kranbau", "plug_total": "5000", "plugged_total": "100000"},
        ],
    }
    [finding] = checks.check_plug_share(payload)
    assert finding.element_ref == "Rheinbeton" and finding.params["share"] == "15.0"
    assert checks.check_plug_share({**payload, "threshold_pct": "20"}) == []


def test_unplugged_gaps_and_award_without_leveling_are_flagged() -> None:
    assert checks.check_gaps_plugged({"bidders": [{"name": "X", "unpriced_gap_lines": 2}]})[0].params["count"] == "2"
    assert checks.check_award_leveled({"package": "BP-1", "leveling_computed": False})[0].element_ref == "BP-1"
    assert checks.check_award_leveled({"package": "BP-1", "leveling_computed": True}) == []


def test_rules_are_registered_and_messages_exist_in_en_de_ru() -> None:
    register_builtin_rules()
    award_ids = {r.rule_id for r in rule_registry.get_rules_for_sets(["bid_award"])}
    assert {"bid_leveling.plug_share", "bid_leveling.gaps_plugged", "bid_leveling.award_leveled"} <= award_ids
    change_ids = {r.rule_id for r in rule_registry.get_rules_for_sets(["subcontract_change"])}
    assert {
        "subcontract.change_owner_linked",
        "subcontract.change_amount_set",
        "subcontract.change_within_owner_value",
    } <= change_ids
    for locale in ("en", "de", "ru"):
        text = translate("bid_leveling.award_leveled.fail", locale=locale, package="BP-1")
        assert "BP-1" in text and "award_leveled" not in text


@pytest.mark.parametrize(
    ("package_type", "route"), [("supply", SUPPLY), ("subcontract", SUBCONTRACT), (None, SUBCONTRACT)]
)
def test_a_package_routes_to_exactly_one_commitment_kind(package_type: str | None, route: str) -> None:
    assert bid_package_route(SimpleNamespace(package_type=package_type)) == route


def test_linked_tender_without_award_is_flagged() -> None:
    from app.modules.bid_management.validators import check_linked_tender_awarded

    base = {"package": "BP-001", "linked_tender": "Main works"}
    assert check_linked_tender_awarded({**base, "status": "evaluating"})[0].params["tender"] == "Main works"
    assert check_linked_tender_awarded({**base, "status": "awarded"}) == []
    assert check_linked_tender_awarded({"package": "BP-002", "status": "open"}) == []
