# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project scoring engine - computes weighted scores and detects gaps.

Takes a ProjectState and produces a ProjectScore with:
- Overall weighted score (0-100)
- Per-domain scores (0-100)
- Critical gaps sorted by severity
- Achievements (positive reinforcement)
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.i18n import catalogue_table
from app.modules.project_intelligence.collector import ProjectState

logger = logging.getLogger(__name__)

# ── Domain weights (must sum to 1.0) ──────────────────────────────────────

# RFC 25 - reweighted for the Estimation Dashboard (v1.9.1): BOQ / Cost Model /
# Validation / Risk are the four domains shown in the reshaped ring. The four
# remaining domains keep 0 weight so they no longer influence the headline
# score - the detail tabs still show them when data is present.
DOMAIN_WEIGHTS: dict[str, float] = {
    "boq": 0.40,
    "cost_model": 0.30,
    "validation": 0.20,
    "risk": 0.10,
    "schedule": 0.0,
    "takeoff": 0.0,
    "tendering": 0.0,
    "documents": 0.0,
    "reports": 0.0,
}


# ── Score result dataclasses ──────────────────────────────────────────────


@dataclass
class CriticalGap:
    """A detected gap in the project that needs attention."""

    id: str
    domain: str
    severity: str  # "blocker" | "critical" | "warning" | "suggestion"
    title: str
    description: str
    impact: str
    action_id: str | None = None
    affected_count: int | None = None


@dataclass
class Achievement:
    """A positive accomplishment to celebrate."""

    domain: str
    title: str
    description: str


@dataclass
class ProjectScore:
    """Complete scoring result for a project."""

    overall: float = 0.0
    overall_grade: str = "F"
    domain_scores: dict[str, float] = field(default_factory=dict)
    critical_gaps: list[CriticalGap] = field(default_factory=list)
    achievements: list[Achievement] = field(default_factory=list)


# ── Gap detection rules ───────────────────────────────────────────────────

# Each rule is a dict with condition, title, etc.
# title and affected_count can be callables that receive ProjectState.

