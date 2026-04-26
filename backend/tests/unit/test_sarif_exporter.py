"""Unit tests for the SARIF v2.1.0 exporter.

Covers task tracker #224 mandates:
    1. round-trip: 2 errors + 1 warning → schema-shape valid SARIF
    2. severity mapping: error→error, warning→warning, info→note
    3. empty report → valid SARIF with runs[0].results == []
    4. unicode in messages survives the round-trip
"""

from __future__ import annotations

import json

import pytest

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationReport,
)
from app.modules.validation.sarif_exporter import (
    SARIF_VERSION,
    _level_for,
    report_to_sarif,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_report(*results: RuleResult, target_type: str = "boq", target_id: str = "boq-123") -> ValidationReport:
    return ValidationReport(
        target_type=target_type,
        target_id=target_id,
        rule_sets_applied=["din276", "boq_quality"],
        results=list(results),
        duration_ms=12.3,
    )


def _r(rule_id: str, severity: Severity, *, passed: bool, message: str = "msg", element_ref: str | None = None) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        rule_name=rule_id.replace(".", " ").title(),
        severity=severity,
        category=RuleCategory.COMPLIANCE,
        passed=passed,
        message=message,
        element_ref=element_ref,
    )


def _required_run_keys(run: dict) -> None:
    """Spot-check a SARIF run for the keys the v2.1.0 schema mandates."""
    assert "tool" in run
    assert "driver" in run["tool"]
    assert "name" in run["tool"]["driver"]
    assert "results" in run
    assert isinstance(run["results"], list)


# ── 1. Round-trip with 2 errors + 1 warning ────────────────────────────────


def test_round_trip_two_errors_one_warning() -> None:
    """A report with three failing rules round-trips to a SARIF doc with 3 results."""
    report = _make_report(
        _r("din276.kg_required", Severity.ERROR, passed=False, element_ref="pos-1"),
        _r("din276.kg_valid", Severity.ERROR, passed=False, element_ref="pos-2"),
        _r("boq_quality.zero_rate", Severity.WARNING, passed=False, element_ref="pos-3"),
        _r("boq_quality.no_dup", Severity.ERROR, passed=True),  # passed → not in results
    )

    sarif = report_to_sarif(report)

    # Top-level shape
    assert sarif["version"] == SARIF_VERSION
    assert "$schema" in sarif
    assert "runs" in sarif and len(sarif["runs"]) == 1

    run = sarif["runs"][0]
    _required_run_keys(run)

    # Three failing → three results.  The passing rule must NOT be in results
    # (SARIF idiom — passing checks live in invocations.properties).
    assert len(run["results"]) == 3
    levels = [r["level"] for r in run["results"]]
    assert levels.count("error") == 2
    assert levels.count("warning") == 1

    # All four rules registered in the driver.rules registry (passing + failing).
    rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
    assert rule_ids == {
        "din276.kg_required",
        "din276.kg_valid",
        "boq_quality.zero_rate",
        "boq_quality.no_dup",
    }

    # Each result must have ruleId, message.text, locations[0].physicalLocation
    for r in run["results"]:
        assert r["ruleId"]
        assert r["message"]["text"]
        loc = r["locations"][0]
        assert "physicalLocation" in loc
        assert "artifactLocation" in loc["physicalLocation"]
        assert "uri" in loc["physicalLocation"]["artifactLocation"]

    # The element_refs surface as logicalLocations.
    refs = []
    for r in run["results"]:
        if "logicalLocations" in r["locations"][0]:
            refs.append(r["locations"][0]["logicalLocations"][0]["name"])
    assert set(refs) == {"pos-1", "pos-2", "pos-3"}

    # The doc must be JSON-serialisable.
    encoded = json.dumps(sarif, ensure_ascii=False)
    assert "din276.kg_required" in encoded


# ── 1b. jsonschema validation when available ───────────────────────────────


def test_round_trip_passes_jsonschema_if_available() -> None:
    """If jsonschema + a SARIF schema file are around, the doc validates."""
    jsonschema = pytest.importorskip("jsonschema")
    # We don't ship the SARIF schema in the repo.  Build a minimum draft
    # schema covering the required keys we promise.
    minimum_schema = {
        "type": "object",
        "required": ["version", "runs"],
        "properties": {
            "version": {"type": "string"},
            "runs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["tool", "results"],
                    "properties": {
                        "tool": {
                            "type": "object",
                            "required": ["driver"],
                            "properties": {
                                "driver": {
                                    "type": "object",
                                    "required": ["name"],
                                },
                            },
                        },
                        "results": {"type": "array"},
                    },
                },
            },
        },
    }
    report = _make_report(_r("x.y", Severity.ERROR, passed=False))
    sarif = report_to_sarif(report)
    jsonschema.validate(sarif, minimum_schema)


