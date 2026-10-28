# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the match prior-pick learning loop.

Pure, DB-free coverage of the load-bearing logic:

* the :mod:`app.core.match_service.boosts.prior_pick` boost + context
  (score lift, candidate re-pinning, ContextVar scoping),
* the match-elements service helpers that build the exact-repeat
  candidate and guard the pre-select id parse, and
* the feedback read-model attribution helper.

The end-to-end run_match short-circuit / bind / pin wiring is exercised
by the broader match-elements integration tests against a real DB.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core.match_service.boosts import prior_pick as pp
from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

_ENV = ElementEnvelope(source="text")


def _cand(code: str, *, cid: str | None = None) -> MatchCandidate:
    return MatchCandidate(code=code, id=cid)


# ── PriorPickContext ──────────────────────────────────────────────────────


def test_context_is_empty() -> None:
    assert pp.PriorPickContext().is_empty is True
    assert pp.PriorPickContext(weak=frozenset({"RC-1"})).is_empty is False
    assert pp.PriorPickContext(strong=frozenset({"RC-1"})).is_empty is False


def test_reason_for_template_by_code_and_id() -> None:
    ctx = pp.PriorPickContext(strong=frozenset({"CI-1", "RC-1"}))
    # Strong match by the rate code the vector ranker stamps.
    assert ctx.reason_for(_cand("RC-1")) == pp.REASON_TEMPLATE
    # Strong match by the real CostItem id (resources / short-circuit).
    assert ctx.reason_for(_cand("ZZ", cid="CI-1")) == pp.REASON_TEMPLATE


def test_reason_for_history_and_none() -> None:
    ctx = pp.PriorPickContext(strong=frozenset({"RC-1"}), weak=frozenset({"RC-2"}))
    assert ctx.reason_for(_cand("RC-2")) == pp.REASON_HISTORY
    assert ctx.reason_for(_cand("NOPE")) is None


def test_reason_for_strong_wins_over_weak() -> None:
    ctx = pp.PriorPickContext(strong=frozenset({"RC-1"}), weak=frozenset({"RC-1"}))
    assert ctx.reason_for(_cand("RC-1")) == pp.REASON_TEMPLATE


def test_blank_candidate_ids_never_match() -> None:
    # A candidate with no id and empty code must not collide with an empty
    # string that slipped into the sets.
    ctx = pp.PriorPickContext(strong=frozenset({""}), weak=frozenset({""}))
    assert ctx.reason_for(MatchCandidate(code="")) is None


# ── boost ─────────────────────────────────────────────────────────────────


def test_boost_no_op_when_unbound() -> None:
    # Nothing bound (the ad-hoc / eval path) -> zero cost.
    assert pp.boost(_ENV, _cand("RC-1"), None) == {}


def test_boost_template_and_history_weights() -> None:
    ctx = pp.PriorPickContext(strong=frozenset({"RC-1"}), weak=frozenset({"RC-2"}))
    with pp.applied(ctx):
        assert pp.boost(_ENV, _cand("RC-1"), None) == {pp.BOOST_KEY: pp.PRIOR_PICK_TEMPLATE_WEIGHT}
        assert pp.boost(_ENV, _cand("RC-2"), None) == {pp.BOOST_KEY: pp.PRIOR_PICK_HISTORY_WEIGHT}
        assert pp.boost(_ENV, _cand("OTHER"), None) == {}


def test_boost_template_weight_is_stronger_than_history() -> None:
    assert pp.PRIOR_PICK_TEMPLATE_WEIGHT > pp.PRIOR_PICK_HISTORY_WEIGHT > 0.0


def test_applied_restores_previous_context() -> None:
    assert pp.active() is None
    ctx = pp.PriorPickContext(weak=frozenset({"RC-2"}))
    with pp.applied(ctx):
        assert pp.active() is ctx
    # ContextVar must be reset so the next group / caller starts clean.
    assert pp.active() is None


