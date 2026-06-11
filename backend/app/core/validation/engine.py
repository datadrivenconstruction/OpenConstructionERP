"""‌⁠‍Validation engine - configurable rule-based data validation.

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
    """‌⁠‍Validation result severity."""

    ERROR = "error"  # Blocks workflow - must be resolved
    WARNING = "warning"  # Flags issue - can proceed with acknowledgment
    INFO = "info"  # Suggestion - informational only


class ValidationStatus(StrEnum):
    """‌⁠‍Overall validation status."""

    PASSED = "passed"  # No errors, no warnings, no failing info
    WARNINGS = "warnings"  # Warnings only, no errors
    ERRORS = "errors"  # Has errors (may also have warnings)
    INFO = "info"  # Failing INFO results only, no errors or warnings
    SKIPPED = "skipped"  # Validation was skipped (no applicable rules)
    UNSUPPORTED = "unsupported"  # Requested rule set(s) have no implemented rules


class RuleCategory(StrEnum):
    """Categories of validation rules."""

    STRUCTURE = "structure"  # Format correctness, required fields
    COMPLETENESS = "completeness"  # Missing data, gaps in coverage
    CONSISTENCY = "consistency"  # Internal consistency, cross-references
    COMPLIANCE = "compliance"  # Standard compliance (DIN, NRM, etc.)
    QUALITY = "quality"  # Data quality (anomalies, outliers)
    CUSTOM = "custom"  # User-defined rules
    DIAGNOSTIC = "diagnostic"  # Engine/infra failure - NOT a compliance finding


# ── Shared scoring ──────────────────────────────────────────────────────────
#
# ONE definition of "quality score" so every validation path (BOQ core +
# BIM-model) produces comparable numbers in the unified dashboard
# (E-XMOD-015). Severity weights and the blocking-error cap live here so
# there is a single source of truth.

SEVERITY_WEIGHTS: dict[str, float] = {
    "error": 3.0,
    "warning": 1.5,
    "info": 0.4,
}


def compute_quality_score(
    passed_weight: float,
    total_weight: float,
    n_errors: int,
) -> float:
    """Severity-weighted quality score in ``0.0 - 1.0``.

    Args:
        passed_weight: Sum of severity weights of *passing* checks.
        total_weight: Sum of severity weights of *all* (compliance) checks.
        n_errors: Number of blocking (ERROR-severity) failures.

    Any blocking error caps the headline number (E-VAL-007): one error can
    never read as "99% quality", but the cap stays strictly > 0 so the score
    still discriminates "one error" from "everything broken".
    """
    ratio = passed_weight / total_weight if total_weight > 0 else 1.0
    if n_errors > 0:
        ratio = min(ratio, 0.5 / (1 + n_errors))
    return round(ratio, 4)


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
    # True when this row records a *rule execution failure* (an exception in
    # the rule, e.g. an un-parseable input) rather than a genuine data
    # compliance finding. Engine-error rows are surfaced separately and never
    # flip status to ERRORS or drag down the quality score (E-VAL-018).
    is_engine_error: bool = False


@dataclass
class ValidationReport:
    """Complete validation report for a data set."""

    id: str = field(default_factory=lambda: str(uuid4()))
    target_type: str = ""  # "boq", "cad_import", "tender", etc.
    target_id: str = ""
    rule_sets_applied: list[str] = field(default_factory=list)
    # Requested rule sets that resolved to zero implemented rules. These did
    # NOT run - they are recorded so the HTTP/UI layer can distinguish "ran
    # and passed" from "never ran" instead of silently dropping them.
    unsupported_rule_sets: list[str] = field(default_factory=list)
    results: list[RuleResult] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float = 0.0

    @property
    def errors(self) -> list[RuleResult]:
        return [r for r in self.results if not r.passed and r.severity == Severity.ERROR and not r.is_engine_error]

    @property
    def warnings(self) -> list[RuleResult]:
        return [r for r in self.results if not r.passed and r.severity == Severity.WARNING and not r.is_engine_error]

    @property
    def infos(self) -> list[RuleResult]:
        return [r for r in self.results if not r.passed and r.severity == Severity.INFO and not r.is_engine_error]

    @property
    def engine_errors(self) -> list[RuleResult]:
        """Rule-execution failures (infra), kept distinct from compliance."""
        return [r for r in self.results if r.is_engine_error]

    @property
    def passed_rules(self) -> list[RuleResult]:
        return [r for r in self.results if r.passed]

    @property
    def supported_rule_sets(self) -> list[str]:
        """Requested rule sets that did resolve to at least one rule."""
        unsupported = set(self.unsupported_rule_sets)
        return [s for s in self.rule_sets_applied if s not in unsupported]

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    @property
    def status(self) -> ValidationStatus:
        # Engine-error-only reports are not a real validation pass - there is
        # no compliance signal, so SKIPPED is the honest status (E-VAL-018).
        compliance_results = [r for r in self.results if not r.is_engine_error]
        if not compliance_results:
            # Nothing was actually checked. If the only reason is that every
            # requested rule set is unimplemented, say so explicitly instead
            # of the generic SKIPPED so the caller never reads it as a pass.
            if self.unsupported_rule_sets and not self.supported_rule_sets:
                return ValidationStatus.UNSUPPORTED
            return ValidationStatus.SKIPPED
        if self.has_errors:
            return ValidationStatus.ERRORS
        if self.has_warnings:
            return ValidationStatus.WARNINGS
        # Failing INFO results are real unresolved findings: a report with a
        # sub-1.0 score and info_count > 0 must not read as a clean PASSED.
        # Surface them as INFO (mirrors the BIM service), with errors and
        # warnings still taking precedence above.
        if self.infos:
            return ValidationStatus.INFO
        return ValidationStatus.PASSED

    @property
    def score(self) -> float | None:
        """Quality score in ``0.0 - 1.0``, weighted by severity and honest
        about blocking errors. ``None`` when the report is SKIPPED.

        Three corrections vs. the naive per-result weighted ratio:

        * Engine-error rows are excluded entirely - an infrastructure failure
          must not move the quality number (E-VAL-018).
        * The presence of *any* blocking compliance ERROR caps the score so a
          single fatal error on an otherwise-clean 20-position BOQ can never
          read as "99% quality". The cap shrinks with the error count but
          stays strictly above 0 so the score still discriminates between
          "one error" and "everything broken".
        * A report with **no compliance results** (SKIPPED - nothing was
          actually checked) has *no* quality signal, so the score is ``None``
          rather than a misleading ``1.0`` / "100% quality" (NEW-VAL-004).
        """
        compliance_results = [r for r in self.results if not r.is_engine_error]
        if not compliance_results:
            return None
        total_weight = 0.0
        passed_weight = 0.0
        for r in compliance_results:
            w = SEVERITY_WEIGHTS.get(r.severity.value, 1.0)
            total_weight += w
            if r.passed:
                passed_weight += w
        return compute_quality_score(passed_weight, total_weight, len(self.errors))

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
                "engine_errors": len(self.engine_errors),
            },
            "rule_sets": self.rule_sets_applied,
            "supported_rule_sets": self.supported_rule_sets,
            "unsupported_rule_sets": self.unsupported_rule_sets,
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

    def has_rules(self, set_name: str) -> bool:
        """True when ``set_name`` resolves to at least one registered rule.

        A rule set name can be referenced (in a project config, a partner
        pack, or a UI badge) without any rule ever being registered against
        it - for example a JSON rule pack that the engine cannot load. Such a
        set must never be treated as "ran and passed"; it simply did not run.
        """
        return bool(self._rule_sets.get(set_name))

    def resolve_rule_sets(self, set_names: list[str]) -> tuple[list[str], list[str]]:
        """Split requested rule set names into supported and unsupported.

        Args:
            set_names: Rule set names requested by the caller.

        Returns:
            ``(supported, unsupported)`` - ``supported`` are names that
            resolve to at least one registered rule, ``unsupported`` are names
            with no implemented rules. Order and duplicates of the input are
            preserved within each bucket so callers can echo the request back.
        """
        supported: list[str] = []
        unsupported: list[str] = []
        for name in set_names:
            (supported if self.has_rules(name) else unsupported).append(name)
        return supported, unsupported

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

        _supported, unsupported = self.registry.resolve_rule_sets(rule_sets)
        rules = self.registry.get_rules_for_sets(rule_sets)
        active_rules = [r for r in rules if r.enabled]

        report = ValidationReport(
            target_type=target_type,
            target_id=target_id,
            rule_sets_applied=rule_sets,
            unsupported_rule_sets=unsupported,
        )

        if unsupported:
            logger.warning(
                "Validation requested unimplemented rule set(s): %s (no rules registered)",
                ", ".join(unsupported),
            )

        for rule in active_rules:
            try:
                results = await rule.validate(context)
                report.results.extend(results)
            except Exception as exc:
                logger.exception("Validation rule %s failed with exception", rule.rule_id)
                report.results.append(
                    RuleResult(
                        rule_id=rule.rule_id,
                        rule_name=rule.name,
                        # INFO + DIAGNOSTIC + is_engine_error: a rule crash is
                        # an infrastructure problem, NOT a blocking compliance
                        # ERROR. It must not flip status to ERRORS, must not
                        # drag the quality score, and is reported in its own
                        # bucket so the UI can show it without a phantom
                        # element_ref (E-VAL-018).
                        severity=Severity.INFO,
                        category=RuleCategory.DIAGNOSTIC,
                        passed=False,
                        message=f"Rule execution failed: {rule.rule_id}",
                        details={
                            "error": "internal_error",
                            "exception_type": type(exc).__name__,
                        },
                        is_engine_error=True,
                    )
                )

        report.duration_ms = round((time.monotonic() - start) * 1000, 2)

        logger.info(
            "Validation complete: %s (score=%s, errors=%d, warnings=%d, duration=%.1fms)",
            report.status.value,
            "n/a" if report.score is None else f"{report.score:.2f}",
            len(report.errors),
            len(report.warnings),
            report.duration_ms,
        )

        return report


# ── Global instances ────────────────────────────────────────────────────────

rule_registry = RuleRegistry()
validation_engine = ValidationEngine(rule_registry)
