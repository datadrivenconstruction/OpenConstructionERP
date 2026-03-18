"""Validation engine — configurable rule-based data validation.

This is a FIRST-CLASS component of OpenEstimate. Every data import and
modification passes through validation. Rules are organized into rule sets
(e.g., "din276", "gaeb", "boq_quality") that can be enabled per project.

Architecture:
    ValidationEngine
    ├── RuleRegistry (discovers & stores all available rules)
    ├── RuleSet (named collection of rules, e.g. "din276")
    └── ValidationRule (individual rule with validate() method)

    Flow: data → select rule sets → execute rules → ValidationReport
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


# ── Enums & Value Objects ───────────────────────────────────────────────────


class Severity(StrEnum):
    """Validation result severity."""

    ERROR = "error"  # Blocks workflow — must be resolved
    WARNING = "warning"  # Flags issue — can proceed with acknowledgment
    INFO = "info"  # Suggestion — informational only


class ValidationStatus(StrEnum):
    """Overall validation status."""

    PASSED = "passed"  # No errors, no warnings
    WARNINGS = "warnings"  # Warnings only, no errors
    ERRORS = "errors"  # Has errors (may also have warnings)
    SKIPPED = "skipped"  # Validation was skipped (no applicable rules)


class RuleCategory(StrEnum):
    """Categories of validation rules."""

    STRUCTURE = "structure"  # Format correctness, required fields
    COMPLETENESS = "completeness"  # Missing data, gaps in coverage
    CONSISTENCY = "consistency"  # Internal consistency, cross-references
    COMPLIANCE = "compliance"  # Standard compliance (DIN, NRM, etc.)
    QUALITY = "quality"  # Data quality (anomalies, outliers)
    CUSTOM = "custom"  # User-defined rules


# ── Results ─────────────────────────────────────────────────────────────────


@dataclass
class RuleResult:
    """Result of a single validation rule execution."""

    rule_id: str
    rule_name: str
    severity: Severity
    category: RuleCategory
    passed: bool
    message: str
    element_ref: str | None = None  # Reference to source element (BOQ position ID, etc.)
    details: dict[str, Any] = field(default_factory=dict)
    suggestion: str | None = None  # How to fix the issue


@dataclass
class ValidationReport:
    """Complete validation report for a data set."""

    id: str = field(default_factory=lambda: str(uuid4()))
    target_type: str = ""  # "boq", "cad_import", "tender", etc.
    target_id: str = ""
    rule_sets_applied: list[str] = field(default_factory=list)
    results: list[RuleResult] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float = 0.0

    @property
    def errors(self) -> list[RuleResult]:
        return [r for r in self.results if not r.passed and r.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[RuleResult]:
        return [r for r in self.results if not r.passed and r.severity == Severity.WARNING]

    @property
    def infos(self) -> list[RuleResult]:
        return [r for r in self.results if not r.passed and r.severity == Severity.INFO]

    @property
    def passed_rules(self) -> list[RuleResult]:
        return [r for r in self.results if r.passed]

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    @property
    def status(self) -> ValidationStatus:
        if not self.results:
            return ValidationStatus.SKIPPED
        if self.has_errors:
            return ValidationStatus.ERRORS
        if self.has_warnings:
            return ValidationStatus.WARNINGS
        return ValidationStatus.PASSED

    @property
    def score(self) -> float:
        """Quality score 0.0 - 1.0 based on passed/total ratio, weighted by severity."""
        if not self.results:
            return 1.0
        total_weight = 0.0
        passed_weight = 0.0
        weights = {Severity.ERROR: 3.0, Severity.WARNING: 1.5, Severity.INFO: 0.5}
        for r in self.results:
            w = weights.get(r.severity, 1.0)
            total_weight += w
            if r.passed:
                passed_weight += w
        return round(passed_weight / total_weight, 3) if total_weight > 0 else 1.0

    def summary(self) -> dict[str, Any]:
        """Compact summary for API response."""
        return {
            "id": self.id,
            "status": self.status.value,
            "score": self.score,
            "counts": {
                "total": len(self.results),
                "passed": len(self.passed_rules),
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "infos": len(self.infos),
            },
            "rule_sets": self.rule_sets_applied,
            "duration_ms": self.duration_ms,
        }


# ── Rule Interface ──────────────────────────────────────────────────────────


@dataclass
class ValidationContext:
    """Context passed to each validation rule.

    Contains the data being validated plus any additional context
    (project settings, regional config, etc.).
    """

    data: Any  # The data to validate (BOQ, CAD import result, etc.)
    project_id: str | None = None
    region: str | None = None  # "DACH", "UK", "US", etc.
    standard: str | None = None  # "DIN276", "NRM", "MasterFormat"
    metadata: dict[str, Any] = field(default_factory=dict)


class ValidationRule(ABC):
    """Base class for all validation rules.

    Each rule has a unique ID, belongs to a standard and category,
    and implements a validate() method that returns a list of results.

    Subclass this to create new rules:

        class DIN276CostGroupRequired(ValidationRule):
            rule_id = "din276.cost_group_required"
            name = "DIN 276 Cost Group Required"
            standard = "din276"
            severity = Severity.ERROR
            category = RuleCategory.COMPLIANCE
            description = "Every BOQ position must have a DIN 276 cost group assigned"

            async def validate(self, context: ValidationContext) -> list[RuleResult]:
                results = []
                for position in context.data.get("positions", []):
                    has_kg = bool(position.get("classification", {}).get("din276"))
                    results.append(RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=self.severity,
                        category=self.category,
                        passed=has_kg,
                        message="OK" if has_kg else f"Pos {position['ordinal']} missing DIN 276",
                        element_ref=position.get("id"),
                    ))
                return results
    """

    rule_id: str
    name: str
    standard: str  # "din276", "gaeb", "nrm", "masterformat", "universal"
    severity: Severity
    category: RuleCategory
    description: str = ""
    enabled: bool = True

    @abstractmethod
    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Execute validation logic.

        Args:
            context: Data and metadata to validate.

        Returns:
            List of RuleResult (one per checked element, or one overall).
        """
        ...


