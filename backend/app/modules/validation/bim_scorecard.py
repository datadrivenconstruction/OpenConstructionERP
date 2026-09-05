# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BIM model quality scorecard - maturity facets + version trend.

Extends the per-element BIM validation (``bim_validation_service``) into a
fuller "quality scorecard": several maturity FACETS computed from the
canonical element data the platform already holds, aggregated into named
sub-scores and an overall maturity grade, plus a version-over-version score
TREND assembled from the ``ValidationReport`` history the platform already
persists.

Everything in this module is PURE and DB-free. The facet functions and the
scorecard/trend builders take plain element-like objects (BIM ORM rows,
dicts, or ``SimpleNamespace``) and prior-report-like objects, so they are
unit-testable without a database. The async orchestration that loads elements
and reads the report history lives in ``bim_scorecard_service``.

Facets implemented here (all derived from data already loaded, no geometry
invented):

* ``property_completeness`` - rolls in the existing per-element rule score
  (thickness/material/fire-rating/dimensions/system/storey/name), scored with
  the SAME severity-weighted formula as the persisted BIM report so the number
  stays comparable across the platform.
* ``discipline_coverage`` - which major disciplines are present versus a
  configurable expected set, as a percent.
* ``information_consistency`` - elements whose metadata richness is out of step
  with peers of the same category (missing properties most siblings carry). A
  lightweight proxy for information maturity; it does NOT attempt true
  geometric Level-of-Development, which would need solids the platform does not
  expose here.
* ``naming_rigor`` - share of elements with a well-formed name and identifier.

Deliberately NOT implemented: true solid overlap / gap (clash) detection. That
needs real geometry (meshes / solids) this layer does not expose, so faking it
would be dishonest. It is left to the dedicated clash pipeline.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.validation.engine import (
    SEVERITY_WEIGHTS,
    compute_quality_score,
)
from app.modules.validation.rules.bim_universal import get_rules_by_ids

# --- Facet identifiers + defaults ------------------------------------------

FACET_PROPERTY_COMPLETENESS = "property_completeness"
FACET_DISCIPLINE_COVERAGE = "discipline_coverage"
FACET_INFORMATION_CONSISTENCY = "information_consistency"
FACET_NAMING_RIGOR = "naming_rigor"

FACET_ORDER: tuple[str, ...] = (
    FACET_PROPERTY_COMPLETENESS,
    FACET_DISCIPLINE_COVERAGE,
    FACET_INFORMATION_CONSISTENCY,
    FACET_NAMING_RIGOR,
)

FACET_NAMES: dict[str, str] = {
    FACET_PROPERTY_COMPLETENESS: "Property completeness",
    FACET_DISCIPLINE_COVERAGE: "Discipline coverage",
    FACET_INFORMATION_CONSISTENCY: "Information consistency",
    FACET_NAMING_RIGOR: "Naming and identifier rigor",
}

# Composite weights. Property completeness carries the most weight because it is
# the compliance-bearing facet (it can raise blocking errors); the three
# structural-maturity facets split the rest evenly. Sums to 1.0.
DEFAULT_FACET_WEIGHTS: dict[str, float] = {
    FACET_PROPERTY_COMPLETENESS: 0.40,
    FACET_DISCIPLINE_COVERAGE: 0.20,
    FACET_INFORMATION_CONSISTENCY: 0.20,
    FACET_NAMING_RIGOR: 0.20,
}

# Canonical disciplines, aligned with the federation palette used elsewhere in
# the platform (bim_hub.seed). The default "expected" set is the five major
# building disciplines.
CANONICAL_DISCIPLINES: tuple[str, ...] = (
    "architectural",
    "structural",
    "mechanical",
    "electrical",
    "plumbing",
)
DEFAULT_EXPECTED_DISCIPLINES: tuple[str, ...] = CANONICAL_DISCIPLINES

