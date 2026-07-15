# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""E1 Readiness Engine — pure classification truth table + determinism.

Unit tests for ``readiness_engine`` with no DB and no clock. Focus areas:
    * the Ready / At-risk / Blocked truth table (every rule that fires),
    * the correctness catch: raw ``cannot_clear`` rows classify as BLOCKED
      (``schedule_advanced.constraint_ready_state`` would skip them),
    * binding-constraint selection and P4 driver traceability,
    * float-burn detection vs a prior snapshot,
    * uniform E5.3 confidence + its degradation when CPM float is unresolved,
    * determinism: identical inputs → identical verdict and ``run_digest``.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.modules.schedule_intelligence.enums import ConfidenceBand, ReadinessClass
from app.modules.schedule_intelligence.readiness_engine import (
    AT_RISK_FLOAT_DAYS,
    NEAR_HORIZON_DAYS,
    ActivityInput,
    ConstraintInput,
    classify_activity,
    evaluate_look_ahead,
    run_digest,
)

TODAY = date(2026, 7, 15)


def _c(ref: str, status: str, target: date | None = None, ctype: str = "material") -> ConstraintInput:
    return ConstraintInput(ref=ref, status=status, target_clear_date=target, constraint_type=ctype)


# ─────────────────────────────────────────────────────────────────────────────
# READY
# ─────────────────────────────────────────────────────────────────────────────
def test_no_constraints_healthy_float_is_ready() -> None:
    v = classify_activity(ActivityInput(task_ref="t", constraints=(), total_float=10), TODAY)
    assert v.classification is ReadinessClass.READY
    assert v.binding_constraint_ref is None
    assert v.drivers  # never empty — a "clear" driver is emitted


def test_cleared_constraints_do_not_block() -> None:
    v = classify_activity(
        ActivityInput(task_ref="t", constraints=(_c("c1", "cleared"), _c("c2", "cleared")), total_float=5),
        TODAY,
    )
    assert v.classification is ReadinessClass.READY


def test_unknown_float_but_no_constraints_is_ready() -> None:
    v = classify_activity(ActivityInput(task_ref="t", constraints=()), TODAY)
    assert v.classification is ReadinessClass.READY


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKED
# ─────────────────────────────────────────────────────────────────────────────
def test_cannot_clear_is_blocked_not_ready() -> None:
    """The correctness catch: a raw ``cannot_clear`` row must block."""
    v = classify_activity(
        ActivityInput(task_ref="t", constraints=(_c("c1", "cannot_clear", ctype="permit"),), total_float=99),
        TODAY,
    )
    assert v.classification is ReadinessClass.BLOCKED
    assert v.binding_constraint_ref == "c1"
    assert any(d["type"] == "constraint" and d["ref"] == "c1" for d in v.drivers)


def test_open_constraint_targeting_after_need_by_is_blocked() -> None:
    need_by = TODAY + timedelta(days=10)
    late = need_by + timedelta(days=3)
    v = classify_activity(
        ActivityInput(
            task_ref="t",
            constraints=(_c("c1", "open", target=late),),
            need_by_date=need_by,
            total_float=20,
        ),
        TODAY,
    )
    assert v.classification is ReadinessClass.BLOCKED
    assert v.binding_constraint_ref == "c1"


def test_undated_open_constraint_near_horizon_is_blocked() -> None:
    need_by = TODAY + timedelta(days=NEAR_HORIZON_DAYS - 1)
    v = classify_activity(
        ActivityInput(
            task_ref="t",
            constraints=(_c("c1", "open", target=None),),
            need_by_date=need_by,
            total_float=20,
        ),
        TODAY,
    )
    assert v.classification is ReadinessClass.BLOCKED


def test_zero_float_with_open_blocker_is_blocked() -> None:
    v = classify_activity(
        ActivityInput(task_ref="t", constraints=(_c("c1", "open"),), total_float=0),
        TODAY,
    )
    assert v.classification is ReadinessClass.BLOCKED
    assert any(d["type"] == "float" for d in v.drivers)


# ─────────────────────────────────────────────────────────────────────────────
# AT_RISK
# ─────────────────────────────────────────────────────────────────────────────
def test_open_constraint_clearing_in_time_is_at_risk() -> None:
    need_by = TODAY + timedelta(days=30)
    early = TODAY + timedelta(days=5)
    v = classify_activity(
        ActivityInput(
            task_ref="t",
            constraints=(_c("c1", "open", target=early),),
            need_by_date=need_by,
            total_float=20,
        ),
        TODAY,
    )
    assert v.classification is ReadinessClass.AT_RISK
    assert v.binding_constraint_ref == "c1"


def test_thin_float_alone_is_at_risk() -> None:
    v = classify_activity(
        ActivityInput(task_ref="t", constraints=(), total_float=AT_RISK_FLOAT_DAYS),
        TODAY,
    )
    assert v.classification is ReadinessClass.AT_RISK
    assert any(d["type"] == "float" for d in v.drivers)