# ── 2. Severity mapping ────────────────────────────────────────────────────


def test_severity_mapping_table() -> None:
    """All three severities map to the correct SARIF level strings."""
    assert _level_for(Severity.ERROR) == "error"
    assert _level_for(Severity.WARNING) == "warning"
    assert _level_for(Severity.INFO) == "note"
    # String inputs (from ORM) work too.
    assert _level_for("error") == "error"
    assert _level_for("warning") == "warning"
    assert _level_for("info") == "note"
    # Unknown → "none" (SARIF's "no-level" sentinel).
    assert _level_for("UNKNOWN") == "none"


def test_severity_mapping_in_results() -> None:
    """A report with one of each severity → one result of each level."""
    report = _make_report(
        _r("e", Severity.ERROR, passed=False),
        _r("w", Severity.WARNING, passed=False),
        _r("i", Severity.INFO, passed=False),
    )
    sarif = report_to_sarif(report)
    levels = sorted(r["level"] for r in sarif["runs"][0]["results"])
    assert levels == ["error", "note", "warning"]


# ── 3. Empty report → valid SARIF with empty results ───────────────────────


def test_empty_report_produces_valid_sarif() -> None:
    """A report with no results still produces a schema-shape SARIF doc."""
    report = _make_report()  # no results
    sarif = report_to_sarif(report)

    assert sarif["version"] == SARIF_VERSION
    assert len(sarif["runs"]) == 1
    run = sarif["runs"][0]
    _required_run_keys(run)
    assert run["results"] == []
    assert run["tool"]["driver"]["rules"] == []
    # invocations array still emits, with counters in the property bag.
    assert run["invocations"][0]["properties"]["totalChecks"] == 0
    assert run["invocations"][0]["properties"]["passingChecks"] == 0


# ── 4. Unicode survives round-trip ─────────────────────────────────────────


def test_unicode_messages_survive_round_trip() -> None:
    """Messages with non-ASCII characters round-trip through JSON serialisation."""
    report = _make_report(
        _r(
            "din276.kg",
            Severity.ERROR,
            passed=False,
            message="Position 01.02 fehlt Kostengruppe — Stahlbeton C30/37 für Außenwände 🏗️ ñoño",
            element_ref="pos-уникод-001",
        ),
    )
    sarif = report_to_sarif(report)

    # Direct attribute survives.
    msg = sarif["runs"][0]["results"][0]["message"]["text"]
    assert "Stahlbeton" in msg
    assert "Außenwände" in msg
    assert "🏗️" in msg
    assert "ñoño" in msg

    # logicalLocations preserves the cyrillic element_ref.
    loc = sarif["runs"][0]["results"][0]["locations"][0]
    assert loc["logicalLocations"][0]["name"] == "pos-уникод-001"

    # JSON round-trip preserves everything.
    encoded = json.dumps(sarif, ensure_ascii=False)
    decoded = json.loads(encoded)
    decoded_msg = decoded["runs"][0]["results"][0]["message"]["text"]
    assert decoded_msg == msg

    # Even with ensure_ascii=True the data round-trips (just escaped on the wire).
    encoded_ascii = json.dumps(sarif, ensure_ascii=True)
    decoded_ascii = json.loads(encoded_ascii)
    assert decoded_ascii["runs"][0]["results"][0]["message"]["text"] == msg


# ── Bonus: ORM-row input path ──────────────────────────────────────────────


def test_orm_row_shape_input() -> None:
    """An ORM-style ValidationReport row (dict-shaped results) also exports."""

    class FakeORMReport:
        def __init__(self) -> None:
            self.id = "00000000-0000-0000-0000-000000000001"
            self.target_type = "boq"
            self.target_id = "boq-abc"
            self.rule_set = "din276+boq_quality"
            self.created_at = None
            self.results = [
                {
                    "rule_id": "x.y",
                    "rule_name": "X Y",
                    "severity": "error",
                    "passed": False,
                    "message": "broken",
                    "element_ref": "pos-1",
                    "details": {},
                    "suggestion": "fix it",
                },
                {
                    "rule_id": "z.q",
                    "rule_name": "Z Q",
                    "severity": "warning",
                    "passed": False,
                    "message": "warn",
                    "element_ref": None,
                    "details": {},
                    "suggestion": None,
                },
            ]

    sarif = report_to_sarif(FakeORMReport())
    levels = [r["level"] for r in sarif["runs"][0]["results"]]
    assert sorted(levels) == ["error", "warning"]
    # The suggestion surfaces in properties.
    has_fix_property = any(
        r.get("properties", {}).get("suggestion") == "fix it"
        for r in sarif["runs"][0]["results"]
    )
    assert has_fix_property