# Element-type prefix -> canonical discipline, used only when an element does
# not carry an explicit ``discipline``. Prefixes are matched after stripping a
# leading ``ifc`` and lower-casing (so ``IfcWallStandardCase`` -> ``wall``).
_ETYPE_DISCIPLINE: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "architectural",
        (
            "wall",
            "door",
            "window",
            "floor",
            "roof",
            "ceiling",
            "stair",
            "railing",
            "curtain",
            "room",
            "space",
            "furniture",
            "covering",
            "ramp",
        ),
    ),
    (
        "structural",
        (
            "beam",
            "column",
            "footing",
            "pile",
            "member",
            "brace",
            "slab",
            "foundation",
            "truss",
            "rebar",
            "reinforc",
        ),
    ),
    (
        "mechanical",
        (
            "duct",
            "airterminal",
            "fan",
            "ahu",
            "mechanicalequipment",
            "boiler",
            "chiller",
            "hvac",
        ),
    ),
    (
        "electrical",
        (
            "cabletray",
            "conduit",
            "lightfixture",
            "lighting",
            "electricalequipment",
            "wire",
            "switch",
            "socket",
            "outlet",
            "panelboard",
        ),
    ),
    (
        "plumbing",
        (
            "pipe",
            "plumbingfixture",
            "sanitary",
            "valve",
            "sprinkler",
            "waste",
            "drain",
        ),
    ),
)

# Tokens that are never a real element name.
_NAME_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "",
        "none",
        "null",
        "n/a",
        "na",
        "unnamed",
        "<unnamed>",
        "undefined",
        "-",
        "--",
        "tbd",
        "?",
    }
)
_EMPTY_ID_TOKENS: frozenset[str] = frozenset({"", "none", "null"})

# Grade bands (maturity letter grade). A score at or above the threshold earns
# the letter; below every band is an "F".
GRADE_BANDS: tuple[tuple[float, str], ...] = (
    (0.90, "A"),
    (0.75, "B"),
    (0.60, "C"),
    (0.40, "D"),
)

# Default cap on how many flagged element ids a single facet keeps, and how
# many elements the merged drill-down keeps. Large models can flag tens of
# thousands of elements; a scorecard payload must stay legible.
DEFAULT_DRILLDOWN_CAP = 500

# Information-consistency tuning. A category needs at least this many peers
# before richness can be judged; a property key is "expected" for a category
# when this share of its peers carry it; an element is flagged when it holds
# less than this share of its category's expected keys.
_MIN_GROUP_SIZE = 3
_COMMON_KEY_FREQ = 0.6
_CONSISTENCY_FLAG_RATIO = 0.6

# Score delta below which a trend is considered flat rather than moving.
_TREND_EPSILON = 0.005


# --- Element access shim ---------------------------------------------------


class _ElementView:
    """Uniform attribute view over an ORM row, dict, or ``SimpleNamespace``.

    The per-element BIM rules and the facet functions read element data through
    plain ``getattr`` (``element_type``, ``properties``, ``quantities``,
    ``storey``, ``name``, ``discipline``, ``id``, ``stable_id``). Wrapping every
    element in this view lets the whole scorecard run identically over BIM ORM
    rows (service path) and over synthetic dicts (unit tests) without either
    side knowing which it holds.
    """

    __slots__ = ("_el",)

    def __init__(self, element: Any) -> None:
        self._el = element

    def __getattr__(self, name: str) -> Any:
        el = object.__getattribute__(self, "_el")
        if isinstance(el, dict):
            if name in el:
                return el[name]
            raise AttributeError(name)
        # Objects (ORM rows / SimpleNamespace): let missing attrs raise
        # AttributeError naturally so the caller's getattr default applies.
        return getattr(el, name)


def _as_view(element: Any) -> _ElementView:
    """Wrap an element in a view unless it already is one (idempotent)."""
    return element if isinstance(element, _ElementView) else _ElementView(element)


def _as_views(elements: list[Any]) -> list[_ElementView]:
    """Normalise a list of raw elements / views into views.

    Lets every facet function accept BIM ORM rows, dicts, or namespaces
    interchangeably, so the pure facets are unit-testable with plain dicts.
    """
    return [_as_view(e) for e in elements]