# ── Rule Registry ───────────────────────────────────────────────────────────


class RuleRegistry:
    """Registry of all available validation rules, organized by rule set."""

    def __init__(self) -> None:
        self._rules: dict[str, ValidationRule] = {}  # rule_id → rule
        self._rule_sets: dict[str, list[str]] = {}  # set_name → [rule_ids]

    def register(self, rule: ValidationRule, rule_sets: list[str] | None = None) -> None:
        """Register a validation rule.

        Args:
            rule: The rule instance.
            rule_sets: Which rule sets this rule belongs to. Defaults to [rule.standard].
        """
        self._rules[rule.rule_id] = rule
        sets = rule_sets or [rule.standard]
        for s in sets:
            if s not in self._rule_sets:
                self._rule_sets[s] = []
            if rule.rule_id not in self._rule_sets[s]:
                self._rule_sets[s].append(rule.rule_id)
        logger.debug("Registered validation rule: %s (sets: %s)", rule.rule_id, sets)

    def get_rule(self, rule_id: str) -> ValidationRule | None:
        return self._rules.get(rule_id)

    def get_rules_for_sets(self, set_names: list[str]) -> list[ValidationRule]:
        """Get all rules belonging to the specified rule sets."""
        rule_ids: set[str] = set()
        for name in set_names:
            rule_ids.update(self._rule_sets.get(name, []))
        return [self._rules[rid] for rid in rule_ids if rid in self._rules]

    def list_rule_sets(self) -> dict[str, int]:
        """List all rule sets with rule counts."""
        return {name: len(ids) for name, ids in self._rule_sets.items()}

    def list_rules(self, rule_set: str | None = None) -> list[dict[str, str]]:
        """List all rules, optionally filtered by rule set."""
        if rule_set:
            rule_ids = self._rule_sets.get(rule_set, [])
            rules = [self._rules[rid] for rid in rule_ids if rid in self._rules]
        else:
            rules = list(self._rules.values())
        return [
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "standard": r.standard,
                "severity": r.severity.value,
                "category": r.category.value,
                "enabled": r.enabled,
            }
            for r in rules
        ]


# ── Validation Engine ───────────────────────────────────────────────────────


class ValidationEngine:
    """Main validation engine.

    Orchestrates rule execution across configured rule sets.

    Usage:
        engine = ValidationEngine(registry)
        report = await engine.validate(
            data=boq_data,
            rule_sets=["din276", "boq_quality"],
            target_type="boq",
            target_id="boq-123",
        )
        if report.has_errors:
            raise ValidationError(report)
    """

    def __init__(self, registry: RuleRegistry) -> None:
        self.registry = registry

    async def validate(
        self,
        data: Any,
        rule_sets: list[str],
        target_type: str = "",
        target_id: str = "",
        project_id: str | None = None,
        region: str | None = None,
        standard: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ValidationReport:
        """Run validation against specified rule sets.

        Args:
            data: The data to validate.
            rule_sets: Which rule sets to apply.
            target_type: Type of data ("boq", "cad_import", etc.).
            target_id: ID of the target entity.
            project_id: Current project ID (for project-specific rules).
            region: Regional context.
            standard: Classification standard context.
            metadata: Additional context for rules.

        Returns:
            ValidationReport with all results.
        """
        import time

        start = time.monotonic()

        context = ValidationContext(
            data=data,
            project_id=project_id,
            region=region,
            standard=standard,
            metadata=metadata or {},
        )

        rules = self.registry.get_rules_for_sets(rule_sets)
        active_rules = [r for r in rules if r.enabled]

        report = ValidationReport(
            target_type=target_type,
            target_id=target_id,
            rule_sets_applied=rule_sets,
        )

        for rule in active_rules:
            try:
                results = await rule.validate(context)
                report.results.extend(results)
            except Exception:
                logger.exception("Validation rule %s failed with exception", rule.rule_id)
                report.results.append(
                    RuleResult(
                        rule_id=rule.rule_id,
                        rule_name=rule.name,
                        severity=Severity.ERROR,
                        category=rule.category,
                        passed=False,
                        message=f"Rule execution failed: {rule.rule_id}",
                        details={"error": "internal_error"},
                    )
                )

        report.duration_ms = round((time.monotonic() - start) * 1000, 2)

        logger.info(
            "Validation complete: %s (score=%.2f, errors=%d, warnings=%d, duration=%.1fms)",
            report.status.value,
            report.score,
            len(report.errors),
            len(report.warnings),
            report.duration_ms,
        )

        return report


# ── Global instances ────────────────────────────────────────────────────────

rule_registry = RuleRegistry()
validation_engine = ValidationEngine(rule_registry)