_GAP_RULES: list[dict[str, Any]] = [
    {
        "id": "boq_empty",
        "domain": "boq",
        "severity": "blocker",
        "condition": lambda s: not s.boq.exists or s.boq.total_items == 0,
        "title": "Bill of Quantities is empty",
        "description": "No BOQ items have been created for this project.",
        "impact": "Impossible to generate cost estimate or schedule.",
        "action_id": "action_create_boq_ai",
    },
    {
        "id": "boq_zero_prices",
        "domain": "boq",
        "severity": "critical",
        "condition": lambda s: s.boq.exists and s.boq.items_with_zero_price > 0,
        "title": lambda s: f"{s.boq.items_with_zero_price} BOQ items have no unit price",
        "description": "Items without prices will result in an incomplete cost estimate.",
        "impact": "Total project cost will be understated.",
        "action_id": "action_match_cwicr_prices",
        "affected_count": lambda s: s.boq.items_with_zero_price,
    },
    {
        "id": "boq_zero_quantities",
        "domain": "boq",
        "severity": "warning",
        "condition": lambda s: s.boq.exists and s.boq.items_with_zero_quantity > 0,
        "title": lambda s: f"{s.boq.items_with_zero_quantity} BOQ items have zero quantity",
        "description": "Items with zero quantity will not contribute to the estimate.",
        "impact": "Project scope coverage is incomplete.",
        "action_id": None,
        "affected_count": lambda s: s.boq.items_with_zero_quantity,
    },
    {
        "id": "validation_not_run",
        "domain": "validation",
        "severity": "critical",
        "condition": lambda s: s.validation.last_run is None and s.boq.exists,
        "title": "Validation has never been run",
        "description": "BOQ data has not been checked against compliance rules.",
        "impact": "May violate DIN 276 / NRM / MasterFormat requirements.",
        "action_id": "action_run_validation",
    },
    {
        "id": "validation_critical_errors",
        "domain": "validation",
        "severity": "blocker",
        "condition": lambda s: s.validation.critical_errors > 0,
        "title": lambda s: f"{s.validation.critical_errors} critical validation errors",
        "description": "Validation found rule violations that must be fixed.",
        "impact": "Project cannot be exported or submitted with these errors.",
        "action_id": "action_open_validation",
        "affected_count": lambda s: s.validation.critical_errors,
    },
    {
        "id": "schedule_missing",
        "domain": "schedule",
        "severity": "critical",
        "condition": lambda s: not s.schedule.exists and s.boq.exists and s.boq.total_items > 5,
        "title": "No project schedule exists",
        "description": "The project has no Gantt chart or activity plan.",
        "impact": "Cannot perform 4D/5D analysis or earned value management.",
        "action_id": "action_generate_schedule",
    },
    {
        "id": "schedule_no_baseline",
        "domain": "schedule",
        "severity": "warning",
        "condition": lambda s: s.schedule.exists and not s.schedule.baseline_set,
        "title": "No schedule baseline set",
        "description": "The schedule has no baseline snapshot for planned-vs-actual comparison.",
        "impact": "Earned value analysis and progress tracking will be inaccurate.",
        "action_id": None,
    },
    {
        "id": "risk_high_unmitigated",
        "domain": "risk",
        "severity": "critical",
        "condition": lambda s: s.risk.high_severity_unmitigated > 0,
        "title": lambda s: f"{s.risk.high_severity_unmitigated} high-severity risks with no mitigation",
        "description": "High-risk items have no mitigation strategy defined.",
        "impact": "Project contingency may be insufficient.",
        "action_id": None,
        "affected_count": lambda s: s.risk.high_severity_unmitigated,
    },
    {
        "id": "risk_missing",
        "domain": "risk",
        "severity": "suggestion",
        "condition": lambda s: not s.risk.register_exists and s.boq.exists,
        "title": "No risk register created",
        "description": "Project risks have not been identified or assessed.",
        "impact": "Cannot allocate contingency or plan mitigation actions.",
        "action_id": None,
    },
    {
        "id": "costmodel_no_budget",
        "domain": "cost_model",
        "severity": "warning",
        "condition": lambda s: not s.cost_model.budget_set and s.boq.exists and s.boq.total_items > 5,
        "title": "No project budget set",
        "description": "Budget lines have not been established for this project.",
        "impact": "Cost control and variance tracking are not available.",
        "action_id": None,
    },
    {
        # TOP-30 #19 - surface a live predictive-forecast alert as a gap so
        # it shows in Critical Gaps, not only in the Forecasts tab.
        "id": "forecast_alert_active",
        "domain": "cost_model",
        "severity": "critical",
        "condition": lambda s: s.cost_model.forecast_alert_active,
        "title": "Forecast breaches a cost/schedule threshold",
        "description": "The latest predictive EVM forecast triggered an active alert.",
        "impact": "The project is forecast to miss a configured cost or schedule target.",
        "action_id": None,
    },
    {
        "id": "no_documents",
        "domain": "documents",
        "severity": "suggestion",
        "condition": lambda s: s.documents.total_files == 0 and s.boq.exists,
        "title": "No documents uploaded",
        "description": "Project has no supporting documents (drawings, specs, contracts).",
        "impact": "Missing documentation for audit trail and reference.",
        "action_id": None,
    },
    {
        "id": "no_takeoff",
        "domain": "takeoff",
        "severity": "suggestion",
        "condition": lambda s: s.takeoff.files_uploaded == 0 and s.boq.exists and s.boq.total_items > 5,
        "title": "No CAD/BIM files uploaded for takeoff",
        "description": "Quantities are entered manually without CAD/BIM source data.",
        "impact": "Quantity accuracy depends entirely on manual measurement.",
        "action_id": None,
    },
]


# ── Achievement detection ─────────────────────────────────────────────────