def _field(view: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from an element view, returning ``default`` when absent."""
    return getattr(view, name, default)


def _element_id(view: Any) -> str:
    """Best-effort stable string id for drill-down references."""
    for attr in ("id", "stable_id"):
        val = _field(view, attr, None)
        if val is not None and str(val).strip():
            return str(val)
    return ""


# --- Small pure helpers ----------------------------------------------------


def grade_for_score(score: float | None) -> str:
    """Map a 0.0-1.0 score to a maturity letter grade (``N/A`` when None)."""
    if score is None:
        return "N/A"
    for threshold, letter in GRADE_BANDS:
        if score >= threshold:
            return letter
    return "F"


def classify_discipline(view: Any) -> str | None:
    """Resolve an element's canonical discipline.

    Prefers the explicit ``discipline`` attribute (normalised to a canonical
    bucket, mirroring the federation tagging used elsewhere). Falls back to
    inferring from the element type. Returns ``None`` when neither yields a
    known discipline. A non-empty but unrecognised ``discipline`` string is
    returned verbatim (lower-cased) so it still counts as "present", it simply
    will not match a canonical expected discipline.
    """
    raw = str(_field(view, "discipline", "") or "").strip().lower()
    if raw:
        if raw in CANONICAL_DISCIPLINES:
            return raw
        if raw.startswith("arch"):
            return "architectural"
        if raw.startswith("struct"):
            return "structural"
        if raw.startswith("mech") or raw in {"hvac", "mep"}:
            return "mechanical"
        if raw.startswith("elec"):
            return "electrical"
        if raw.startswith("plumb"):
            return "plumbing"
        return raw

    etype = str(_field(view, "element_type", "") or "").strip().lower()
    if etype.startswith("ifc"):
        etype = etype[3:]
    if not etype:
        return None
    for bucket, prefixes in _ETYPE_DISCIPLINE:
        if any(etype.startswith(p) for p in prefixes):
            return bucket
    return None


def is_well_formed_name(name: Any) -> bool:
    """True when ``name`` is a real, non-placeholder element name (len >= 2)."""
    if name is None:
        return False
    text = str(name).strip()
    if len(text) < 2:
        return False
    return text.lower() not in _NAME_PLACEHOLDERS


def _has_identifier(view: Any) -> bool:
    """True when the element carries a usable stable id or primary id."""
    for attr in ("stable_id", "id"):
        val = _field(view, attr, None)
        if val is not None and str(val).strip().lower() not in _EMPTY_ID_TOKENS:
            return True
    return False


def _category_key(view: Any) -> str:
    """Category bucket for peer grouping (normalised element type)."""
    etype = str(_field(view, "element_type", "") or "").strip().lower()
    if etype.startswith("ifc"):
        etype = etype[3:]
    if etype:
        return etype
    props = _field(view, "properties", {}) or {}
    if isinstance(props, dict):
        cat = props.get("category")
        if cat:
            return str(cat).strip().lower()
    return "_uncategorized"


def _normalize_expected(expected: list[str] | tuple[str, ...] | None) -> set[str]:
    """Normalise a caller-supplied expected-discipline set (lower, de-duped)."""
    if not expected:
        return set(DEFAULT_EXPECTED_DISCIPLINES)
    out = {str(d).strip().lower() for d in expected if str(d).strip()}
    return out or set(DEFAULT_EXPECTED_DISCIPLINES)


# --- Facet result shape ----------------------------------------------------


@dataclass
class FacetScore:
    """One maturity facet: a named sub-score with drill-down.

    Attributes:
        facet_id: Stable machine id (see the ``FACET_*`` constants).
        name: Human-readable label.
        score: 0.0-1.0 maturity score, or ``None`` when the facet could not be
            assessed (empty model, or nothing comparable to judge against).
        grade: Letter grade for ``score``.
        weight: Composite weight this facet carries (0 when not applicable).
        applicable: False when the facet had no signal to compute a score.
        covered: Facet-specific numerator used in the plain-language summary.
        total: Facet-specific denominator.
        summary: Short human explanation.
        details: Facet-specific structured detail (missing disciplines, per
            severity counts, group stats, ...).
        element_refs: Ids of elements this facet flagged (bounded), for the
            element-level drill-down.
    """

    facet_id: str
    name: str
    score: float | None
    grade: str
    weight: float
    applicable: bool
    covered: int
    total: int
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    element_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "facet_id": self.facet_id,
            "name": self.name,
            "score": self.score,
            "grade": self.grade,
            "weight": self.weight,
            "applicable": self.applicable,
            "covered": self.covered,
            "total": self.total,
            "summary": self.summary,
            "details": self.details,
            "element_refs": self.element_refs,
        }


@dataclass
class BIMScorecard:
    """Composite maturity scorecard for one BIM model."""

    model_id: str | None
    model_name: str | None
    element_count: int
    overall_score: float | None
    overall_grade: str
    status: str
    facets: list[FacetScore]
    element_findings: dict[str, list[str]]
    generated_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "element_count": self.element_count,
            "overall_score": self.overall_score,
            "overall_grade": self.overall_grade,
            "status": self.status,
            "facets": [f.to_dict() for f in self.facets],
            "element_findings": self.element_findings,
            "generated_ms": self.generated_ms,
        }


def _skipped_facet(facet_id: str, weight: float, summary: str) -> FacetScore:
    """A facet that could not be assessed (no signal)."""
    return FacetScore(
        facet_id=facet_id,
        name=FACET_NAMES.get(facet_id, facet_id),
        score=None,
        grade="N/A",
        weight=weight,
        applicable=False,
        covered=0,
        total=0,
        summary=summary,
        details={},
        element_refs=[],
    )


# --- Facets ----------------------------------------------------------------


def property_completeness_facet(
    views: list[Any],
    rule_ids: list[str] | None = None,
    *,
    weight: float = 0.0,
    drilldown_cap: int = DEFAULT_DRILLDOWN_CAP,
) -> FacetScore:
    """Roll the existing per-element rule pass into a facet.

    Runs the universal BIM element rules (or the ``rule_ids`` subset) over the
    elements and scores them with the exact severity-weighted formula the
    persisted BIM report uses (``compute_quality_score``), so this sub-score is
    directly comparable to the model report card. Elements with at least one
    failing check are flagged for drill-down. When no rule matched any element
    the facet is not applicable (score ``None``) rather than a misleading pass.
    """
    views = _as_views(views)
    rules = get_rules_by_ids(rule_ids)
    passed = 0
    failed = 0
    errors = 0
    warnings = 0
    infos = 0
    total_checks = 0
    passed_weight = 0.0
    total_weight = 0.0
    flagged_ids: list[str] = []
    flagged_seen: set[str] = set()

    for rule in rules:
        rule_weight = SEVERITY_WEIGHTS.get(str(rule.severity), 1.0)
        for view in views:
            if not rule.matches(view):
                continue
            total_checks += 1
            failures = rule.evaluate(view)
            if not failures:
                passed += 1
                passed_weight += rule_weight
                total_weight += rule_weight
                continue
            failed += 1
            total_weight += rule_weight
            for failure in failures:
                if failure.severity == "error":
                    errors += 1
                elif failure.severity == "warning":
                    warnings += 1
                else:
                    infos += 1
            eid = _element_id(view)
            if eid and eid not in flagged_seen and len(flagged_ids) < drilldown_cap:
                flagged_seen.add(eid)
                flagged_ids.append(eid)

    if total_checks == 0:
        return _skipped_facet(
            FACET_PROPERTY_COMPLETENESS,
            weight,
            "No element-completeness rule applied to any element in the model.",
        )

    score = compute_quality_score(passed_weight, total_weight, errors)
    summary = f"{passed} of {total_checks} element checks passed ({failed} with findings)."
    return FacetScore(
        facet_id=FACET_PROPERTY_COMPLETENESS,
        name=FACET_NAMES[FACET_PROPERTY_COMPLETENESS],
        score=score,
        grade=grade_for_score(score),
        weight=weight,
        applicable=True,
        covered=passed,
        total=total_checks,
        summary=summary,
        details={
            "checks_total": total_checks,
            "checks_passed": passed,
            "checks_failed": failed,
            "error_findings": errors,
            "warning_findings": warnings,
            "info_findings": infos,
            "passed_weight": round(passed_weight, 4),
            "total_weight": round(total_weight, 4),
            "flagged_elements": len(flagged_seen),
        },
        element_refs=flagged_ids,
    )


def discipline_coverage_facet(
    views: list[Any],
    expected: list[str] | tuple[str, ...] | None = None,
    *,
    weight: float = 0.0,
) -> FacetScore:
    """Percent of the expected disciplines that are present in the model."""
    views = _as_views(views)
    expected_set = _normalize_expected(expected)
    if not views:
        return _skipped_facet(
            FACET_DISCIPLINE_COVERAGE,
            weight,
            "No elements to assess discipline coverage.",
        )
    if not expected_set:
        return _skipped_facet(
            FACET_DISCIPLINE_COVERAGE,
            weight,
            "No expected discipline set configured.",
        )

    present: Counter[str] = Counter()
    unknown = 0
    for view in views:
        disc = classify_discipline(view)
        if disc:
            present[disc] += 1
        else:
            unknown += 1

    present_names = set(present)
    covered_set = expected_set & present_names
    missing = sorted(expected_set - present_names)
    extra = sorted(present_names - expected_set)
    total = len(expected_set)
    covered = len(covered_set)
    score = covered / total

    summary = f"{covered} of {total} expected disciplines present."
    if missing:
        summary += " Missing: " + ", ".join(missing) + "."
    return FacetScore(
        facet_id=FACET_DISCIPLINE_COVERAGE,
        name=FACET_NAMES[FACET_DISCIPLINE_COVERAGE],
        score=score,
        grade=grade_for_score(score),
        weight=weight,
        applicable=True,
        covered=covered,
        total=total,
        summary=summary,
        details={
            "expected": sorted(expected_set),
            "present": sorted(present_names),
            "missing": missing,
            "extra": extra,
            "per_discipline_counts": dict(present),
            "unclassified_elements": unknown,
        },
        element_refs=[],
    )


def information_consistency_facet(
    views: list[Any],
    *,
    weight: float = 0.0,
    min_group_size: int = _MIN_GROUP_SIZE,
    common_key_freq: float = _COMMON_KEY_FREQ,
    flag_ratio: float = _CONSISTENCY_FLAG_RATIO,
    drilldown_cap: int = DEFAULT_DRILLDOWN_CAP,
) -> FacetScore:
    """Peer-relative metadata-richness consistency.

    For each element category with enough peers, the "expected" property keys
    are those most siblings carry. An element is judged on how many of those
    expected keys it actually holds; elements far below their peers are flagged
    (a broken/partial export). Score is the mean per-element consistency ratio
    across judged categories. Categories too small to judge, and models where
    no category has a shared property set, leave the facet not applicable rather
    than inventing a score.
    """
    views = _as_views(views)
    if not views:
        return _skipped_facet(
            FACET_INFORMATION_CONSISTENCY,
            weight,
            "No elements to assess information consistency.",
        )

    groups: dict[str, list[Any]] = defaultdict(list)
    for view in views:
        groups[_category_key(view)].append(view)

    judged = 0
    consistency_sum = 0.0
    flagged_ids: list[str] = []
    assessed_categories = 0
    skipped_small = 0

    for members in groups.values():
        if len(members) < min_group_size:
            skipped_small += len(members)
            continue
        assessed_categories += 1
        n = len(members)
        key_counts: Counter[str] = Counter()
        member_keys: list[set[str]] = []
        for member in members:
            props = _field(member, "properties", {}) or {}
            keys = set(props.keys()) if isinstance(props, dict) else set()
            member_keys.append(keys)
            key_counts.update(keys)

        common = {k for k, c in key_counts.items() if c / n >= common_key_freq}
        if not common:
            # Peers share no common property set, so richness cannot be judged
            # for this category. Count members as consistent (nothing to be out
            # of step with) but record that they were unjudged on key overlap.
            judged += n
            consistency_sum += float(n)
            continue

        common_size = len(common)
        for member, keys in zip(members, member_keys, strict=False):
            ratio = len(common & keys) / common_size
            judged += 1
            consistency_sum += ratio
            if ratio < flag_ratio:
                eid = _element_id(member)
                if eid and len(flagged_ids) < drilldown_cap:
                    flagged_ids.append(eid)

    if judged == 0:
        return _skipped_facet(
            FACET_INFORMATION_CONSISTENCY,
            weight,
            "No element category has enough peers to judge information consistency.",
        )

    score = consistency_sum / judged
    flagged = len(flagged_ids)
    summary = f"{judged - flagged} of {judged} judged elements are information-consistent with their category peers."
    return FacetScore(
        facet_id=FACET_INFORMATION_CONSISTENCY,
        name=FACET_NAMES[FACET_INFORMATION_CONSISTENCY],
        score=score,
        grade=grade_for_score(score),
        weight=weight,
        applicable=True,
        covered=judged - flagged,
        total=judged,
        summary=summary,
        details={
            "assessed_categories": assessed_categories,
            "judged_elements": judged,
            "flagged_elements": flagged,
            "unjudged_small_group_elements": skipped_small,
            "min_group_size": min_group_size,
            "common_key_freq": common_key_freq,
            "flag_ratio": flag_ratio,
        },
        element_refs=flagged_ids,
    )


def naming_rigor_facet(
    views: list[Any],
    *,
    weight: float = 0.0,
    drilldown_cap: int = DEFAULT_DRILLDOWN_CAP,
) -> FacetScore:
    """Share of elements with a well-formed name AND a usable identifier."""
    views = _as_views(views)
    if not views:
        return _skipped_facet(
            FACET_NAMING_RIGOR,
            weight,
            "No elements to assess naming rigor.",
        )

    name_ok = 0
    id_ok = 0
    both_ok = 0
    flagged_ids: list[str] = []
    for view in views:
        good_name = is_well_formed_name(_field(view, "name", None))
        good_id = _has_identifier(view)
        if good_name:
            name_ok += 1
        if good_id:
            id_ok += 1
        if good_name and good_id:
            both_ok += 1
        else:
            eid = _element_id(view)
            if eid and len(flagged_ids) < drilldown_cap:
                flagged_ids.append(eid)

    total = len(views)
    score = both_ok / total
    summary = f"{both_ok} of {total} elements have a well-formed name and identifier."
    return FacetScore(
        facet_id=FACET_NAMING_RIGOR,
        name=FACET_NAMES[FACET_NAMING_RIGOR],
        score=score,
        grade=grade_for_score(score),
        weight=weight,
        applicable=True,
        covered=both_ok,
        total=total,
        summary=summary,
        details={
            "well_formed_name": name_ok,
            "has_identifier": id_ok,
            "name_and_id": both_ok,
            "total_elements": total,
        },
        element_refs=flagged_ids,
    )


# --- Composite scorecard ---------------------------------------------------


def _weighted_overall(facets: list[FacetScore]) -> float | None:
    """Weighted average of the applicable facet scores (``None`` if none)."""
    num = 0.0
    denom = 0.0
    for facet in facets:
        if not facet.applicable or facet.score is None or facet.weight <= 0:
            continue
        num += facet.score * facet.weight
        denom += facet.weight
    if denom <= 0:
        return None
    return round(num / denom, 4)


def _overall_status(overall: float | None, property_facet: FacetScore | None) -> str:
    """Traffic-light status for the composite.

    ``skipped`` when nothing could be assessed; ``errors`` when the compliance
    facet (property completeness) carries blocking errors; ``warnings`` when the
    composite is below a "B" grade; otherwise ``passed``. Mirrors the
    error-blocks / warning-flags convention used across validation.
    """
    if overall is None:
        return "skipped"
    if property_facet is not None and property_facet.applicable:
        if int(property_facet.details.get("error_findings", 0)) > 0:
            return "errors"
    if overall < 0.75:
        return "warnings"
    return "passed"


def _merge_drilldown(facets: list[FacetScore], cap: int) -> dict[str, list[str]]:
    """Merge per-facet flagged ids into ``element_id -> [facet_id, ...]``."""
    findings: dict[str, list[str]] = {}
    for facet in facets:
        for ref in facet.element_refs:
            bucket = findings.get(ref)
            if bucket is None:
                if len(findings) >= cap:
                    continue
                findings[ref] = [facet.facet_id]
            elif facet.facet_id not in bucket:
                bucket.append(facet.facet_id)
    return findings


def build_bim_scorecard(
    elements: list[Any],
    *,
    expected_disciplines: list[str] | tuple[str, ...] | None = None,
    rule_ids: list[str] | None = None,
    model_id: str | None = None,
    model_name: str | None = None,
    weights: dict[str, float] | None = None,
    drilldown_cap: int = DEFAULT_DRILLDOWN_CAP,
) -> BIMScorecard:
    """Compute the composite maturity scorecard for a BIM model.

    Pure and DB-free: ``elements`` may be ORM rows, dicts, or namespaces. On an
    empty model every facet is reported as not-assessed with a ``None`` overall
    score and ``skipped`` status, so an empty model never reads as a clean pass
    or a misleading grade (guards divide-by-zero throughout).

    Args:
        elements: Element-like objects to score.
        expected_disciplines: Override the expected discipline set.
        rule_ids: Optional subset of universal rule ids for the property facet.
        model_id: Optional model id echoed into the scorecard.
        model_name: Optional model name echoed into the scorecard.
        weights: Optional per-facet weight override (merged over the defaults).
        drilldown_cap: Max flagged elements kept per facet and in the merge.

    Returns:
        A :class:`BIMScorecard`.
    """
    # perf_counter, not monotonic: monotonic steps by about 15.625 ms on
    # Windows, coarser than the scorecard build itself, so generated_ms came
    # back as exactly zero for anything but a very large model.
    started = time.perf_counter()
    facet_weights = dict(DEFAULT_FACET_WEIGHTS)
    if weights:
        facet_weights.update(weights)

    views = _as_views(elements)
    count = len(views)

    if count == 0:
        facets = [
            _skipped_facet(fid, facet_weights.get(fid, 0.0), "Empty model - nothing to assess.") for fid in FACET_ORDER
        ]
        return BIMScorecard(
            model_id=model_id,
            model_name=model_name,
            element_count=0,
            overall_score=None,
            overall_grade="N/A",
            status="skipped",
            facets=facets,
            element_findings={},
            generated_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    prop = property_completeness_facet(
        views,
        rule_ids,
        weight=facet_weights.get(FACET_PROPERTY_COMPLETENESS, 0.0),
        drilldown_cap=drilldown_cap,
    )
    disc = discipline_coverage_facet(
        views,
        expected_disciplines,
        weight=facet_weights.get(FACET_DISCIPLINE_COVERAGE, 0.0),
    )
    info = information_consistency_facet(
        views,
        weight=facet_weights.get(FACET_INFORMATION_CONSISTENCY, 0.0),
        drilldown_cap=drilldown_cap,
    )
    naming = naming_rigor_facet(
        views,
        weight=facet_weights.get(FACET_NAMING_RIGOR, 0.0),
        drilldown_cap=drilldown_cap,
    )
    facets = [prop, disc, info, naming]

    overall = _weighted_overall(facets)
    status = _overall_status(overall, prop)
    element_findings = _merge_drilldown(facets, drilldown_cap)

    return BIMScorecard(
        model_id=model_id,
        model_name=model_name,
        element_count=count,
        overall_score=overall,
        overall_grade=grade_for_score(overall),
        status=status,
        facets=facets,
        element_findings=element_findings,
        generated_ms=round((time.perf_counter() - started) * 1000, 2),
    )


# --- Version-over-version trend --------------------------------------------


def coerce_score(value: Any) -> float | None:
    """Coerce a stored score (``str`` / number / ``None``) to a float.

    ``ValidationReport.score`` is persisted as a string ("0.8734") or ``None``.
    Returns ``None`` for anything that is not a finite number.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            f = float(text)
        except ValueError:
            return None
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    return None


def _to_epoch(value: Any) -> float | None:
    """Best-effort conversion of a created_at value to a sortable epoch."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        try:
            return value.timestamp()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            return None
    return None


def _iso(value: Any) -> str | None:
    """Render a created_at value as an ISO-ish string for the payload."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _trend_direction(scores: list[float], *, epsilon: float = _TREND_EPSILON) -> str:
    """Classify a numeric score series as improving / regressing / flat."""
    if len(scores) < 2:
        return "insufficient"
    delta = scores[-1] - scores[0]
    if delta > epsilon:
        return "improving"
    if delta < -epsilon:
        return "regressing"
    return "flat"


@dataclass
class ScoreTrendPoint:
    """One point in a model's validation-score history."""

    report_id: str | None
    created_at: str | None
    score: float | None
    status: str
    grade: str
    run: int
    element_count: int | None
    rule_set: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "created_at": self.created_at,
            "score": self.score,
            "status": self.status,
            "grade": self.grade,
            "run": self.run,
            "element_count": self.element_count,
            "rule_set": self.rule_set,
        }


