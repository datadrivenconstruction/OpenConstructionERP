# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the pure CDE readiness engine.

No database, no app fixtures - the engine is stdlib-only, so these run on the
local Python 3.11 runner exactly like the other pure-engine tests.
"""

from app.modules.cde import readiness as rdy

ALL_KEYS = frozenset(rdy.signal_keys())
TOTAL_WEIGHT = sum(s.weight for s in rdy.READINESS_SIGNALS)


def test_catalogue_is_well_formed():
    keys = rdy.signal_keys()
    assert len(keys) == len(set(keys)), "signal keys must be unique"
    assert len(keys) >= 8
    for s in rdy.READINESS_SIGNALS:
        assert s.key and s.label and s.hint, "every signal is fully described"
        assert s.weight > 0, "weights are positive so nothing subtracts from readiness"


def test_total_weight_matches_expectation():
    # Guards against an accidental weight edit silently reshaping the score.
    assert TOTAL_WEIGHT == 17


def test_empty_is_not_started():
    r = rdy.evaluate(frozenset())
    assert r.score == 0
    assert r.level == "not_started"
    assert all(not s.done for s in r.signals)
    # next actions are the first N unmet signals, in catalogue order
    assert [s.key for s in r.next_actions] == list(rdy.signal_keys())[: rdy.DEFAULT_NEXT_ACTIONS]


def test_all_met_is_mature_hundred():
    r = rdy.evaluate(ALL_KEYS)
    assert r.score == 100
    assert r.level == "mature"
    assert all(s.done for s in r.signals)
    assert r.next_actions == ()


def test_score_is_weighted_percent():
    # containers_created (2) + structured_naming (2) = 4 / 17 -> 24
    observed = frozenset({"containers_created", "structured_naming"})
    r = rdy.evaluate(observed)
    assert r.score == round(4 * 100 / TOTAL_WEIGHT)
    assert r.score == 24
    assert r.level == "forming"


def test_heavier_signal_moves_score_more():
    light = rdy.evaluate(frozenset({"classification_used"}))  # weight 1
    heavy = rdy.evaluate(frozenset({"published_reached"}))  # weight 3
    assert heavy.score > light.score
    assert light.score == round(1 * 100 / TOTAL_WEIGHT)
    assert heavy.score == round(3 * 100 / TOTAL_WEIGHT)


def test_unknown_keys_never_inflate():
    r = rdy.evaluate(frozenset({"not_a_signal", "also_bogus"}))
    assert r.score == 0
    assert r.level == "not_started"


def test_adding_a_key_never_lowers_score():
    base = rdy.evaluate(frozenset({"containers_created"}))
    more = rdy.evaluate(frozenset({"containers_created", "published_reached"}))
    assert more.score >= base.score


def test_next_actions_cap_and_order():
    # one met -> the remaining unmet lead the nudge, in catalogue order, capped
    r = rdy.evaluate(frozenset({"containers_created"}), next_actions_limit=2)
    assert len(r.next_actions) == 2
    remaining = [k for k in rdy.signal_keys() if k != "containers_created"]
    assert [s.key for s in r.next_actions] == remaining[:2]


def test_next_actions_limit_zero():
    r = rdy.evaluate(ALL_KEYS - {"lifecycle_archived"}, next_actions_limit=0)
    assert r.next_actions == ()


def test_level_bands():
    assert rdy.readiness_level(0) == "not_started"
    assert rdy.readiness_level(1) == "forming"
    assert rdy.readiness_level(49) == "forming"
    assert rdy.readiness_level(50) == "operational"
    assert rdy.readiness_level(84) == "operational"
    assert rdy.readiness_level(85) == "mature"
    assert rdy.readiness_level(100) == "mature"


def test_deterministic():
    observed = frozenset({"containers_created", "suitability_assigned", "shared_reached"})
    a = rdy.evaluate(observed)
    b = rdy.evaluate(observed)
    assert a == b


def test_status_lines_up_one_per_signal():
    r = rdy.evaluate(frozenset({"suitability_assigned"}))
    assert len(r.signals) == len(rdy.READINESS_SIGNALS)
    by_key = {s.signal.key: s.done for s in r.signals}
    assert by_key["suitability_assigned"] is True
    assert by_key["containers_created"] is False
