# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Stakeholder analysis as pure functions: SPEC rules 2, 3, 4, 5 and 8, plus JSON safety."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.modules.stakeholders import analysis as an
from app.modules.stakeholders.catalogue import DEFAULT_FRAMEWORK_ID, FRAMEWORK_KIND, register_kind


@pytest.fixture(scope="module")
def fw():
    from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

    register_kind()
    return get_catalogue_kind(FRAMEWORK_KIND).get_shipped(DEFAULT_FRAMEWORK_ID)


# ── rule 2: classification is derived from the method's data ──────────────


@pytest.mark.parametrize(
    ("power", "interest", "expected"),
    [
        (5, 5, "manage_closely"),
        (3, 3, "manage_closely"),  # boundary belongs to "high"
        (3, 2, "keep_satisfied"),
        (2, 3, "keep_informed"),
        (2, 2, "monitor"),
        (1, 5, "keep_informed"),
        (5, 1, "keep_satisfied"),
        (1, 1, "monitor"),
    ],
)
def test_power_interest_quadrants_and_boundaries(fw, power, interest, expected) -> None:
    m = fw.method("power_interest")
    assert an.classify(m, an.validate_scores(m, {"power": power, "interest": interest})) == expected


@pytest.mark.parametrize(
    ("p", "lg", "u", "expected"),
    [
        (True, True, True, "definitive"),
        (True, True, False, "dominant"),
        (True, False, True, "dangerous"),
        (False, True, True, "dependent"),
        (True, False, False, "dormant"),
        (False, True, False, "discretionary"),
        (False, False, True, "demanding"),
        (False, False, False, "non_stakeholder"),
    ],
)
def test_salience_seven_classes_and_non_stakeholder(fw, p, lg, u, expected) -> None:
    m = fw.method("salience")
    assert an.classify(m, an.validate_scores(m, {"power": p, "legitimacy": lg, "urgency": u})) == expected


def test_attitude_and_influence_thresholds(fw) -> None:
    att, inf = fw.method("attitude"), fw.method("influence")
    assert [an.classify(att, {"attitude": v}) for v in (-2, -1, 0, 1, 2)] == [
        "resistant",
        "resistant",
        "neutral",
        "supportive",
        "supportive",
    ]
    assert [an.classify(inf, {"influence": v}) for v in (1, 2, 3, 4, 5)] == ["low", "medium", "medium", "high", "high"]


def test_engagement_method_has_no_classification(fw) -> None:
    m = fw.method("engagement_level")
    assert an.classify(m, an.validate_scores(m, {"current": 1, "desired": 3})) is None


@pytest.mark.parametrize(
    ("scores", "problem"),
    [
        ({"power": 3}, ("interest", "missing")),
        ({"power": 0, "interest": 3}, ("power", "out_of_range")),
        ({"power": 6, "interest": 3}, ("power", "out_of_range")),
        ({"power": "3", "interest": 3}, ("power", "not_integer")),
        ({"power": 3.0, "interest": 3}, ("power", "not_integer")),
        ({"power": True, "interest": 3}, ("power", "not_integer")),
        ({"power": 3, "interest": 3, "mood": 1}, ("mood", "unknown_dimension")),
    ],
)
def test_scores_are_validated_against_the_dimensions(fw, scores, problem) -> None:
    with pytest.raises(an.ScoreError) as exc:
        an.validate_scores(fw.method("power_interest"), scores)
    assert problem in exc.value.problems


def test_salience_refuses_non_boolean(fw) -> None:
    with pytest.raises(an.ScoreError) as exc:
        an.validate_scores(fw.method("salience"), {"power": 1, "legitimacy": True, "urgency": False})
    assert ("power", "not_boolean") in exc.value.problems


def test_every_problem_is_reported_at_once(fw) -> None:
    with pytest.raises(an.ScoreError) as exc:
        an.validate_scores(fw.method("power_interest"), {"power": 9})
    assert {d for d, _ in exc.value.problems} == {"power", "interest"}


# ── rule 3: method change keeps history, grid reads the current method ──────


def _a(sid: str, method: str, cls: str | None, day: int) -> an.AssessmentView:
    return an.AssessmentView(sid, method, cls, None, None, datetime(2026, 1, day, tzinfo=UTC))


