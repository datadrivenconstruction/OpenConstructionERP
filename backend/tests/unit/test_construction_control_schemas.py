"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Construction-control schema validation (pure, no DB).

Pins the discriminators that keep one schema serving every phase document and legal
regime: the inspection type (MIR/WIR/IR/hidden-works/acceptance), the party role
(qc/qa/tpi/ahj), the intervention point, the acceptance rule, and the recorded result.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.construction_control.schemas import (
    AcceptanceCriterionCreate,
    ElementRefIn,
    InspectionCreate,
    InspectionResultIn,
)

_PID = uuid.uuid4()


# ── Inspection discriminators ────────────────────────────────────────────────


@pytest.mark.parametrize("itype", ["mir", "wir", "ir", "hidden_works", "acceptance"])
def test_inspection_type_accepts_every_phase(itype):
    insp = InspectionCreate(project_id=_PID, inspection_type=itype, title="x")
    assert insp.inspection_type == itype
    # Default party role is contractor QC.
    assert insp.party_role == "qc"


@pytest.mark.parametrize("bad", ["MIR", "snag", "", "inspection", "accept"])
def test_inspection_type_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        InspectionCreate(project_id=_PID, inspection_type=bad, title="x")


@pytest.mark.parametrize("role", ["qc", "qa", "tpi", "ahj"])
def test_party_role_accepts_every_viewpoint(role):
    insp = InspectionCreate(project_id=_PID, inspection_type="ir", title="x", party_role=role)
    assert insp.party_role == role


@pytest.mark.parametrize("bad", ["client", "engineer", "QA", "owner"])
def test_party_role_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        InspectionCreate(project_id=_PID, inspection_type="ir", title="x", party_role=bad)


@pytest.mark.parametrize("point", ["hold", "witness", "surveillance", "review"])
def test_intervention_point_accepts_hwsr(point):
    insp = InspectionCreate(project_id=_PID, inspection_type="ir", title="x", intervention_point=point)
    assert insp.intervention_point == point


def test_intervention_point_rejects_unknown():
    with pytest.raises(ValidationError):
        InspectionCreate(project_id=_PID, inspection_type="ir", title="x", intervention_point="stop")


def test_title_is_required_and_bounded():
    with pytest.raises(ValidationError):
        InspectionCreate(project_id=_PID, inspection_type="ir", title="")


# ── Acceptance criterion ─────────────────────────────────────────────────────


@pytest.mark.parametrize("rule", ["range", "min", "max", "boolean", "text"])
def test_acceptance_rule_accepts_known(rule):
    crit = AcceptanceCriterionCreate(project_id=_PID, code="AC-1", title="x", acceptance_rule=rule)
    assert crit.acceptance_rule == rule


def test_acceptance_rule_defaults_to_text():
    crit = AcceptanceCriterionCreate(project_id=_PID, code="AC-1", title="x")
    assert crit.acceptance_rule == "text"


def test_acceptance_rule_rejects_unknown():
    with pytest.raises(ValidationError):
        AcceptanceCriterionCreate(project_id=_PID, code="AC-1", title="x", acceptance_rule="between")


# ── Result ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("result", ["pass", "fail", "conditional"])
def test_result_accepts_known(result):
    assert InspectionResultIn(result=result).result == result


@pytest.mark.parametrize("bad", ["passed", "failed", "ok", ""])
def test_result_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        InspectionResultIn(result=bad)


def test_ncr_severity_is_constrained_when_supplied():
    assert InspectionResultIn(result="fail", ncr_severity="critical").ncr_severity == "critical"
    with pytest.raises(ValidationError):
        InspectionResultIn(result="fail", ncr_severity="blocker")


# ── Universal Element Reference inbound ──────────────────────────────────────


def test_element_ref_accepts_partial_identity():
    """A caller may supply only the normalised identity; nothing else is required."""
    ref = ElementRefIn(model_id=uuid.uuid4(), stable_id="2hWqf$0bsdf9R")
    assert ref.bim_element_id is None
    assert ref.ifc_global_id is None  # IFC GlobalId is optional, never required.


def test_element_ref_accepts_pure_denormalised():
    """Field inspector can reference an element by name before the model is ingested."""
    ref = ElementRefIn(element_name="Wall W-12", source_format="revit")
    assert ref.element_name == "Wall W-12"
    assert ref.model_id is None
