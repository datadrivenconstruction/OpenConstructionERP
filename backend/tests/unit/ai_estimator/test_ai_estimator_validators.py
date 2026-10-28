# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the AI Estimate Builder module validation rules.

Pure unit tests over ``ValidationContext`` (no DB). They pin the module's
estimator-specific invariants that gate (or flag) an applied estimate:

    * rate_grounding (ERROR)        - every position must reference a real
                                      cost-database rate; an ungrounded
                                      position is rejected (blocks apply).
    * group_has_quantity (ERROR)    - a zero/negative quantity has nothing to
                                      price.
    * rate_currency_matches (ERROR) - a position's rate currency must match the
                                      run base currency (never-blend).
    * resource_breakdown (WARNING)  - a composite position should carry a
                                      resource breakdown.
    * low_confidence (WARNING)      - a sub-medium-confidence, non-human-
                                      confirmed position is flagged.
    * completeness (INFO)           - advisory scope gaps from CHECK_SCOPE.

It also asserts the rules register into the ``ai_estimator`` rule set so the
service can request them alongside ``boq_quality``.

Run:
    cd backend
    python -m pytest tests/unit/ai_estimator/test_ai_estimator_validators.py -q
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.ai_estimator.validators import (
    AiEstimatorCompleteness,
    AiEstimatorGroupHasQuantity,
    AiEstimatorLowConfidence,
    AiEstimatorRateCurrencyMatches,
    AiEstimatorRateGrounding,
    AiEstimatorResourceBreakdown,
    register_ai_estimator_rules,
)


def _ctx(positions: list[dict], **metadata) -> ValidationContext:
    return ValidationContext(data={"positions": positions}, metadata=metadata)


def _grounded_position(**overrides) -> dict:
    """A clean, fully-grounded position dict the service feeds the engine."""
    pos = {
        "id": "p1",
        "ordinal": "0001",
        "description": "Reinforced concrete wall",
        "unit": "m3",
        "quantity": 10.0,
        "unit_rate": "185.00",
        "currency": "EUR",
        "confidence": 0.83,
        "confidence_band": "high",
        "human_confirmed": True,
        "resources": [{"name": "Concrete", "type": "material"}],
        "metadata_": {"cost_item_id": "cost-1"},
    }
    pos.update(overrides)
    return pos


# ── rate_grounding (ERROR) - the LLM never invents a rate ─────────────────────


@pytest.mark.asyncio
async def test_rate_grounding_passes_with_cost_item_ref():
    rule = AiEstimatorRateGrounding()
    results = await rule.validate(_ctx([_grounded_position()]))
    assert len(results) == 1
    assert results[0].passed is True


@pytest.mark.asyncio
async def test_rate_grounding_fails_without_any_grounding():
    rule = AiEstimatorRateGrounding()
    pos = _grounded_position(metadata_={})  # no cost_item_id, no candidate_id
    results = await rule.validate(_ctx([pos]))
    assert results[0].passed is False
    assert results[0].severity == Severity.ERROR
    assert "cost database" in results[0].message.lower()


@pytest.mark.asyncio
async def test_rate_grounding_accepts_candidate_id_fallback():
    """A position carrying a candidate_id (but no metadata cost_item_id) is
    still grounded - the candidate id is a real cost-DB row."""
    rule = AiEstimatorRateGrounding()
    pos = _grounded_position(metadata_={}, candidate_id="cost-9")
    results = await rule.validate(_ctx([pos]))
    assert results[0].passed is True


# ── group_has_quantity (ERROR) ───────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(("qty", "ok"), [(10.0, True), (0.0, False), (-5.0, False), ("nan", False), (None, False)])
async def test_group_has_quantity(qty, ok):
    rule = AiEstimatorGroupHasQuantity()
    results = await rule.validate(_ctx([_grounded_position(quantity=qty)]))
    assert results[0].passed is ok
    if not ok:
        assert results[0].severity == Severity.ERROR


# ── rate_currency_matches (ERROR) - never-blend ──────────────────────────────


@pytest.mark.asyncio
async def test_currency_match_passes_when_equal():
    rule = AiEstimatorRateCurrencyMatches()
    results = await rule.validate(_ctx([_grounded_position(currency="EUR")], base_currency="EUR"))
    assert results[0].passed is True