_ACHIEVEMENT_RULES: list[dict[str, Any]] = [
    {
        "domain": "boq",
        "condition": lambda s: s.boq.exists and s.boq.total_items > 0,
        "title": lambda s: f"BOQ created with {s.boq.total_items} items across {s.boq.sections_count} sections",
        "description": "The project has a structured Bill of Quantities.",
    },
    {
        "domain": "boq",
        "condition": lambda s: s.boq.export_ready,
        "title": "BOQ is export-ready",
        "description": "All items have prices and quantities - ready for tender.",
    },
    {
        "domain": "validation",
        "condition": lambda s: s.validation.last_run is not None and s.validation.critical_errors == 0,
        "title": "All validation rules pass",
        "description": "No critical compliance issues detected.",
    },
    {
        "domain": "schedule",
        "condition": lambda s: s.schedule.exists and s.schedule.activities_count > 0,
        "title": lambda s: f"Schedule created with {s.schedule.activities_count} activities",
        "description": "Project timeline is established.",
    },
    {
        "domain": "schedule",
        "condition": lambda s: s.schedule.baseline_set,
        "title": "Schedule baseline is set",
        "description": "Planned-vs-actual tracking is ready.",
    },
    {
        "domain": "risk",
        "condition": lambda s: s.risk.register_exists,
        "title": lambda s: f"Risk register created with {s.risk.total_risks} risks",
        "description": "Project risks have been identified.",
    },
    {
        "domain": "risk",
        "condition": lambda s: (
            s.risk.register_exists and s.risk.high_severity_unmitigated == 0 and s.risk.total_risks > 0
        ),
        "title": "All high-severity risks have mitigation",
        "description": "Risk management is in good shape.",
    },
    {
        "domain": "takeoff",
        "condition": lambda s: s.takeoff.files_processed > 0,
        "title": lambda s: f"CAD/BIM takeoff processed ({', '.join(s.takeoff.formats) or 'files'})",
        "description": "Quantities extracted from CAD/BIM source data.",
    },
    {
        "domain": "cost_model",
        "condition": lambda s: s.cost_model.earned_value_active,
        "title": "Earned value management is active",
        "description": "5D cost tracking with planned, earned, and actual values.",
    },
    {
        "domain": "tendering",
        "condition": lambda s: s.tendering.bids_received > 0,
        "title": lambda s: f"{s.tendering.bids_received} bids received across {s.tendering.bid_packages} packages",
        "description": "Tender process is underway.",
    },
    {
        "domain": "documents",
        "condition": lambda s: s.documents.total_files > 0,
        "title": lambda s: f"{s.documents.total_files} documents uploaded",
        "description": "Project documentation is being maintained.",
    },
    {
        "domain": "reports",
        "condition": lambda s: s.reports.reports_generated > 0,
        "title": lambda s: f"{s.reports.reports_generated} reports generated",
        "description": "Project reporting is active.",
    },
]


# ── Grade mapping ─────────────────────────────────────────────────────────


def _score_to_grade(score: float) -> str:
    """Convert a 0-100 score to a letter grade."""
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 55:
        return "C"
    if score >= 35:
        return "D"
    return "F"


# ── Severity sort order ──────────────────────────────────────────────────

_SEVERITY_ORDER = {"blocker": 0, "critical": 1, "warning": 2, "suggestion": 3}


# ── Main scoring function ────────────────────────────────────────────────


def _resolve_value(value: Any, state: ProjectState) -> Any:
    """Resolve a value that may be a callable (lambda) or a static value."""
    if callable(value):
        return value(state)
    return value


def compute_score(state: ProjectState) -> ProjectScore:
    """Compute the project score from its state.

    Args:
        state: Collected project state.

    Returns:
        ProjectScore with overall score, domain scores, gaps, and achievements.
    """
    result = ProjectScore()

    # ── Domain scores ──────────────────────────────────────────────────
    domain_pcts = {
        "boq": state.boq.completion_pct,
        "validation": state.validation.completion_pct,
        "schedule": state.schedule.completion_pct,
        "cost_model": state.cost_model.completion_pct,
        "takeoff": state.takeoff.completion_pct,
        "risk": state.risk.completion_pct,
        "tendering": state.tendering.completion_pct,
        "documents": state.documents.completion_pct,
        "reports": state.reports.completion_pct,
    }

    result.domain_scores = {domain: round(pct * 100, 1) for domain, pct in domain_pcts.items()}

    # ── Overall weighted score ─────────────────────────────────────────
    # Essential domains always count even if zero - they're required for any
    # serious project. Optional domains (tendering, documents, reports) only
    # contribute to the denominator when they have been touched, so a project
    # that skips optional phases isn't unfairly penalized.
    # RFC 25: headline ring covers BOQ / Cost Model / Validation / Risk.
    ESSENTIAL_DOMAINS = {"boq", "validation", "cost_model", "risk"}

    weighted_sum = 0.0
    total_weight = 0.0
    for domain, weight in DOMAIN_WEIGHTS.items():
        score = domain_pcts.get(domain, 0.0)
        is_essential = domain in ESSENTIAL_DOMAINS
        # Count an optional domain only if it has any progress
        if is_essential or score > 0:
            weighted_sum += score * weight
            total_weight += weight

    if total_weight > 0:
        # `score` here is already a 0-1 float; multiply by 100 to get 0-100.
        result.overall = round(weighted_sum / total_weight * 100, 1)
    else:
        result.overall = 0.0
    result.overall_grade = _score_to_grade(result.overall)

    # ── Detect gaps ────────────────────────────────────────────────────
    for rule in _GAP_RULES:
        try:
            if rule["condition"](state):
                gap = CriticalGap(
                    id=rule["id"],
                    domain=rule["domain"],
                    severity=rule["severity"],
                    title=_resolve_value(rule["title"], state),
                    description=rule["description"],
                    impact=rule["impact"],
                    action_id=rule.get("action_id"),
                    affected_count=(
                        _resolve_value(rule["affected_count"], state) if "affected_count" in rule else None
                    ),
                )
                result.critical_gaps.append(gap)
        except Exception:
            logger.debug("Gap rule %s failed", rule.get("id"), exc_info=True)

    # Sort gaps by severity
    result.critical_gaps.sort(key=lambda g: _SEVERITY_ORDER.get(g.severity, 99))

    # ── Detect achievements ────────────────────────────────────────────
    for rule in _ACHIEVEMENT_RULES:
        try:
            if rule["condition"](state):
                achievement = Achievement(
                    domain=rule["domain"],
                    title=_resolve_value(rule["title"], state),
                    description=rule["description"],
                )
                result.achievements.append(achievement)
        except Exception:
            logger.debug("Achievement rule failed", exc_info=True)

    return result