def test_current_classification_ignores_other_methods_but_review_clock_does_not() -> None:
    rows = [_a("s1", "power_interest", "monitor", 1), _a("s1", "salience", "definitive", 5)]
    assert an.current_classification(rows, "s1", "power_interest").classification == "monitor"
    assert an.current_classification(rows, "s1", "influence") is None  # listed as not_assessed
    assert an.latest_by_stakeholder(rows)["s1"].method_code == "salience"


def test_current_classification_takes_the_newest() -> None:
    rows = [_a("s1", "power_interest", "monitor", 1), _a("s1", "power_interest", "manage_closely", 9)]
    assert an.current_classification(rows, "s1", "power_interest").classification == "manage_closely"


# ── rule 4: review due ────────────────────────────────────────────────────


def test_review_due() -> None:
    today = date(2026, 10, 12)
    old = datetime(2026, 7, 1, tzinfo=UTC)
    fresh = datetime(2026, 9, 1, tzinfo=UTC)
    assert an.review_due(latest_at=old, external=False, interval_days=90, today=today)
    assert not an.review_due(latest_at=fresh, external=True, interval_days=90, today=today)
    assert an.review_due(latest_at=None, external=True, interval_days=90, today=today)
    assert not an.review_due(latest_at=None, external=False, interval_days=90, today=today)
    exactly = datetime(2026, 7, 14, tzinfo=UTC)  # 90 days: not yet older than the interval
    assert not an.review_due(latest_at=exactly, external=True, interval_days=90, today=today)


# ── rule 5: engagement gap ───────────────────────────────────────────────


def test_engagement_gap(fw) -> None:
    assert an.engagement_gap(fw, "neutral", "leading") == 2
    assert an.engagement_gap(fw, "supportive", "supportive") == 0
    assert an.engagement_gap(fw, "leading", "neutral") == -2
    assert an.engagement_gap(fw, None, "leading") is None


# ── rule 8: feedback reported ─────────────────────────────────────────────


def test_feedback_not_reported(fw) -> None:
    held = date(2026, 9, 1)
    kw = {"status": "held", "held_on": held, "feedback_summary": ""}
    assert an.feedback_not_reported(fw, level="consult", today=date(2026, 10, 2), **kw)
    assert not an.feedback_not_reported(fw, level="consult", today=date(2026, 10, 1), **kw)  # day 30
    assert not an.feedback_not_reported(fw, level="inform", today=date(2026, 12, 1), **kw)  # no promise
    assert an.feedback_not_reported(fw, level="empower", today=date(2026, 12, 1), **kw)
    done = {**kw, "feedback_summary": "Reported in newsletter 4"}
    assert not an.feedback_not_reported(fw, level="consult", today=date(2026, 12, 1), **done)
    planned = {**kw, "status": "planned"}
    assert not an.feedback_not_reported(fw, level="consult", today=date(2026, 12, 1), **planned)


# ── JSON columns ─────────────────────────────────────────────────────────


def test_jsonable_turns_every_scalar_into_json() -> None:
    raw = {
        "ids": [uuid.uuid4(), uuid.uuid4()],
        "when": date(2026, 10, 12),
        "at": datetime(2026, 10, 12, 8, tzinfo=UTC),
        "amount": Decimal("250000.00"),
        "nested": ({"d": date(2026, 1, 1)},),
        "set": {"b", "a"},
    }
    out = an.jsonable(raw)
    assert an.assert_json_safe(out) is out
    assert out["amount"] == "250000.00"
    assert out["when"] == "2026-10-12"
    assert out["set"] == ["a", "b"]
    with pytest.raises(TypeError):
        json.dumps(raw)


def test_jsonable_refuses_unknown_objects() -> None:
    with pytest.raises(TypeError):
        an.jsonable({"x": object()})


def test_grid_position(fw) -> None:
    pos = an.grid_position(fw.method("power_interest"), {"power": 4, "interest": 2})
    assert pos == {"x": 2, "y": 4, "x_dim": "interest", "y_dim": "power"}
    sal = an.grid_position(fw.method("salience"), {"power": True, "legitimacy": False, "urgency": True})
    assert sal == {"sets": ["power", "urgency"]}
