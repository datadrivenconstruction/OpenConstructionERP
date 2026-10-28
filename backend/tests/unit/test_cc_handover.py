"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Construction-control Pillar 4 (handover) schema + pure-logic tests (no DB).

Pins the handover discriminators (completion regime, completion type), the regime ->
certificate-title mapping, the create/issue/override schema validation, and the SHA-256
issue-signature determinism that backs the e-signed acceptance certificate.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.construction_control.handover_service import certificate_title_for
from app.modules.construction_control.schemas import (
    HandoverIssueIn,
    HandoverOverrideIn,
    HandoverPackageCreate,
    HandoverPackageUpdate,
)
from app.modules.construction_control.signing import snapshot_sha256

_PID = uuid.uuid4()


# ── Completion-regime discriminator ────────────────────────────────────────────


@pytest.mark.parametrize("regime", ["taking_over", "substantial", "practical"])
def test_completion_regime_accepts_known(regime):
    assert (
        HandoverPackageCreate(project_id=_PID, title="Handover", completion_regime=regime).completion_regime == regime
    )


def test_completion_regime_defaults_to_taking_over():
    assert HandoverPackageCreate(project_id=_PID, title="x").completion_regime == "taking_over"


@pytest.mark.parametrize("bad", ["completion", "final", "handover", ""])
def test_completion_regime_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        HandoverPackageCreate(project_id=_PID, title="x", completion_regime=bad)


# ── Completion-type discriminator ──────────────────────────────────────────────


@pytest.mark.parametrize("ctype", ["whole", "sectional", "partial"])
def test_completion_type_accepts_known(ctype):
    assert HandoverPackageCreate(project_id=_PID, title="x", completion_type=ctype).completion_type == ctype


def test_completion_type_defaults_to_whole():
    assert HandoverPackageCreate(project_id=_PID, title="x").completion_type == "whole"


@pytest.mark.parametrize("bad", ["section", "full", "phase", ""])
def test_completion_type_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        HandoverPackageCreate(project_id=_PID, title="x", completion_type=bad)


def test_handover_title_required():
    with pytest.raises(ValidationError):
        HandoverPackageCreate(project_id=_PID, title="")


def test_handover_update_status_is_not_a_field():
    # Status transitions go through assemble/issue/revoke, never a plain update.
    assert "status" not in HandoverPackageUpdate.model_fields
    # Nor are the gate counters or the signature directly writable.
    assert "gating_state" not in HandoverPackageUpdate.model_fields
    assert "issue_signature_sha256" not in HandoverPackageUpdate.model_fields


def test_override_reason_required():
    assert HandoverOverrideIn(reason="FIDIC snag-list taking-over agreed").reason
    with pytest.raises(ValidationError):
        HandoverOverrideIn(reason="")
    with pytest.raises(ValidationError):
        HandoverOverrideIn()


def test_override_severity_validated():
    assert HandoverOverrideIn(reason="x", ncr_severity="major").ncr_severity == "major"
    with pytest.raises(ValidationError):
        HandoverOverrideIn(reason="x", ncr_severity="blocker")


def test_issue_certificate_no_optional():
    # The certificate number is optional at issue (the service derives a default).
    assert HandoverIssueIn().certificate_no is None
    assert HandoverIssueIn(certificate_no="TOC-2026-001").certificate_no == "TOC-2026-001"


# ── Regime -> certificate title (pure) ─────────────────────────────────────────


def test_certificate_title_for_known_regimes():
    assert certificate_title_for("taking_over") == "Taking-Over Certificate"
    assert certificate_title_for("substantial") == "Certificate of Substantial Completion"
    assert certificate_title_for("practical") == "Certificate of Practical Completion"


def test_certificate_title_for_unknown_regime_falls_back():
    assert certificate_title_for("bogus") == "Acceptance Certificate"


# ── Issue signature determinism ────────────────────────────────────────────────


def test_issue_signature_deterministic_and_content_sensitive():
    snap = {
        "package_number": "HOP-001",
        "project_id": str(_PID),
        "completion_regime": "taking_over",
        "certificate_no": "CERT-HOP-001",
        "gating_state": "clear",
        "issued_by": "user-1",
    }
    again = dict(reversed(list(snap.items())))
    # Key order does not change the digest (canonical, sorted serialisation).
    assert snapshot_sha256(snap) == snapshot_sha256(again)
    assert len(snapshot_sha256(snap)) == 64

    # A different gate state (e.g. issued under override) yields a different digest.
    other = {**snap, "gating_state": "overridden"}
    assert snapshot_sha256(snap) != snapshot_sha256(other)