# ── Presentation helpers (additive, pure, localized) ──────────────────────
#
# The score itself is language-neutral, but the severity words shown on the
# headline were English-only, and a user still had to eyeball which gap to act
# on. These helpers localize the severity words and turn the gap list into a
# plain "do this next" view without re-deriving anything.

#: The four severities in worst-first order (matches _SEVERITY_ORDER).
SEVERITIES: tuple[str, ...] = ("blocker", "critical", "warning", "suggestion")

#: Localized severity word, per language. English is always present and is the
#: fallback for any missing language or unknown severity.
SEVERITY_LABELS: dict[str, dict[str, str]] = catalogue_table(
    "project_intelligence.severity_labels", ("blocker", "critical", "warning", "suggestion"), by_key=True
)


def severity_label(severity: str, lang: str = "en") -> str:
    """Localized word for a gap severity, English as fallback.

    Falls back to English for an unknown language and to the raw ``severity``
    for an unknown severity, so a caller never gets a blank.
    """
    per_lang = SEVERITY_LABELS.get(severity)
    if per_lang is None:
        return severity
    return per_lang.get(lang) or per_lang["en"]


def gap_counts(score: ProjectScore) -> dict[str, int]:
    """Count a score's gaps by severity, worst first, zero-filled.

    Always returns all four severities in :data:`SEVERITIES` order so a caller
    can render a stable row of counts without guarding for missing keys.
    """
    counts = dict.fromkeys(SEVERITIES, 0)
    for gap in score.critical_gaps:
        if gap.severity in counts:
            counts[gap.severity] += 1
    return counts


def next_actions(score: ProjectScore, limit: int | None = None) -> list[CriticalGap]:
    """The actionable gaps to tackle next, worst severity first.

    Keeps only gaps that carry an ``action_id`` (something the user can act on
    directly), preserving the severity-sorted order :func:`compute_score`
    already applied. ``limit`` caps the list; ``None`` returns them all.
    """
    actionable = [gap for gap in score.critical_gaps if gap.action_id]
    if limit is not None and limit >= 0:
        return actionable[:limit]
    return actionable


def score_summary(score: ProjectScore) -> str:
    """One-line plain-language summary of a project score.

    States the grade and score, then the count of blocking and critical gaps to
    address, or confirms a clean project. Kept in English (it quotes English gap
    titles elsewhere); a UI wanting other languages uses :func:`severity_label`.
    """
    head = f"Project health is grade {score.overall_grade} ({score.overall}/100)."
    counts = gap_counts(score)
    blockers = counts["blocker"]
    criticals = counts["critical"]
    if blockers == 0 and criticals == 0:
        return f"{head} No blocking or critical gaps."
    blocker_word = "blocker" if blockers == 1 else "blockers"
    critical_word = "critical gap" if criticals == 1 else "critical gaps"
    return f"{head} {blockers} {blocker_word} and {criticals} {critical_word} need attention."