def test_bind_reset_roundtrip() -> None:
    ctx = pp.PriorPickContext(strong=frozenset({"RC-1"}))
    token = pp.bind(ctx)
    try:
        assert pp.active() is ctx
    finally:
        pp.reset(token)
    assert pp.active() is None


# ── pin_candidates ────────────────────────────────────────────────────────


def test_pin_orders_strong_then_history_then_rest_stably() -> None:
    ctx = pp.PriorPickContext(strong=frozenset({"RC-1"}), weak=frozenset({"RC-2"}))
    ordered = pp.pin_candidates(
        [_cand("A"), _cand("RC-2"), _cand("RC-1"), _cand("B")],
        ctx,
    )
    assert [c.code for c in ordered] == ["RC-1", "RC-2", "A", "B"]


def test_pin_is_noop_when_no_hits() -> None:
    ctx = pp.PriorPickContext(strong=frozenset({"RC-9"}))
    original = [_cand("A"), _cand("B")]
    # Same list object back -> the caller keeps the ranker's ordering.
    assert pp.pin_candidates(original, ctx) is original


def test_pin_is_noop_for_empty_context() -> None:
    original = [_cand("A")]
    assert pp.pin_candidates(original, pp.PriorPickContext()) is original
    assert pp.pin_candidates(original, None) is original


# ── ranker registration ───────────────────────────────────────────────────


def test_boost_registered_in_ranker_stack() -> None:
    from app.core.match_service.ranker_qdrant import _BOOSTS

    assert pp.boost in _BOOSTS
    # Prior-pick leads the stack so a confirmed code is lifted before the
    # confidence band is derived.
    assert _BOOSTS[0] is pp.boost


# ── service helpers (exact-repeat candidate + safe pre-select) ────────────


def test_coerce_cost_item_uuid() -> None:
    from app.modules.match_elements.service import _coerce_cost_item_uuid

    real = "11111111-1111-1111-1111-111111111111"
    assert _coerce_cost_item_uuid(real) == uuid.UUID(real)
    # The vector ranker stamps the rate code on ``id`` - it must never
    # resolve (and must never raise, which would abort the whole run).
    assert _coerce_cost_item_uuid("01.02.003") is None
    assert _coerce_cost_item_uuid(None) is None
    assert _coerce_cost_item_uuid("") is None


def test_candidate_from_cost_item() -> None:
    from app.modules.match_elements.service import (
        _candidate_from_cost_item,
        _coerce_cost_item_uuid,
    )

    item = SimpleNamespace(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        code="RC-9",
        description="Reinforced concrete wall C30/37",
        unit="m3",
        rate="123.45",
        currency="EUR",
        region="DE_BERLIN",
        classification={"din276": "330"},
    )
    cand = _candidate_from_cost_item(item, "RC-9")
    # Real row id so the downstream pre-select links a live CostItem.
    assert cand.id == "22222222-2222-2222-2222-222222222222"
    assert _coerce_cost_item_uuid(cand.id) == item.id
    assert cand.code == "RC-9"
    assert cand.unit == "m3"
    assert cand.unit_rate == 123.45
    assert cand.currency == "EUR"
    assert cand.region_code == "DE_BERLIN"
    assert cand.source == "prior_pick"
    assert cand.confidence_band == "high"
    assert cand.score == 1.0
    assert pp.BOOST_KEY in cand.boosts_applied
    assert cand.classification == {"din276": "330"}
    assert cand.reasoning


# ── feedback read-model attribution ───────────────────────────────────────


def test_picked_rank_for_code() -> None:
    from app.core.match_service.feedback import _picked_rank_for_code

    assert _picked_rank_for_code(["A", "B", "C"], "B") == 2
    assert _picked_rank_for_code(["A", "B"], "Z") is None
    assert _picked_rank_for_code([], "A") is None
    assert _picked_rank_for_code(None, "A") is None
    assert _picked_rank_for_code(["A"], "") is None
    # Whitespace-tolerant on both sides.
    assert _picked_rank_for_code(["  B  "], "B") == 1
