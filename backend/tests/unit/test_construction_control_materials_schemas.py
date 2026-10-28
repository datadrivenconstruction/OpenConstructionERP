"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Construction-control Pillar 2 schema validation (pure, no DB).

Pins the discriminators that keep the material passport and test-result schemas honest:
the EN 10204 / EU CPR certificate grade, the create- vs update-time status grammar, the
review decision and recorded test result, and the bounded specimen age.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.construction_control.schemas import (
    MaterialRecordCreate,
    MaterialRecordUpdate,
    MaterialReviewIn,
    TestResultCreate,
    TestResultRecordIn,
    TestResultUpdate,
)

_PID = uuid.uuid4()


# ── Material certificate grade (EN 10204 + EU CPR / UKCA) ─────────────────────


@pytest.mark.parametrize("cert", ["2.1", "2.2", "3.1", "3.2", "dop", "ce", "ukca", "coc", "other"])
def test_cert_type_accepts_en10204_and_cpr_grades(cert):
    mat = MaterialRecordCreate(project_id=_PID, name="Rebar B500B", cert_type=cert)
    assert mat.cert_type == cert


@pytest.mark.parametrize("bad", ["4.1", "1.0", "A", "EN10204", "3", "2-1", ""])
def test_cert_type_rejects_unknown_grade(bad):
    with pytest.raises(ValidationError):
        MaterialRecordCreate(project_id=_PID, name="x", cert_type=bad)


# ── Material lifecycle status: create vs update grammar ───────────────────────


@pytest.mark.parametrize("status", ["draft", "submitted"])
def test_material_create_status_allows_only_pre_decision(status):
    assert MaterialRecordCreate(project_id=_PID, name="x", status=status).status == status


def test_material_create_status_defaults_to_draft():
    assert MaterialRecordCreate(project_id=_PID, name="x").status == "draft"


@pytest.mark.parametrize("bad", ["accepted", "rejected", "under_review", "expired", "superseded"])
def test_material_create_status_rejects_decision_states(bad):
    """A decision is reached only through the review endpoint, never a plain create."""
    with pytest.raises(ValidationError):
        MaterialRecordCreate(project_id=_PID, name="x", status=bad)


@pytest.mark.parametrize("status", ["draft", "submitted", "under_review", "superseded"])
def test_material_update_status_allows_open_states(status):
    assert MaterialRecordUpdate(status=status).status == status


@pytest.mark.parametrize("bad", ["accepted", "rejected", "expired", "withdrawn"])
def test_material_update_status_rejects_decision_states(bad):
    with pytest.raises(ValidationError):
        MaterialRecordUpdate(status=bad)


def test_material_name_is_required():
    with pytest.raises(ValidationError):
        MaterialRecordCreate(project_id=_PID, name="")


def test_material_ce_ukca_default_false():
    mat = MaterialRecordCreate(project_id=_PID, name="x")
    assert mat.ce_marking is False
    assert mat.ukca_marking is False


# ── Material review decision ──────────────────────────────────────────────────


@pytest.mark.parametrize("decision", ["pass", "fail", "conditional"])
def test_material_review_decision_accepts_result_grammar(decision):
    assert MaterialReviewIn(decision=decision).decision == decision


@pytest.mark.parametrize("bad", ["accept", "reject", "approved", "ok", ""])
def test_material_review_decision_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        MaterialReviewIn(decision=bad)


def test_material_review_ncr_severity_is_constrained():
    assert MaterialReviewIn(decision="fail", ncr_severity="critical").ncr_severity == "critical"
    with pytest.raises(ValidationError):
        MaterialReviewIn(decision="fail", ncr_severity="blocker")


# ── Test result ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("result", ["pass", "fail", "conditional"])
def test_test_result_accepts_result_grammar(result):
    assert TestResultRecordIn(result=result).result == result


@pytest.mark.parametrize("bad", ["passed", "failed", "void", ""])
def test_test_result_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        TestResultRecordIn(result=bad)


def test_test_result_title_required():
    with pytest.raises(ValidationError):
        TestResultCreate(project_id=_PID, title="")


def test_test_specimen_age_is_non_negative():
    assert TestResultCreate(project_id=_PID, title="Cube 28d", specimen_age_days=28).specimen_age_days == 28
    assert TestResultCreate(project_id=_PID, title="t", specimen_age_days=0).specimen_age_days == 0
    with pytest.raises(ValidationError):
        TestResultCreate(project_id=_PID, title="t", specimen_age_days=-1)


@pytest.mark.parametrize("status", ["draft", "recorded", "void"])
def test_test_update_status_accepts_known(status):
    assert TestResultUpdate(status=status).status == status


@pytest.mark.parametrize("bad", ["failed", "passed", "closed"])
def test_test_update_status_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        TestResultUpdate(status=bad)
