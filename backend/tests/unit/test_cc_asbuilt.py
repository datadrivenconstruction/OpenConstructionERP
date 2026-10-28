"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Construction-control Pillar 3 (as-built) schema + pure-logic tests (no DB).

Pins the discriminators that keep the as-built schemas honest (capture method, accuracy
class, source kind, the update-time status grammar), the deterministic tolerance
computation against a criterion's bounds, and the SHA-256 signature determinism used for
the legal-record attestation.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.construction_control.asbuilt_service import compute_tolerance_result
from app.modules.construction_control.schemas import (
    AsBuiltImportFromScanIn,
    AsBuiltRecordCreate,
    AsBuiltRecordUpdate,
    AsBuiltSignIn,
    AsBuiltSurveyIn,
)
from app.modules.construction_control.signing import canonical_snapshot, snapshot_sha256

_PID = uuid.uuid4()


def _criterion(rule, *, lower=None, upper=None):
    """A criterion-like object for the pure tolerance computation."""
    return SimpleNamespace(acceptance_rule=rule, tolerance_lower=lower, tolerance_upper=upper)


# ── Capture method / accuracy class / source kind discriminators ──────────────


@pytest.mark.parametrize(
    "method",
    ["laser_scan", "photogrammetry", "total_station", "gnss", "tape", "drone_lidar", "model_extract", "manual"],
)
def test_capture_method_accepts_known(method):
    rec = AsBuiltRecordCreate(project_id=_PID, title="As-built wall", capture_method=method)
    assert rec.capture_method == method


@pytest.mark.parametrize("bad", ["lidar", "scan", "gps", "drone", ""])
def test_capture_method_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        AsBuiltRecordCreate(project_id=_PID, title="x", capture_method=bad)


def test_capture_method_defaults_to_manual():
    assert AsBuiltRecordCreate(project_id=_PID, title="x").capture_method == "manual"


@pytest.mark.parametrize("cls", ["survey", "standard", "coarse"])
def test_accuracy_class_accepts_known(cls):
    assert AsBuiltRecordCreate(project_id=_PID, title="x", accuracy_class=cls).accuracy_class == cls


@pytest.mark.parametrize("bad", ["precise", "high", "low", ""])
def test_accuracy_class_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        AsBuiltRecordCreate(project_id=_PID, title="x", accuracy_class=bad)


@pytest.mark.parametrize(
    "kind", ["pointcloud_scan", "pointcloud_registration", "takeoff_measurement", "cde_document", "manual"]
)
def test_source_kind_accepts_known(kind):
    assert AsBuiltRecordCreate(project_id=_PID, title="x", source_kind=kind).source_kind == kind


@pytest.mark.parametrize("bad", ["scan", "pointcloud", "document", ""])
def test_source_kind_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        AsBuiltRecordCreate(project_id=_PID, title="x", source_kind=bad)


def test_asbuilt_title_required():
    with pytest.raises(ValidationError):
        AsBuiltRecordCreate(project_id=_PID, title="")


@pytest.mark.parametrize("status", ["draft", "surveyed", "verified", "superseded"])
def test_asbuilt_update_status_allows_open_states(status):
    assert AsBuiltRecordUpdate(status=status).status == status


@pytest.mark.parametrize("bad", ["recorded", "void", "signed", "closed"])
def test_asbuilt_update_status_rejects_terminal_and_unknown(bad):
    """``recorded`` is reached only by signing; ``void`` is not a plain-update target."""
    with pytest.raises(ValidationError):
        AsBuiltRecordUpdate(status=bad)


def test_asbuilt_sign_valid_defaults_true():
    assert AsBuiltSignIn().valid is True


def test_asbuilt_survey_all_optional():
    # A survey may carry only notes; the value can already live on the record.
    AsBuiltSurveyIn(notes="captured by total station")


def test_import_from_scan_requires_registration_and_title():
    AsBuiltImportFromScanIn(project_id=_PID, registration_id=uuid.uuid4(), title="As-built from scan")
    with pytest.raises(ValidationError):
        AsBuiltImportFromScanIn(project_id=_PID, registration_id=uuid.uuid4(), title="")


# ── Tolerance computation (pure) ──────────────────────────────────────────────


def test_tolerance_min_rule():
    crit = _criterion("min", lower="355")
    assert compute_tolerance_result(crit, "360") == "within"
    assert compute_tolerance_result(crit, "355") == "within"
    assert compute_tolerance_result(crit, "320") == "out_of_tolerance"


def test_tolerance_max_rule():
    crit = _criterion("max", upper="50")
    assert compute_tolerance_result(crit, "40") == "within"
    assert compute_tolerance_result(crit, "50") == "within"
    assert compute_tolerance_result(crit, "60") == "out_of_tolerance"


def test_tolerance_range_rule():
    crit = _criterion("range", lower="10", upper="20")
    assert compute_tolerance_result(crit, "15") == "within"
    assert compute_tolerance_result(crit, "10") == "within"
    assert compute_tolerance_result(crit, "20") == "within"
    assert compute_tolerance_result(crit, "9") == "out_of_tolerance"
    assert compute_tolerance_result(crit, "21") == "out_of_tolerance"


def test_tolerance_handles_negative_and_decimal_bounds():
    crit = _criterion("range", lower="-2.5", upper="2.5")
    assert compute_tolerance_result(crit, "-1.25") == "within"
    assert compute_tolerance_result(crit, "-3") == "out_of_tolerance"


def test_tolerance_not_assessed_when_undecidable():
    # No criterion, a non-numeric rule, a missing bound, or a non-numeric value: never
    # silently "within".
    assert compute_tolerance_result(None, "5") == "not_assessed"
    assert compute_tolerance_result(_criterion("text"), "5") == "not_assessed"
    assert compute_tolerance_result(_criterion("boolean"), "5") == "not_assessed"
    assert compute_tolerance_result(_criterion("min", lower=None), "5") == "not_assessed"
    assert compute_tolerance_result(_criterion("min", lower="355"), "not-a-number") == "not_assessed"
    assert compute_tolerance_result(_criterion("min", lower="355"), None) == "not_assessed"


# ── Signature determinism (SHA-256 over a canonical snapshot) ─────────────────


def test_snapshot_sha256_is_deterministic_regardless_of_key_order():
    a = {"record_number": "ASB-001", "valid_for_legal_record": True, "signed_by": "u1"}
    b = {"signed_by": "u1", "valid_for_legal_record": True, "record_number": "ASB-001"}
    assert snapshot_sha256(a) == snapshot_sha256(b)


def test_snapshot_sha256_changes_with_content():
    base = {"record_number": "ASB-001", "tolerance_result": "within"}
    changed = {"record_number": "ASB-001", "tolerance_result": "out_of_tolerance"}
    assert snapshot_sha256(base) != snapshot_sha256(changed)


def test_snapshot_sha256_is_hex_64():
    digest = snapshot_sha256({"x": 1})
    assert len(digest) == 64
    int(digest, 16)  # raises if not valid hex


def test_canonical_snapshot_sorts_keys():
    assert canonical_snapshot({"b": 1, "a": 2}) == '{"a":2,"b":1}'
