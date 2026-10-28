"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Construction-control Pillar 5 (gating) schema + pure-logic tests (no DB).

Pins the gate discriminators (point type, attached kind, required party role), the
party-role satisfaction rule that backs defence-in-depth release (a qc cannot release an
ahj gate), and the SHA-256 release-signature determinism.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.construction_control.gating_service import party_role_satisfies
from app.modules.construction_control.schemas import (
    HoldGateCreate,
    HoldGateReleaseIn,
    HoldGateUpdate,
    HoldGateWaiveIn,
)
from app.modules.construction_control.signing import snapshot_sha256

_PID = uuid.uuid4()


# ── Gate discriminators ────────────────────────────────────────────────────────


@pytest.mark.parametrize("pt", ["hold", "witness", "surveillance", "review"])
def test_point_type_accepts_known(pt):
    assert HoldGateCreate(project_id=_PID, title="Gate", point_type=pt).point_type == pt


@pytest.mark.parametrize("bad", ["block", "stop", "checkpoint", ""])
def test_point_type_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        HoldGateCreate(project_id=_PID, title="x", point_type=bad)


def test_point_type_defaults_to_hold():
    assert HoldGateCreate(project_id=_PID, title="x").point_type == "hold"


@pytest.mark.parametrize("role", ["qc", "qa", "tpi", "ahj"])
def test_required_party_role_accepts_known(role):
    assert HoldGateCreate(project_id=_PID, title="x", required_party_role=role).required_party_role == role


def test_required_party_role_defaults_to_qa():
    assert HoldGateCreate(project_id=_PID, title="x").required_party_role == "qa"


@pytest.mark.parametrize("bad", ["client", "engineer", "owner", ""])
def test_required_party_role_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        HoldGateCreate(project_id=_PID, title="x", required_party_role=bad)


@pytest.mark.parametrize("kind", ["activity", "handover_package", "inspection"])
def test_attached_kind_accepts_known(kind):
    # attached_kind and attached_id must be set together (a kind with no id can
    # never match the enforcement lookup), so pair the known kind with an id.
    gate = HoldGateCreate(project_id=_PID, title="x", attached_kind=kind, attached_id="elem-1")
    assert gate.attached_kind == kind


@pytest.mark.parametrize("bad", ["task", "package", "boq", ""])
def test_attached_kind_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        HoldGateCreate(project_id=_PID, title="x", attached_kind=bad)


def test_gate_blocks_progress_optional_at_create():
    # Omitted -> None so the service can derive it from point_type.
    assert HoldGateCreate(project_id=_PID, title="x").blocks_progress is None
    assert HoldGateCreate(project_id=_PID, title="x", blocks_progress=True).blocks_progress is True


def test_gate_title_required():
    with pytest.raises(ValidationError):
        HoldGateCreate(project_id=_PID, title="")


def test_gate_release_party_role_required():
    assert HoldGateReleaseIn(party_role="qa").party_role == "qa"
    with pytest.raises(ValidationError):
        HoldGateReleaseIn()
    with pytest.raises(ValidationError):
        HoldGateReleaseIn(party_role="owner")


def test_gate_waive_reason_required():
    assert HoldGateWaiveIn(reason="advisory point, no witness needed").reason
    with pytest.raises(ValidationError):
        HoldGateWaiveIn(reason="")


def test_gate_update_status_is_not_a_field():
    # Status transitions go through release/waive/void, never a plain update.
    assert "status" not in HoldGateUpdate.model_fields


# ── Party-role satisfaction (pure, defence in depth) ──────────────────────────


def test_party_role_equal_satisfies():
    for role in ("qc", "qa", "tpi", "ahj"):
        assert party_role_satisfies(role, role) is True


def test_higher_authority_satisfies_lower_requirement():
    assert party_role_satisfies("ahj", "qa") is True
    assert party_role_satisfies("tpi", "qc") is True
    assert party_role_satisfies("qa", "qc") is True


def test_lower_authority_cannot_satisfy_higher_requirement():
    # The headline rule: a contractor QC cannot release an authority gate.
    assert party_role_satisfies("qc", "ahj") is False
    assert party_role_satisfies("qc", "qa") is False
    assert party_role_satisfies("qa", "tpi") is False


def test_unknown_role_only_satisfies_itself():
    assert party_role_satisfies("bogus", "qa") is False
    assert party_role_satisfies("qa", "bogus") is False


# ── Release signature determinism ─────────────────────────────────────────────


def test_release_signature_deterministic_and_content_sensitive():
    snap = {
        "gate_number": "GATE-001",
        "point_type": "hold",
        "attached_kind": "activity",
        "attached_id": "act-1",
        "released_party_role": "qa",
    }
    again = dict(reversed(list(snap.items())))
    assert snapshot_sha256(snap) == snapshot_sha256(again)

    other = {**snap, "released_party_role": "ahj"}
    assert snapshot_sha256(snap) != snapshot_sha256(other)
