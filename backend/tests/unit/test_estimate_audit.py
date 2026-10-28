"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure estimate-audit helpers (DB-free).

Exercise :mod:`app.modules.validation.audit`: rule-set expansion, the median /
dominant-unit suggestions, the per-position status roll-up, and the grouped
findings with their one-click fixes. No database or rule engine is touched.
"""

from decimal import Decimal

from app.modules.validation import audit


def _result(
    rule_id: str,
    *,
    passed: bool,
    severity: str = "warning",
    element_ref: str | None = None,
    details: dict | None = None,
) -> dict:
    """Build an engine result dict in the shape the service persists."""
    return {
        "rule_id": rule_id,
        "rule_name": rule_id,
        "severity": severity,
        "status": "pass" if passed else severity,
        "passed": passed,
        "message": f"{rule_id} {'ok' if passed else 'fail'}",
        "element_ref": element_ref,
        "details": details or {},
        "suggestion": None,
        "is_engine_error": False,
    }


# ── build_rule_sets ─────────────────────────────────────────────────────────


def test_build_rule_sets_expands_estimate_audit() -> None:
    assert audit.build_rule_sets(["estimate_audit"]) == ["boq_quality"]


def test_build_rule_sets_passthrough_and_dedupe() -> None:
    out = audit.build_rule_sets(["estimate_audit", "boq_quality", "din276"])
    assert out == ["boq_quality", "din276"]


# ── numeric helpers ─────────────────────────────────────────────────────────


def test_median_unit_rate_odd() -> None:
    positions = [{"unit_rate": "100"}, {"unit_rate": "300"}, {"unit_rate": "200"}]
    assert audit.median_unit_rate(positions) == Decimal("200")


def test_median_unit_rate_even_averages_two_middles() -> None:
    positions = [{"unit_rate": "10"}, {"unit_rate": "20"}, {"unit_rate": "30"}, {"unit_rate": "40"}]
    assert audit.median_unit_rate(positions) == Decimal("25")


def test_median_unit_rate_ignores_zero_and_blank() -> None:
    positions = [{"unit_rate": "0"}, {"unit_rate": ""}, {"unit_rate": "50"}]
    assert audit.median_unit_rate(positions) == Decimal("50")


def test_median_unit_rate_none_when_unpriced() -> None:
    assert audit.median_unit_rate([{"unit_rate": "0"}, {"unit_rate": None}]) is None


def test_dominant_unit_picks_most_common() -> None:
    positions = [{"unit": "m2"}, {"unit": "m2"}, {"unit": "m3"}, {"unit": ""}]
    assert audit.dominant_unit(positions) == "m2"


def test_dominant_unit_empty_when_no_units() -> None:
    assert audit.dominant_unit([{"unit": ""}, {"unit": None}]) == ""


# ── status roll-up ──────────────────────────────────────────────────────────


def test_build_status_map_worst_severity_wins() -> None:
    results = [
        _result("boq_quality.position_has_quantity", passed=True, element_ref="p1"),
        _result("boq_quality.empty_unit", passed=False, severity="error", element_ref="p1"),
        _result("boq_quality.position_has_unit_rate", passed=False, severity="warning", element_ref="p2"),
        _result("boq_quality.position_has_quantity", passed=True, element_ref="p3"),
    ]
    status = audit.build_status_map(results)
    assert status == {"p1": "errors", "p2": "warnings", "p3": "passed"}


def test_build_status_map_expands_duplicate_ids() -> None:
    results = [
        _result(
            "boq_quality.no_duplicate_ordinals",
            passed=False,
            severity="error",
            element_ref="p1",
            details={"duplicate_ids": ["p1", "p2", "p3"]},
        ),
    ]
    status = audit.build_status_map(results)
    assert status == {"p1": "errors", "p2": "errors", "p3": "errors"}


def test_build_status_map_skips_engine_errors() -> None:
    engine_err = _result("boq_quality.empty_unit", passed=False, severity="info", element_ref="p1")
    engine_err["is_engine_error"] = True
    assert audit.build_status_map([engine_err]) == {}


# ── grouped findings + fixes ────────────────────────────────────────────────


def _priced_positions() -> list[dict]:
    return [
        {"id": "p1", "ordinal": "01", "description": "A", "unit": "m2", "unit_rate": "100"},
        {"id": "p2", "ordinal": "02", "description": "B", "unit": "m2", "unit_rate": "200"},
        {"id": "p3", "ordinal": "03", "description": "C", "unit": "m3", "unit_rate": "300"},
    ]


def test_price_outlier_fix_sets_median_rate() -> None:
    results = [_result("boq_quality.unit_rate_in_range", passed=False, element_ref="p1")]
    findings = audit.build_findings(results, _priced_positions())
    assert len(findings) == 1
    f = findings[0]
    assert f["group"] == audit.GROUP_PRICE_OUTLIER
    assert f["fix"] == {"type": audit.FIX_SET_RATE, "params": {"unit_rate": "200.00"}}


def test_missing_rate_fix_sets_median_rate() -> None:
    results = [_result("boq_quality.position_has_unit_rate", passed=False, element_ref="p2")]
    findings = audit.build_findings(results, _priced_positions())
    assert findings[0]["fix"]["type"] == audit.FIX_SET_RATE
    assert findings[0]["fix"]["params"]["unit_rate"] == "200.00"


def test_empty_unit_fix_switches_to_dominant_unit() -> None:
    results = [_result("boq_quality.empty_unit", passed=False, severity="error", element_ref="p1")]
    findings = audit.build_findings(results, _priced_positions())
    f = findings[0]
    assert f["group"] == audit.GROUP_WRONG_UNIT
    assert f["fix"] == {"type": audit.FIX_SWITCH_UNIT, "params": {"unit": "m2"}}


def test_duplicate_fix_carries_keep_and_remove_ids() -> None:
    results = [
        _result(
            "boq_quality.no_duplicate_ordinals",
            passed=False,
            severity="error",
            element_ref="p1",
            details={"duplicate_ids": ["p1", "p2"]},
        ),
    ]
    findings = audit.build_findings(results, _priced_positions())
    f = findings[0]
    assert f["group"] == audit.GROUP_DUPLICATE
    assert f["fix"]["type"] == audit.FIX_MERGE_DUPLICATE
    assert f["fix"]["params"] == {"keep_position_id": "p1", "duplicate_position_ids": ["p2"]}
    assert f["position_ids"] == ["p1", "p2"]


def test_empty_section_fix_adds_companion_line() -> None:
    positions = [
        *_priced_positions(),
        {"id": "s1", "ordinal": "10", "description": "Sec", "unit": "", "type": "section"},
    ]
    results = [_result("boq_quality.section_without_items", passed=False, element_ref="s1")]
    findings = audit.build_findings(results, positions)
    f = findings[0]
    assert f["group"] == audit.GROUP_MISSING
    assert f["fix"]["type"] == audit.FIX_ADD_COMPANION
    assert f["fix"]["params"]["section_id"] == "s1"
    assert f["fix"]["params"]["unit"] == "m2"
    assert f["fix"]["params"]["unit_rate"] == "200.00"


def test_missing_quantity_has_no_auto_fix() -> None:
    results = [_result("boq_quality.position_has_quantity", passed=False, severity="error", element_ref="p1")]
    findings = audit.build_findings(results, _priced_positions())
    assert findings[0]["group"] == audit.GROUP_MISSING
    assert findings[0]["fix"] is None


def test_missing_description_is_missing_group_without_fix() -> None:
    results = [_result("boq_quality.position_has_description", passed=False, severity="error", element_ref="p1")]
    findings = audit.build_findings(results, _priced_positions())
    assert findings[0]["group"] == audit.GROUP_MISSING
    assert findings[0]["fix"] is None


def test_unrealistic_rate_offers_set_rate_fix() -> None:
    results = [_result("boq_quality.unrealistic_rate", passed=False, element_ref="p1")]
    findings = audit.build_findings(results, _priced_positions())
    assert findings[0]["group"] == audit.GROUP_PRICE_OUTLIER
    assert findings[0]["fix"] == {"type": audit.FIX_SET_RATE, "params": {"unit_rate": "200.00"}}


def test_set_rate_fix_none_when_no_priced_line() -> None:
    positions = [{"id": "p1", "ordinal": "01", "description": "A", "unit": "m2", "unit_rate": "0"}]
    results = [_result("boq_quality.position_has_unit_rate", passed=False, element_ref="p1")]
    findings = audit.build_findings(results, positions)
    assert findings[0]["fix"] is None


def test_passing_and_unknown_results_produce_no_findings() -> None:
    results = [
        _result("boq_quality.position_has_quantity", passed=True, element_ref="p1"),
        _result("din276.cost_group_required", passed=False, severity="error", element_ref="p1"),
    ]
    assert audit.build_findings(results, _priced_positions()) == []


def test_findings_sorted_errors_first() -> None:
    results = [
        _result("boq_quality.unit_rate_in_range", passed=False, severity="warning", element_ref="p1"),
        _result("boq_quality.empty_unit", passed=False, severity="error", element_ref="p2"),
    ]
    findings = audit.build_findings(results, _priced_positions())
    assert findings[0]["severity"] == "error"
    assert findings[1]["severity"] == "warning"


# ── summaries ───────────────────────────────────────────────────────────────


def test_summarize_groups_orders_and_flags_error_severity() -> None:
    findings = [
        {"group": audit.GROUP_PRICE_OUTLIER, "severity": "warning"},
        {"group": audit.GROUP_MISSING, "severity": "error"},
        {"group": audit.GROUP_MISSING, "severity": "warning"},
    ]
    groups = audit.summarize_groups(findings)
    assert [g["key"] for g in groups] == [audit.GROUP_MISSING, audit.GROUP_PRICE_OUTLIER]
    assert groups[0] == {"key": audit.GROUP_MISSING, "count": 2, "severity": "error"}


def test_build_position_audit_meta_counts_per_position() -> None:
    findings = [
        {"group": audit.GROUP_DUPLICATE, "position_id": "p1", "position_ids": ["p1", "p2"]},
        {"group": audit.GROUP_PRICE_OUTLIER, "position_id": "p1", "position_ids": ["p1"]},
    ]
    meta = audit.build_position_audit_meta(findings)
    assert meta["p1"] == {"groups": [audit.GROUP_DUPLICATE, audit.GROUP_PRICE_OUTLIER], "count": 2}
    assert meta["p2"] == {"groups": [audit.GROUP_DUPLICATE], "count": 1}
