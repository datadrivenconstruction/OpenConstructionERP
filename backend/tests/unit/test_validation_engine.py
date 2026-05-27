"""Tests for the validation engine."""

import pytest

from app.core.validation.engine import (
    RuleCategory,
    RuleRegistry,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationEngine,
    ValidationRule,
    ValidationStatus,
)

# ── Test fixtures ──────────────────────────────────────────────────────────


class AlwaysPassRule(ValidationRule):
    rule_id = "test.always_pass"
    name = "Always Pass"
    standard = "test"
    severity = Severity.ERROR
    category = RuleCategory.QUALITY

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=True,
                message="OK",
            )
        ]


class AlwaysFailRule(ValidationRule):
    rule_id = "test.always_fail"
    name = "Always Fail"
    standard = "test"
    severity = Severity.ERROR
    category = RuleCategory.QUALITY

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message="This always fails",
            )
        ]


class WarningRule(ValidationRule):
    rule_id = "test.warning"
    name = "Warning Rule"
    standard = "test"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message="This is a warning",
            )
        ]


class QuantityCheckRule(ValidationRule):
    rule_id = "test.quantity_check"
    name = "Quantity Check"
    standard = "test_boq"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results = []
        for pos in context.data.get("positions", []):
            qty = pos.get("quantity", 0)
            passed = qty is not None and float(qty) > 0
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK" if passed else f"Missing quantity for {pos.get('ordinal')}",
                    element_ref=pos.get("id"),
                )
            )
        return results


# ── Registry tests ─────────────────────────────────────────────────────────


class TestRuleRegistry:
    def test_register_and_get(self):
        registry = RuleRegistry()
        rule = AlwaysPassRule()
        registry.register(rule)

        assert registry.get_rule("test.always_pass") is rule
        assert registry.get_rule("nonexistent") is None

    def test_rule_sets(self):
        registry = RuleRegistry()
        registry.register(AlwaysPassRule(), ["set_a", "set_b"])
        registry.register(AlwaysFailRule(), ["set_a"])

        assert registry.list_rule_sets() == {"set_a": 2, "set_b": 1}

    def test_get_rules_for_sets(self):
        registry = RuleRegistry()
        pass_rule = AlwaysPassRule()
        fail_rule = AlwaysFailRule()
        registry.register(pass_rule, ["set_a"])
        registry.register(fail_rule, ["set_b"])

        rules_a = registry.get_rules_for_sets(["set_a"])
        assert len(rules_a) == 1
        assert rules_a[0].rule_id == "test.always_pass"

        rules_both = registry.get_rules_for_sets(["set_a", "set_b"])
        assert len(rules_both) == 2


# ── Engine tests ───────────────────────────────────────────────────────────


class TestValidationEngine:
    @pytest.fixture
    def engine(self):
        registry = RuleRegistry()
        registry.register(AlwaysPassRule())
        registry.register(AlwaysFailRule())
        registry.register(WarningRule())
        return ValidationEngine(registry)

    @pytest.mark.asyncio
    async def test_all_pass(self, engine):
        # Only run the passing rule
        engine.registry = RuleRegistry()
        engine.registry.register(AlwaysPassRule())

        report = await engine.validate(data={}, rule_sets=["test"])
        assert report.status == ValidationStatus.PASSED
        assert report.score == 1.0
        assert not report.has_errors
        assert len(report.passed_rules) == 1

    @pytest.mark.asyncio
    async def test_with_errors(self, engine):
        report = await engine.validate(data={}, rule_sets=["test"])
        assert report.status == ValidationStatus.ERRORS
        assert report.has_errors
        assert len(report.errors) == 1
        assert len(report.warnings) == 1

    @pytest.mark.asyncio
    async def test_warnings_only(self):
        registry = RuleRegistry()
        registry.register(AlwaysPassRule())
        registry.register(WarningRule())
        engine = ValidationEngine(registry)

        report = await engine.validate(data={}, rule_sets=["test"])
        assert report.status == ValidationStatus.WARNINGS
        assert not report.has_errors
        assert report.has_warnings

    @pytest.mark.asyncio
    async def test_no_applicable_rules(self, engine):
        report = await engine.validate(data={}, rule_sets=["nonexistent"])
        assert report.status == ValidationStatus.SKIPPED
        # A SKIPPED report has no honest score — None, not a misleading 1.0.
        assert report.score is None

    @pytest.mark.asyncio
    async def test_boq_validation_with_data(self):
        registry = RuleRegistry()
        registry.register(QuantityCheckRule())
        engine = ValidationEngine(registry)

        data = {
            "positions": [
                {"id": "1", "ordinal": "01.01", "quantity": 10.0},
                {"id": "2", "ordinal": "01.02", "quantity": 0},
                {"id": "3", "ordinal": "01.03", "quantity": 5.5},
            ]
        }

        report = await engine.validate(data=data, rule_sets=["test_boq"])
        assert len(report.results) == 3
        assert len(report.errors) == 1  # position 2 has zero quantity
        assert report.errors[0].element_ref == "2"

    @pytest.mark.asyncio
    async def test_report_summary(self, engine):
        report = await engine.validate(
            data={},
            rule_sets=["test"],
            target_type="boq",
            target_id="test-123",
        )
        summary = report.summary()
        assert summary["status"] == "errors"
        assert summary["counts"]["total"] == 3
        assert summary["counts"]["errors"] == 1
        assert summary["counts"]["warnings"] == 1
        assert summary["counts"]["passed"] == 1
        assert "duration_ms" in summary

    @pytest.mark.asyncio
    async def test_score_calculation(self):
        registry = RuleRegistry()
        registry.register(AlwaysPassRule())
        engine = ValidationEngine(registry)

        report = await engine.validate(data={}, rule_sets=["test"])
        assert report.score == 1.0

        # Add a failing rule
        registry.register(AlwaysFailRule())
        report = await engine.validate(data={}, rule_sets=["test"])
        assert 0 < report.score < 1.0


