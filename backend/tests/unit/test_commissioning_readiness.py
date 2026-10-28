# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free unit tests for the commissioning readiness math and gate.

These pin the pure behaviour in
:mod:`app.modules.commissioning.validators.compute_readiness`: the
percent-of-applicable-functional-items-passed figure, the N/A exclusion from the
denominator, division-by-zero safety on an empty system, the commission gate
(no open functional item, no open critical issue, at least one applicable test),
the traffic-light level, and a strict no-typographic-punctuation rule on every
shipped blocking-reason string.

The suite lives under ``backend/tests`` (the ``testpaths`` root in
``backend/pyproject.toml``) so a bare ``pytest`` run collects it. It imports
only the pure validator and touches no database.
"""

from app.modules.commissioning.validators import compute_readiness

# -- Banned characters, built from code points (never a literal string) -----
#
# em dash, en dash, curly single/double quotes, and the zero-width family.
# Assembled from chr() so this source file itself stays free of them.
_BANNED_CODE_POINTS = (
    0x2014,  # em dash
    0x2013,  # en dash
    0x2018,  # left single quotation mark
    0x2019,  # right single quotation mark
    0x201C,  # left double quotation mark
    0x201D,  # right double quotation mark
    0x200B,  # zero width space
    0x200C,  # zero width non-joiner
    0x200D,  # zero width joiner
    0x2060,  # word joiner
    0xFEFF,  # zero width no-break space
)
_BANNED_CHARS = frozenset(chr(cp) for cp in _BANNED_CODE_POINTS)

_EXPECTED_KEYS = {
    "functional_total",
    "functional_passed",
    "functional_failed",
    "functional_pending",
    "functional_na",
    "applicable",
    "open_functional_items",
    "open_critical_issues",
    "readiness_pct",
    "defined",
    "can_commission",
    "readiness_level",
    "blocking_reasons",
    "formula",
}


class TestShape:
    def test_result_has_all_documented_keys(self) -> None:
        result = compute_readiness(["pass", "fail"])
        assert set(result.keys()) == _EXPECTED_KEYS

    def test_no_typographic_punctuation_in_blocking_reasons(self) -> None:
        # Sweep every branch that can emit a blocking reason and assert none of
        # the shipped strings carry an em/en dash, a curly quote or a zero-width.
        scenarios = [
            ([], 0),
            (["na", "na"], 0),
            (["pending", "fail"], 0),
            (["pass"], 3),
            (["pass", "fail", "pending"], 2),
        ]
        for statuses, crit in scenarios:
            for reason in compute_readiness(statuses, crit)["blocking_reasons"]:
                assert not (_BANNED_CHARS & set(reason)), f"banned char in: {reason!r}"


class TestReadinessMath:
    def test_all_passed_is_full_readiness_and_green(self) -> None:
        result = compute_readiness(["pass", "pass", "pass"])
        assert result["readiness_pct"] == 100.0
        assert result["defined"] is True
        assert result["can_commission"] is True
        assert result["readiness_level"] == "green"
        assert result["blocking_reasons"] == []

    def test_percent_is_passed_over_applicable(self) -> None:
        # 2 pass out of (4 total - 0 na) = 50%.
        result = compute_readiness(["pass", "pass", "fail", "pending"])
        assert result["functional_total"] == 4
        assert result["applicable"] == 4
        assert result["readiness_pct"] == 50.0

    def test_na_items_excluded_from_denominator(self) -> None:
        # 1 pass, 1 na -> applicable = 1, so 1/1 = 100%.
        result = compute_readiness(["pass", "na"])
        assert result["functional_na"] == 1
        assert result["applicable"] == 1
        assert result["readiness_pct"] == 100.0
        assert result["can_commission"] is True

    def test_pending_and_unknown_are_conservative(self) -> None:
        # An unrecognised status counts as pending (not done), never as passed.
        result = compute_readiness(["pass", "sometimes", ""])
        assert result["functional_passed"] == 1
        assert result["functional_pending"] == 2
        assert result["can_commission"] is False

    def test_amber_when_partly_done_no_failures(self) -> None:
        result = compute_readiness(["pass", "pending"])
        assert result["readiness_level"] == "amber"
        assert result["open_functional_items"] == 1

    def test_failure_makes_it_red(self) -> None:
        result = compute_readiness(["pass", "fail"])
        assert result["readiness_level"] == "red"
        assert result["can_commission"] is False


class TestEmptyAndUndefined:
    def test_empty_is_defined_false_not_a_crash(self) -> None:
        result = compute_readiness([])
        assert result["functional_total"] == 0
        assert result["readiness_pct"] == 0.0
        assert result["defined"] is False
        assert result["can_commission"] is False
        assert result["readiness_level"] == "red"
        assert any("no functional checklist items" in r.lower() for r in result["blocking_reasons"])

    def test_all_na_is_not_commissionable(self) -> None:
        result = compute_readiness(["na", "na"])
        assert result["applicable"] == 0
        assert result["defined"] is False
        assert result["can_commission"] is False
        assert any("not applicable" in r.lower() for r in result["blocking_reasons"])


class TestCommissionGate:
    def test_open_functional_item_blocks_commission(self) -> None:
        result = compute_readiness(["pass", "pending"])
        assert result["can_commission"] is False
        assert any("not passed" in r.lower() for r in result["blocking_reasons"])

    def test_open_critical_issue_blocks_even_when_all_passed(self) -> None:
        result = compute_readiness(["pass", "pass"], open_critical_issues=1)
        assert result["readiness_pct"] == 100.0
        assert result["can_commission"] is False
        assert result["readiness_level"] == "red"
        assert any("critical issue" in r.lower() for r in result["blocking_reasons"])

    def test_all_passed_no_critical_is_commissionable(self) -> None:
        result = compute_readiness(["pass", "pass"], open_critical_issues=0)
        assert result["can_commission"] is True
        assert result["blocking_reasons"] == []

    def test_negative_critical_count_coerced_to_zero(self) -> None:
        result = compute_readiness(["pass"], open_critical_issues=-5)
        assert result["open_critical_issues"] == 0
        assert result["can_commission"] is True

    def test_both_blockers_reported_together(self) -> None:
        result = compute_readiness(["pending"], open_critical_issues=2)
        reasons = " ".join(result["blocking_reasons"]).lower()
        assert "not passed" in reasons
        assert "critical issue" in reasons