def test_float_burn_vs_prior_snapshot_is_at_risk() -> None:
    v = classify_activity(
        ActivityInput(task_ref="t", constraints=(), total_float=8, prior_float=12),
        TODAY,
    )
    assert v.classification is ReadinessClass.AT_RISK
    assert v.float_burn_days == 4  # lost 4 days of float since prior run
    assert any(d["type"] == "float_burn" for d in v.drivers)


def test_no_burn_when_float_grows_or_no_prior() -> None:
    grew = classify_activity(ActivityInput(task_ref="t", constraints=(), total_float=15, prior_float=12), TODAY)
    assert grew.classification is ReadinessClass.READY
    assert grew.float_burn_days == -3  # gained float
    first = classify_activity(ActivityInput(task_ref="t", constraints=(), total_float=15), TODAY)
    assert first.float_burn_days is None


def test_critical_activity_adds_criticality_driver() -> None:
    v = classify_activity(
        ActivityInput(task_ref="t", constraints=(), total_float=1, is_critical=True),
        TODAY,
    )
    assert v.classification is ReadinessClass.AT_RISK
    assert any(d["type"] == "criticality" for d in v.drivers)


# ─────────────────────────────────────────────────────────────────────────────
# Binding selection & drivers (P4)
# ─────────────────────────────────────────────────────────────────────────────
def test_binding_is_deterministic_by_ref_order() -> None:
    v = classify_activity(
        ActivityInput(
            task_ref="t",
            constraints=(_c("c9", "open"), _c("c2", "open"), _c("c5", "open")),
        ),
        TODAY,
    )
    # ref-sorted → the lowest ref binds, stably.
    assert v.binding_constraint_ref == "c2"


def test_every_driver_links_a_source_ref() -> None:
    v = classify_activity(
        ActivityInput(task_ref="t", constraints=(_c("c1", "open"),), total_float=1),
        TODAY,
    )
    assert v.drivers
    for d in v.drivers:
        assert set(d) == {"type", "ref", "detail"}
        assert d["ref"]  # non-empty


# ─────────────────────────────────────────────────────────────────────────────
# Confidence (E5.3, uniform + degradation)
# ─────────────────────────────────────────────────────────────────────────────
def test_confidence_is_high_with_resolved_float() -> None:
    v = classify_activity(ActivityInput(task_ref="t", constraints=(), total_float=10), TODAY)
    assert v.confidence.band is ConfidenceBand.HIGH
    assert v.confidence.score == 0.9


def test_confidence_degrades_when_float_unresolved() -> None:
    resolved = classify_activity(ActivityInput(task_ref="t", constraints=(_c("c1", "open"),), total_float=10), TODAY)
    unresolved = classify_activity(ActivityInput(task_ref="t", constraints=(_c("c1", "open"),)), TODAY)
    assert unresolved.confidence.score < resolved.confidence.score
    # The reduction is stated, never silent (P5).
    assert any(r["step"] == "cap:feed_coverage" for r in unresolved.confidence.rationale)


# ─────────────────────────────────────────────────────────────────────────────
# Determinism (E1.1-AC6)
# ─────────────────────────────────────────────────────────────────────────────
def test_run_digest_is_order_independent_and_stable() -> None:
    a = ActivityInput(task_ref="a", constraints=(_c("c1", "open", target=TODAY),), total_float=3)
    b = ActivityInput(task_ref="b", constraints=(), total_float=10)
    d1 = run_digest([a, b], TODAY)
    d2 = run_digest([b, a], TODAY)
    assert d1 == d2 and len(d1) == 64


def test_run_digest_excludes_prior_float() -> None:
    """Idempotency: a prior snapshot must not change the run id."""
    base = ActivityInput(task_ref="a", constraints=(), total_float=5)
    with_prior = ActivityInput(task_ref="a", constraints=(), total_float=5, prior_float=99)
    assert run_digest([base], TODAY) == run_digest([with_prior], TODAY)


def test_run_digest_changes_with_inputs() -> None:
    a = ActivityInput(task_ref="a", constraints=(_c("c1", "open"),), total_float=5)
    b = ActivityInput(task_ref="a", constraints=(_c("c1", "cannot_clear"),), total_float=5)
    assert run_digest([a], TODAY) != run_digest([b], TODAY)


def test_evaluate_look_ahead_is_sorted_and_deterministic() -> None:
    acts = [
        ActivityInput(task_ref="z", constraints=()),
        ActivityInput(task_ref="a", constraints=(_c("c1", "cannot_clear"),)),
        ActivityInput(task_ref="m", constraints=(_c("c2", "open"),)),
    ]
    r1 = evaluate_look_ahead(acts, TODAY)
    r2 = evaluate_look_ahead(list(reversed(acts)), TODAY)
    assert [r.task_ref for r in r1] == ["a", "m", "z"]
    assert [r.classification for r in r1] == [r.classification for r in r2]
