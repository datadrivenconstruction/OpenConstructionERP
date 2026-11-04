# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Validation rules and the confirm guard of rate feedback."""

import asyncio
from decimal import Decimal as D

import pytest

from app.core.validation.engine import rule_registry
from app.modules.rate_feedback.manifest import manifest
from app.modules.rate_feedback.validators import (
    RATE_FEEDBACK_RULE_SET,
    RateFeedbackError,
    check_confirmable,
    register_rate_feedback_rules,
    run_rules,
)


def proposal(**kw):
    base = {
        "status": "pending",
        "unit": "m3",
        "current_rate": D("100"),
        "suggested_rate": D("120"),
        "confidence": D("0.8"),
        "project_count": 3,
        "line_count": 5,
    }
    base.update(kw)
    return base


ITEM = {"unit": "m3", "rate": "100"}


def failed(p, item=ITEM):
    return {r.rule_id for r in asyncio.run(run_rules(p, item))}


def test_clean_proposal_passes_every_rule():
    assert failed(proposal()) == set()


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        ({"suggested_rate": D("0")}, "rate_positive"),
        ({"project_count": 0}, "sample_present"),
        ({"confidence": D("1.5")}, "confidence_range"),
        ({"unit": "m2"}, "unit_matches"),
        ({"confidence": D("0.1")}, "low_confidence"),
        ({"suggested_rate": D("400")}, "jump_plausible"),
        ({"suggested_rate": D("30")}, "jump_plausible"),
    ],
)
def test_each_rule_fires(change, rule):
    assert f"rate_feedback.{rule}" in failed(proposal(**change))


def test_registration_is_idempotent_and_complete():
    register_rate_feedback_rules()
    register_rate_feedback_rules()
    assert len(rule_registry._rule_sets[RATE_FEEDBACK_RULE_SET]) == 6


def test_confirm_refuses_a_stale_rate():
    with pytest.raises(RateFeedbackError) as exc:
        check_confirmable(proposal(), {"unit": "m3", "rate": "110"})
    assert exc.value.code == "stale_rate"


def test_confirm_refuses_decided_missing_and_unit_changed():
    codes = []
    for p, item in [
        (proposal(status="accepted"), ITEM),
        (proposal(), None),
        (proposal(), {"unit": "m2", "rate": "100"}),
    ]:
        with pytest.raises(RateFeedbackError) as exc:
            check_confirmable(p, item)
        codes.append(exc.value.code)
    assert codes == ["not_pending", "cost_item_gone", "unit_changed"]


def test_confirm_accepts_equal_rates_written_differently():
    check_confirmable(proposal(), {"unit": "m3", "rate": "100.00"})


def test_manifest_declares_human_confirmed_rule_based_inference():
    assert manifest.name == "oe_rate_feedback"
    assert not manifest.inference_gaps()