@pytest.mark.asyncio
async def test_currency_mismatch_is_error():
    rule = AiEstimatorRateCurrencyMatches()
    results = await rule.validate(_ctx([_grounded_position(currency="USD")], base_currency="EUR"))
    assert results[0].passed is False
    assert results[0].severity == Severity.ERROR
    assert "USD" in results[0].message and "EUR" in results[0].message


@pytest.mark.asyncio
async def test_currency_rule_no_signal_passes():
    """No base currency resolved (or a zero-rate position) -> the rule has no
    signal and must not emit a false ERROR."""
    rule = AiEstimatorRateCurrencyMatches()
    # No base currency.
    r1 = await rule.validate(_ctx([_grounded_position(currency="USD")]))
    assert r1[0].passed is True
    # Zero rate (no grounded number to compare).
    r2 = await rule.validate(_ctx([_grounded_position(currency="USD", unit_rate="0")], base_currency="EUR"))
    assert r2[0].passed is True


# ── resource_breakdown (WARNING) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resource_breakdown_warns_when_absent():
    rule = AiEstimatorResourceBreakdown()
    ok = await rule.validate(_ctx([_grounded_position(resources=[{"name": "x"}])]))
    assert ok[0].passed is True
    warn = await rule.validate(_ctx([_grounded_position(resources=[])]))
    assert warn[0].passed is False
    assert warn[0].severity == Severity.WARNING


# ── low_confidence (WARNING) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_low_confidence_warns_unless_human_confirmed():
    rule = AiEstimatorLowConfidence()
    # Human-confirmed always passes (the human took responsibility).
    hc = await rule.validate(_ctx([_grounded_position(confidence=0.1, human_confirmed=True)]))
    assert hc[0].passed is True
    # Low confidence + not human-confirmed -> warning.
    low = await rule.validate(_ctx([_grounded_position(confidence=0.4, human_confirmed=False)]))
    assert low[0].passed is False
    assert low[0].severity == Severity.WARNING
    # None confidence (no real score) + not human-confirmed -> warning (not
    # silently treated as fine).
    none = await rule.validate(_ctx([_grounded_position(confidence=None, human_confirmed=False)]))
    assert none[0].passed is False
    # High confidence + not human-confirmed -> passes.
    high = await rule.validate(_ctx([_grounded_position(confidence=0.9, human_confirmed=False)]))
    assert high[0].passed is True


# ── completeness (INFO) ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_completeness_is_info_advisory():
    rule = AiEstimatorCompleteness()
    clean = await rule.validate(_ctx([_grounded_position()], missing_items=[]))
    assert clean[0].passed is True
    assert clean[0].severity == Severity.INFO
    flagged = await rule.validate(_ctx([_grounded_position()], missing_items=["Roofing", "MEP"]))
    assert flagged[0].passed is False
    assert flagged[0].severity == Severity.INFO  # advisory only, never blocks
    assert "Roofing" in flagged[0].message


# ── registration ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rules_register_into_ai_estimator_rule_set():
    """The service requests rule_sets=['boq_quality','ai_estimator',...]; the
    module rules must resolve under the 'ai_estimator' set."""
    from app.core.validation.engine import rule_registry

    register_ai_estimator_rules()
    rules = rule_registry.get_rules_for_sets(["ai_estimator"])
    rule_ids = {r.rule_id for r in rules}
    for expected in (
        "ai_estimator.rate_grounding",
        "ai_estimator.group_has_quantity",
        "ai_estimator.rate_currency_matches",
        "ai_estimator.resource_breakdown",
        "ai_estimator.low_confidence",
        "ai_estimator.completeness",
    ):
        assert expected in rule_ids, f"{expected} not registered under ai_estimator set"

    # The two ERROR rules block apply; assert their severity is ERROR.
    by_id = {r.rule_id: r for r in rules}
    assert by_id["ai_estimator.rate_grounding"].severity == Severity.ERROR
    assert by_id["ai_estimator.group_has_quantity"].severity == Severity.ERROR
    assert by_id["ai_estimator.rate_currency_matches"].severity == Severity.ERROR
