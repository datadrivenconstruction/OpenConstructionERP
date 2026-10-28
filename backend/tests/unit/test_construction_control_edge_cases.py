"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Construction-control edge-case guards (pure, no DB).

Covers the conservative validation added so a real user cannot save a self-contradictory
record and so international behaviour stays consistent:

* an acceptance criterion whose ``range`` bounds are inverted (would reject every value),
* a material certificate whose validity window ends before it starts,
* a hold gate attached to a kind without an id (or the reverse), which would silently
  never block anything,
* certificate-expiry judged against the UTC calendar date, not the server's local one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.construction_control.schemas import (
    AcceptanceCriterionCreate,
    AcceptanceCriterionUpdate,
    HoldGateCreate,
    MaterialRecordCreate,
    MaterialRecordUpdate,
)
from app.modules.construction_control.service import is_material_expired

_PID = uuid.uuid4()


# ── Acceptance criterion: range bounds must be ordered ────────────────────────


def test_range_criterion_accepts_ordered_bounds():
    crit = AcceptanceCriterionCreate(
        project_id=_PID,
        code="AC-1",
        title="Slab level",
        acceptance_rule="range",
        tolerance_lower="-5",
        tolerance_upper="5",
    )
    assert crit.tolerance_lower == "-5"


def test_range_criterion_accepts_equal_bounds():
    crit = AcceptanceCriterionCreate(
        project_id=_PID,
        code="AC-1",
        title="x",
        acceptance_rule="range",
        tolerance_lower="10",
        tolerance_upper="10",
    )
    assert crit.tolerance_upper == "10"


def test_range_criterion_rejects_inverted_bounds():
    with pytest.raises(ValidationError):
        AcceptanceCriterionCreate(
            project_id=_PID,
            code="AC-1",
            title="x",
            acceptance_rule="range",
            tolerance_lower="5",
            tolerance_upper="-5",
        )


def test_range_criterion_rejects_inverted_decimal_bounds():
    with pytest.raises(ValidationError):
        AcceptanceCriterionCreate(
            project_id=_PID,
            code="AC-1",
            title="x",
            acceptance_rule="range",
            tolerance_lower="12.51",
            tolerance_upper="12.50",
        )


def test_range_criterion_skips_check_for_non_numeric_bounds():
    """A non-numeric (free-text) bound is left alone; only plain numbers are compared."""
    crit = AcceptanceCriterionCreate(
        project_id=_PID,
        code="AC-1",
        title="x",
        acceptance_rule="range",
        tolerance_lower="see note",
        tolerance_upper="1",
    )
    assert crit.tolerance_lower == "see note"


def test_range_criterion_allows_partial_bounds():
    """One bound alone cannot be inverted, so a half-filled range is accepted."""
    crit = AcceptanceCriterionCreate(
        project_id=_PID,
        code="AC-1",
        title="x",
        acceptance_rule="range",
        tolerance_lower="5",
    )
    assert crit.tolerance_upper is None


def test_min_max_rules_ignore_bound_order():
    """min / max read a single bound; the ordering guard is a range-only concern."""
    lo = AcceptanceCriterionCreate(
        project_id=_PID,
        code="AC-1",
        title="x",
        acceptance_rule="min",
        tolerance_lower="30",
        tolerance_upper="5",
    )
    assert lo.acceptance_rule == "min"
    hi = AcceptanceCriterionCreate(
        project_id=_PID,
        code="AC-1",
        title="x",
        acceptance_rule="max",
        tolerance_lower="30",
        tolerance_upper="5",
    )
    assert hi.acceptance_rule == "max"


def test_criterion_update_rejects_inverted_range_in_same_patch():
    with pytest.raises(ValidationError):
        AcceptanceCriterionUpdate(acceptance_rule="range", tolerance_lower="9", tolerance_upper="1")


def test_criterion_update_without_rule_skips_range_check():
    """A patch touching bounds but not the rule cannot know the stored rule, so it passes."""
    upd = AcceptanceCriterionUpdate(tolerance_lower="9", tolerance_upper="1")
    assert upd.tolerance_lower == "9"