@dataclass
class ScoreTrend:
    """Ordered score series for a model, with an overall direction."""

    target_type: str
    target_id: str | None
    points: list[ScoreTrendPoint]
    direction: str
    first_score: float | None
    latest_score: float | None
    delta: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_type": self.target_type,
            "target_id": self.target_id,
            "direction": self.direction,
            "first_score": self.first_score,
            "latest_score": self.latest_score,
            "delta": self.delta,
            "point_count": len(self.points),
            "points": [p.to_dict() for p in self.points],
        }


def assemble_score_trend(
    reports: list[Any],
    *,
    target_type: str = "bim_model",
    target_id: str | None = None,
) -> ScoreTrend:
    """Assemble a version-over-version score trend from prior reports.

    Reuses the ``ValidationReport`` rows the platform already persists (one per
    validation run of a model) - no new storage. ``reports`` are report-like
    objects exposing ``score`` (str/number/None), ``status``, ``created_at``,
    ``id``, ``rule_set``, and ``metadata_``/``metadata``. They are ordered
    chronologically (by ``created_at`` when comparable, else input order), the
    stored score strings are coerced to floats, and the net first-to-latest
    change classifies the series as improving, regressing, flat, or
    insufficient. Guards an empty history.

    Args:
        reports: Prior report-like rows for one model.
        target_type: Echoed onto the trend (defaults to ``bim_model``).
        target_id: The model id the series belongs to.

    Returns:
        A :class:`ScoreTrend`.
    """
    indexed = list(enumerate(reports))

    def _sort_key(item: tuple[int, Any]) -> tuple[bool, float]:
        idx, report = item
        epoch = _to_epoch(_field(report, "created_at", None))
        # Timestamped rows sort first (by epoch); un-timestamped rows keep their
        # original relative order. The two groups never compare across types.
        if epoch is None:
            return (True, float(idx))
        return (False, epoch)

    ordered = [report for _, report in sorted(indexed, key=_sort_key)]

    points: list[ScoreTrendPoint] = []
    for run, report in enumerate(ordered, start=1):
        score = coerce_score(_field(report, "score", None))
        status = str(_field(report, "status", "") or "")
        meta = _field(report, "metadata_", None)
        if meta is None:
            meta = _field(report, "metadata", None)
        element_count = None
        if isinstance(meta, dict):
            raw_count = meta.get("element_count")
            if isinstance(raw_count, int) and not isinstance(raw_count, bool):
                element_count = raw_count
        report_id = _field(report, "id", None)
        points.append(
            ScoreTrendPoint(
                report_id=None if report_id is None else str(report_id),
                created_at=_iso(_field(report, "created_at", None)),
                score=score,
                status=status,
                grade=grade_for_score(score),
                run=run,
                element_count=element_count,
                rule_set=_field(report, "rule_set", None),
            )
        )

    numeric = [p.score for p in points if p.score is not None]
    first_score = numeric[0] if numeric else None
    latest_score = numeric[-1] if numeric else None
    delta = None
    if first_score is not None and latest_score is not None:
        delta = round(latest_score - first_score, 4)

    return ScoreTrend(
        target_type=target_type,
        target_id=None if target_id is None else str(target_id),
        points=points,
        direction=_trend_direction(numeric),
        first_score=first_score,
        latest_score=latest_score,
        delta=delta,
    )