# ── Score / status / engine-error integrity (E-VAL-007/008/018) ────────────


class _CrashingRule(ValidationRule):
    rule_id = "test.crashes"
    name = "Crashing Rule"
    standard = "test_crash"
    severity = Severity.ERROR
    category = RuleCategory.QUALITY

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        raise ValueError("boom — un-parseable input")


class _OnePerPositionDescRule(ValidationRule):
    """ERROR rule, one result per position — mirrors PositionHasDescription."""

    rule_id = "test.desc"
    name = "Has Description"
    standard = "test_boq2"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for pos in context.data.get("positions", []):
            ok = bool((pos.get("description") or "").strip())
            out.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=ok,
                    message="OK" if ok else "missing desc",
                    element_ref=pos.get("id"),
                )
            )
        return out


class TestScoreHonesty:
    @pytest.mark.asyncio
    async def test_single_hard_error_among_many_caps_score(self):
        """E-VAL-007: one ERROR on 20 perfect positions must NOT read ~0.99."""
        registry = RuleRegistry()
        registry.register(_OnePerPositionDescRule())
        engine = ValidationEngine(registry)

        positions = [{"id": str(i), "description": "ok"} for i in range(20)]
        positions[0]["description"] = ""  # one hard error
        report = await engine.validate(data={"positions": positions}, rule_sets=["test_boq2"])
        assert report.status == ValidationStatus.ERRORS
        assert len(report.errors) == 1
        # The naive per-result weighted ratio would be ~0.9926. The cap must
        # pull it well below "looks fine".
        assert report.score < 0.5
        assert report.score > 0.0  # still discriminates from "all broken"

    @pytest.mark.asyncio
    async def test_engine_error_does_not_become_compliance_error(self):
        """E-VAL-018: a rule crash is diagnostic, not a blocking ERROR."""
        registry = RuleRegistry()
        registry.register(AlwaysPassRule())
        registry.register(_CrashingRule())
        engine = ValidationEngine(registry)

        report = await engine.validate(data={}, rule_sets=["test", "test_crash"])
        # The crash row exists but is bucketed separately.
        assert len(report.engine_errors) == 1
        assert report.engine_errors[0].is_engine_error is True
        assert report.engine_errors[0].category == RuleCategory.DIAGNOSTIC
        # It must NOT flip status to ERRORS nor count as a compliance error.
        assert len(report.errors) == 0
        assert report.has_errors is False
        assert report.status == ValidationStatus.PASSED
        # ... nor drag the quality score (only the passing rule counts).
        assert report.score == 1.0

    @pytest.mark.asyncio
    async def test_only_engine_errors_is_skipped_not_passed(self):
        registry = RuleRegistry()
        registry.register(_CrashingRule())
        engine = ValidationEngine(registry)
        report = await engine.validate(data={}, rule_sets=["test_crash"])
        assert report.status == ValidationStatus.SKIPPED
        # Engine-error-only run is SKIPPED with no honest score (not a fake
        # passing 1.0) — score-honesty contract.
        assert report.score is None
        assert report.summary()["counts"]["engine_errors"] == 1


class TestEmptyDataHandling:
    @pytest.mark.asyncio
    async def test_empty_boq_is_skipped_not_passed(self):
        """E-VAL-008: an empty BOQ must not look '100% green'."""
        from app.core.validation.engine import (
            rule_registry as builtin_registry,
        )
        from app.core.validation.engine import (
            validation_engine,
        )
        from app.core.validation.rules import register_builtin_rules

        if not builtin_registry.get_rule("boq_quality.position_has_quantity"):
            register_builtin_rules()

        report = await validation_engine.validate(data={"positions": []}, rule_sets=["boq_quality"])
        assert report.status == ValidationStatus.SKIPPED
        # SKIPPED reports have no honest quality signal — score is None, not 1.0
        # (NEW-VAL-004: an empty BOQ must not look "100% green").
        assert report.score is None
        assert len(report.results) == 0