# ── Material certificate: validity window must be ordered ──────────────────────


def test_material_accepts_ordered_validity_window():
    mat = MaterialRecordCreate(
        project_id=_PID,
        name="Rebar B500B",
        valid_from="2026-01-01",
        valid_until="2027-01-01",
    )
    assert mat.valid_until == "2027-01-01"


def test_material_accepts_equal_validity_dates():
    mat = MaterialRecordCreate(
        project_id=_PID,
        name="x",
        valid_from="2026-06-01",
        valid_until="2026-06-01",
    )
    assert mat.valid_from == "2026-06-01"


def test_material_rejects_inverted_validity_window():
    with pytest.raises(ValidationError):
        MaterialRecordCreate(
            project_id=_PID,
            name="x",
            valid_from="2027-01-01",
            valid_until="2026-01-01",
        )


def test_material_accepts_single_validity_date():
    """Only one date given cannot be inverted; it is accepted."""
    assert MaterialRecordCreate(project_id=_PID, name="x", valid_until="2027-01-01").valid_from is None


def test_material_validity_reads_datetime_strings():
    with pytest.raises(ValidationError):
        MaterialRecordCreate(
            project_id=_PID,
            name="x",
            valid_from="2027-01-01T08:00:00Z",
            valid_until="2026-12-31T23:59:59Z",
        )


def test_material_validity_skips_non_iso_dates():
    """A non-ISO date is not second-guessed; the guard only compares parseable ISO dates."""
    mat = MaterialRecordCreate(project_id=_PID, name="x", valid_from="01/01/2027", valid_until="01/01/2026")
    assert mat.valid_from == "01/01/2027"


def test_material_update_rejects_inverted_window_when_both_present():
    with pytest.raises(ValidationError):
        MaterialRecordUpdate(valid_from="2027-01-01", valid_until="2026-01-01")


def test_material_update_single_date_is_accepted():
    assert MaterialRecordUpdate(valid_until="2026-01-01").valid_until == "2026-01-01"


# ── Hold gate: attachment kind and id come together ───────────────────────────


def test_gate_accepts_both_attachment_fields():
    gate = HoldGateCreate(
        project_id=_PID,
        title="Rebar before pour",
        attached_kind="activity",
        attached_id="act-1",
    )
    assert gate.attached_kind == "activity"


def test_gate_accepts_neither_attachment_field():
    gate = HoldGateCreate(project_id=_PID, title="Standing hold")
    assert gate.attached_kind is None
    assert gate.attached_id is None


def test_gate_rejects_kind_without_id():
    with pytest.raises(ValidationError):
        HoldGateCreate(project_id=_PID, title="x", attached_kind="activity")


def test_gate_rejects_id_without_kind():
    with pytest.raises(ValidationError):
        HoldGateCreate(project_id=_PID, title="x", attached_id="act-1")


# ── Certificate expiry judged in UTC ──────────────────────────────────────────


def _material(valid_until: str | None) -> SimpleNamespace:
    return SimpleNamespace(valid_until=valid_until)


def test_expiry_true_for_clearly_past_date():
    assert is_material_expired(_material("2000-01-01")) is True


def test_expiry_false_for_far_future_date():
    assert is_material_expired(_material("2999-12-31")) is False


def test_expiry_false_for_missing_or_unparseable_date():
    assert is_material_expired(_material(None)) is False
    assert is_material_expired(_material("")) is False
    assert is_material_expired(_material("not-a-date")) is False


def test_expiry_reads_datetime_string():
    assert is_material_expired(_material("1999-06-01T12:00:00Z")) is True


def test_expiry_uses_utc_today_boundary():
    """Yesterday (UTC) is expired, tomorrow is not - the boundary is the UTC calendar day."""
    today = datetime.now(UTC).date()
    assert is_material_expired(_material((today - timedelta(days=1)).isoformat())) is True
    assert is_material_expired(_material((today + timedelta(days=1)).isoformat())) is False
    # The certificate is valid through its last day: today itself is not yet past.
    assert is_material_expired(_material(today.isoformat())) is False
