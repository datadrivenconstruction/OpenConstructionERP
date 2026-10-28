# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Saved-views module validation rules.

A saved view outlives the register it was written against. Fields get renamed,
enum vocabularies get pruned, whole modules get disabled - and the stored spec
keeps sitting there looking healthy. The danger is not that such a view fails;
it is that it might quietly succeed against a different question from the one
the estimator saved. The run path already refuses a spec that no longer binds,
so nothing silently returns the wrong rows. These rules are how the drift is
found BEFORE someone clicks, so a list of views can mark the broken ones
instead of turning a dashboard into a row of identical 422s.

All rules register under the ``saved_views`` rule set and self-select by the
``scope`` carried on the validated data.

View scope (``scope == "view"``, one stored definition plus the registry facts
about the entity it queries):

* ``saved_views.entity_registered``   - ERROR. The entity type is no longer in
                                        the registry, so the view cannot run at
                                        all.
* ``saved_views.spec_parses``         - ERROR. The stored JSON no longer parses
                                        as a filter spec.
* ``saved_views.fields_whitelisted``  - ERROR. The spec names a field the entity
                                        no longer whitelists.
* ``saved_views.field_capability``    - ERROR. The field still exists but may no
                                        longer be filtered, sorted, selected or
                                        grouped the way the spec uses it.
* ``saved_views.enum_values_current`` - ERROR. A filter compares an enum field
                                        against a value that has left the
                                        vocabulary, so it can only ever match
                                        nothing.
* ``saved_views.share_scope_known``   - ERROR. An unrecognised share scope is
                                        treated as private, hiding a view its
                                        owner believes is shared.
* ``saved_views.team_share_has_team`` - ERROR. A team share whose team is gone
                                        reaches nobody but its owner.
* ``saved_views.shared_view_pinned``  - ERROR. A shared view with no project pin
                                        can never admit a second reader.
* ``saved_views.within_complexity_budget`` - WARNING. The spec is close to or
                                        over the static complexity ceiling.
* ``saved_views.page_size_within_cap`` - WARNING. The requested page size is
                                        above the entity cap and will be clamped
                                        without saying so.
* ``saved_views.spec_is_not_empty``   - WARNING. Nothing was actually saved: no
                                        filter, no sort, no column choice.
* ``saved_views.shared_view_described`` - INFO. A view shared with other people
                                        and no description makes them guess.

The rules are pure and DB-free: :mod:`app.modules.saved_views.service` builds
the plain-dict payload from the stored row plus the registry and calls
:func:`evaluate_view`. :func:`describe_staleness` is the same structural core
without the engine, cheap enough to run over every row of a list response.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationReport,
    ValidationRule,
    ValidationStatus,
    rule_registry,
    validation_engine,
)
from app.modules.saved_views.models import SHARE_SCOPES
from app.modules.saved_views.schemas import (
    FilterGroup,
    FilterSpec,
    SavedViewFinding,
    SavedViewValidationReport,
)

if TYPE_CHECKING:
    from app.modules.saved_views.registry import QueryableEntity

logger = logging.getLogger(__name__)

# The rule set every saved-views rule registers under. The service names it on
# every validate call - a registered rule that nobody requests never runs.
SAVED_VIEWS_RULE_SET = "saved_views"

# A spec whose static complexity is within this fraction of the ceiling is
# reported before it crosses it, because the ceiling is a hard refusal.
_COMPLEXITY_WARN_RATIO = 0.75


# ── The structural core, shared by the rules and the cheap list-time check ──


@dataclass(frozen=True)
class SpecProblem:
    """One way a stored spec has drifted from the entity it queries.

    Attributes:
        code: Machine-readable kind, one of ``entity_unregistered``,
            ``spec_unparsable``, ``field_missing``, ``field_capability``,
            ``enum_value_gone``.
        message: A sentence naming what drifted.
        field: The offending field name, when the problem has one.
    """

    code: str
    message: str
    field: str | None = None


def _referenced_fields(spec: FilterSpec) -> dict[str, set[str]]:
    """Map every field the spec names to the uses it makes of it.

    Args:
        spec: A parsed filter spec.

    Returns:
        Field name to the set of uses (``filter`` / ``sort`` / ``select`` /
        ``group``) the spec makes of that field.
    """
    uses: dict[str, set[str]] = {}

    def _add(name: str, use: str) -> None:
        uses.setdefault(name, set()).add(use)

    def _walk(group: FilterGroup) -> None:
        for condition in group.conditions:
            _add(condition.field, "filter")
        for nested in group.groups:
            _walk(nested)

    _walk(spec.where)
    for sort in spec.sort:
        _add(sort.field, "sort")
    for name in spec.columns:
        _add(name, "select")
    for name in spec.group_by:
        _add(name, "group")
    return uses


#: Which ``FieldSpec`` flag each use requires.
_CAPABILITY_FLAG: dict[str, str] = {
    "filter": "filterable",
    "sort": "sortable",
    "select": "selectable",
    "group": "groupable",
}


def _enum_values_used(spec: FilterSpec, field_name: str) -> list[Any]:
    """Every literal a spec compares ``field_name`` against.

    ``in`` / ``not_in`` carry a list, so the members are unpacked; a bare
    comparison carries a scalar. ``is_null`` style operators carry nothing.

    Args:
        spec: A parsed filter spec.
        field_name: The field whose comparison values to collect.

    Returns:
        The literal values, in the order the spec mentions them.
    """
    found: list[Any] = []

    def _walk(group: FilterGroup) -> None:
        for condition in group.conditions:
            if condition.field != field_name or condition.value is None:
                continue
            if isinstance(condition.value, (list, tuple, set)):
                found.extend(condition.value)
            else:
                found.append(condition.value)
        for nested in group.groups:
            _walk(nested)

    _walk(spec.where)
    return found


def spec_problems(
    entity_type: str,
    raw_spec: dict[str, Any] | None,
    entity: QueryableEntity | None,
) -> list[SpecProblem]:
    """Compare a stored spec against the entity as it is registered right now.

    Pure and DB-free. This is the single source of truth for "has this view
    drifted": both the ERROR-severity rules below and :func:`describe_staleness`
    read it, so the list badge and the validation report can never disagree.

    Args:
        entity_type: The entity type recorded on the view.
        raw_spec: The stored spec JSON, as persisted.
        entity: The registered entity, or ``None`` if it is no longer
            registered.

    Returns:
        Every problem found, in a stable order. Empty means the view still
        binds.
    """
    if entity is None:
        return [
            SpecProblem(
                code="entity_unregistered",
                message=(f"The entity type {entity_type!r} is no longer registered, so this view cannot run"),
                field="entity_type",
            )
        ]

    try:
        spec = FilterSpec.model_validate(raw_spec or {})
    except Exception as exc:  # noqa: BLE001 - any parse failure is one problem
        return [
            SpecProblem(
                code="spec_unparsable",
                message=f"The stored filter spec no longer parses: {exc}",
                field="spec",
            )
        ]

    problems: list[SpecProblem] = []
    for name, uses in sorted(_referenced_fields(spec).items()):
        field_spec = entity.fields.get(name)
        if field_spec is None:
            problems.append(
                SpecProblem(
                    code="field_missing",
                    message=(
                        f"The field {name!r} is no longer available on {entity_type!r}, "
                        "so this view would report on something other than what it was saved for"
                    ),
                    field=name,
                )
            )
            continue
        for use in sorted(uses):
            flag = _CAPABILITY_FLAG[use]
            if not getattr(field_spec, flag, False):
                problems.append(
                    SpecProblem(
                        code="field_capability",
                        message=f"The field {name!r} on {entity_type!r} can no longer be used to {use}",
                        field=name,
                    )
                )
        if field_spec.kind == "enum" and field_spec.enum_values:
            allowed = {str(v) for v in field_spec.enum_values}
            gone = [v for v in _enum_values_used(spec, name) if str(v) not in allowed]
            for value in gone:
                problems.append(
                    SpecProblem(
                        code="enum_value_gone",
                        message=(
                            f"The filter on {name!r} compares against {value!r}, which is no longer "
                            "one of its values, so it can only ever match nothing"
                        ),
                        field=name,
                    )
                )
    return problems


def describe_staleness(
    entity_type: str,
    raw_spec: dict[str, Any] | None,
    entity: QueryableEntity | None,
) -> tuple[bool, list[str]]:
    """Whether a stored view still binds, and why not.

    The list-response form of :func:`spec_problems`: no engine, no database,
    cheap enough to run over every row so a list can mark its broken views.

    Args:
        entity_type: The entity type recorded on the view.
        raw_spec: The stored spec JSON, as persisted.
        entity: The registered entity, or ``None`` if unregistered.

    Returns:
        ``(is_stale, reasons)``.
    """
    problems = spec_problems(entity_type, raw_spec, entity)
    return (bool(problems), [p.message for p in problems])


# ── payload helpers ─────────────────────────────────────────────────────────


def _scope(context: ValidationContext) -> str:
    """The validation scope carried on the data (``view``)."""
    data = context.data
    if isinstance(data, dict):
        scope = data.get("scope")
        if isinstance(scope, str):
            return scope
    return ""


def _view(context: ValidationContext) -> dict[str, Any]:
    """The saved-view row payload in a view-scope context."""
    data = context.data
    if isinstance(data, dict):
        view = data.get("view")
        if isinstance(view, dict):
            return view
    return {}


def _problems(context: ValidationContext) -> list[SpecProblem]:
    """The pre-computed structural problems carried on the payload."""
    data = context.data
    if isinstance(data, dict):
        problems = data.get("problems")
        if isinstance(problems, list):
            return [p for p in problems if isinstance(p, SpecProblem)]
    return []


def _by_code(context: ValidationContext, code: str) -> list[SpecProblem]:
    """The structural problems of one kind."""
    return [p for p in _problems(context) if p.code == code]


def _facts(context: ValidationContext) -> dict[str, Any]:
    """The registry facts (caps, complexity) carried on the payload."""
    data = context.data
    if isinstance(data, dict):
        facts = data.get("entity_facts")
        if isinstance(facts, dict):
            return facts
    return {}


def _label(view: dict[str, Any]) -> str:
    """A human-readable handle for one view in a message."""
    name = str(view.get("name") or "").strip()
    return name or str(view.get("id") or "saved view")


def _result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    *,
    element_ref: str | None = None,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> RuleResult:
    """Build a RuleResult carrying this rule's own identity and severity."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=element_ref,
        suggestion=suggestion,
        details=details or {},
    )


def _skip(rule: ValidationRule) -> list[RuleResult]:
    """A rule that does not apply to this scope contributes nothing.

    Returning an empty list (rather than a passing result) keeps the report
    honest: a rule that never looked must not read as "passed".
    """
    return []


# ── Structural drift ────────────────────────────────────────────────────────


class SavedViewEntityRegistered(ValidationRule):
    """The entity a view queries must still be registered."""

    rule_id = "saved_views.entity_registered"
    name = "Saved view targets a registered entity"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "A view whose entity type has left the registry cannot run at all"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "view":
            return _skip(self)
        view = _view(context)
        entity_type = str(view.get("entity_type") or "")
        found = _by_code(context, "entity_unregistered")
        if found:
            return [
                _result(
                    self,
                    False,
                    found[0].message,
                    element_ref=_label(view),
                    suggestion=(
                        "Enable the module that owns this entity, or delete the view; "
                        "it can only fail while the entity is unregistered"
                    ),
                    details={"entity_type": entity_type},
                )
            ]
        return [
            _result(
                self,
                True,
                f"{entity_type!r} is registered",
                element_ref=_label(view),
                details={"entity_type": entity_type},
            )
        ]


class SavedViewSpecParses(ValidationRule):
    """The stored spec JSON must still parse as a filter spec."""

    rule_id = "saved_views.spec_parses"
    name = "Saved view spec still parses"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "A stored spec that no longer parses cannot be run or edited"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "view":
            return _skip(self)
        view = _view(context)
        if _by_code(context, "entity_unregistered"):
            return _skip(self)
        found = _by_code(context, "spec_unparsable")
        if found:
            return [
                _result(
                    self,
                    False,
                    found[0].message,
                    element_ref=_label(view),
                    suggestion="Rebuild the filter in the view editor and save it again",
                )
            ]
        return [_result(self, True, "The stored spec parses", element_ref=_label(view))]


class SavedViewFieldsWhitelisted(ValidationRule):
    """Every field the spec names must still be whitelisted on the entity."""

    rule_id = "saved_views.fields_whitelisted"
    name = "Saved view fields still exist"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A view referencing a field the entity no longer exposes reports on a different question"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "view":
            return _skip(self)
        view = _view(context)
        if _by_code(context, "entity_unregistered") or _by_code(context, "spec_unparsable"):
            return _skip(self)
        missing = _by_code(context, "field_missing")
        if missing:
            return [
                _result(
                    self,
                    False,
                    problem.message,
                    element_ref=_label(view),
                    suggestion="Edit the view and drop or replace the field",
                    details={"field": problem.field},
                )
                for problem in missing
            ]
        return [_result(self, True, "Every referenced field is whitelisted", element_ref=_label(view))]


class SavedViewFieldCapability(ValidationRule):
    """A field must still permit the use the spec makes of it."""

    rule_id = "saved_views.field_capability"
    name = "Saved view field uses are still permitted"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Filtering, sorting, selecting or grouping can be withdrawn from a field that still exists"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "view":
            return _skip(self)
        view = _view(context)
        if _by_code(context, "entity_unregistered") or _by_code(context, "spec_unparsable"):
            return _skip(self)
        withdrawn = _by_code(context, "field_capability")
        if withdrawn:
            return [
                _result(
                    self,
                    False,
                    problem.message,
                    element_ref=_label(view),
                    suggestion="Edit the view to stop using the field that way",
                    details={"field": problem.field},
                )
                for problem in withdrawn
            ]
        return [_result(self, True, "Every field use is still permitted", element_ref=_label(view))]


class SavedViewEnumValuesCurrent(ValidationRule):
    """An enum filter must compare against a value still in the vocabulary."""

    rule_id = "saved_views.enum_values_current"
    name = "Saved view enum filters are current"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A filter on a retired enum value matches nothing and reads as an empty result"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "view":
            return _skip(self)
        view = _view(context)
        if _by_code(context, "entity_unregistered") or _by_code(context, "spec_unparsable"):
            return _skip(self)
        gone = _by_code(context, "enum_value_gone")
        if gone:
            return [
                _result(
                    self,
                    False,
                    problem.message,
                    element_ref=_label(view),
                    suggestion="Pick a current value for the filter",
                    details={"field": problem.field},
                )
                for problem in gone
            ]
        return [_result(self, True, "Every enum filter uses a current value", element_ref=_label(view))]


# ── Sharing consistency ─────────────────────────────────────────────────────


class SavedViewShareScopeKnown(ValidationRule):
    """The share scope must be one the visibility check understands."""

    rule_id = "saved_views.share_scope_known"
    name = "Saved view share scope is known"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "An unrecognised share scope is treated as private, hiding a view its owner believes is shared"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "view":
            return _skip(self)
        view = _view(context)
        share_scope = str(view.get("share_scope") or "")
        if share_scope not in SHARE_SCOPES:
            return [
                _result(
                    self,
                    False,
                    f"Share scope {share_scope!r} is not one of {', '.join(SHARE_SCOPES)}",
                    element_ref=_label(view),
                    suggestion="Set the share scope again from the sharing menu",
                    details={"share_scope": share_scope},
                )
            ]
        return [
            _result(
                self,
                True,
                f"Share scope {share_scope!r} is known",
                element_ref=_label(view),
                details={"share_scope": share_scope},
            )
        ]


class SavedViewTeamShareHasTeam(ValidationRule):
    """A team share must still name a team."""

    rule_id = "saved_views.team_share_has_team"
    name = "Team-shared view still names its team"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Deleting a team clears the pin, and the share silently degrades to owner-only"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "view":
            return _skip(self)
        view = _view(context)
        if str(view.get("share_scope") or "") != "team":
            return _skip(self)
        if view.get("shared_team_id") is None:
            return [
                _result(
                    self,
                    False,
                    "This view is shared with a team that no longer exists, so only its owner can see it",
                    element_ref=_label(view),
                    suggestion="Share it with an existing team, or change the scope to project",
                )
            ]
        return [
            _result(
                self,
                True,
                "The team share names an existing team",
                element_ref=_label(view),
                details={"shared_team_id": str(view.get("shared_team_id"))},
            )
        ]


class SavedViewSharedViewPinned(ValidationRule):
    """A shared view must carry the project pin its readers are checked against."""

    rule_id = "saved_views.shared_view_pinned"
    name = "Shared view is pinned to a project"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Visibility for a shared view is decided against its own project, so an unpinned share reaches nobody"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "view":
            return _skip(self)
        view = _view(context)
        share_scope = str(view.get("share_scope") or "")
        if share_scope == "private":
            return _skip(self)
        if view.get("project_id") is None:
            return [
                _result(
                    self,
                    False,
                    (
                        f"This view is shared as {share_scope!r} but is not pinned to a project, "
                        "so nobody but its owner can be admitted to it"
                    ),
                    element_ref=_label(view),
                    suggestion="Pin the view to the project it belongs to, or make it private",
                    details={"share_scope": share_scope},
                )
            ]
        return [_result(self, True, "The shared view is pinned to a project", element_ref=_label(view))]


# ── Budget and usability ────────────────────────────────────────────────────


class SavedViewWithinComplexityBudget(ValidationRule):
    """The spec should sit clear of the static complexity ceiling."""

    rule_id = "saved_views.within_complexity_budget"
    name = "Saved view is within its complexity budget"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "A spec at the complexity ceiling is refused outright the next time a condition is added"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "view":
            return _skip(self)
        view = _view(context)
        facts = _facts(context)
        complexity = facts.get("complexity")
        ceiling = facts.get("complexity_ceiling")
        if not isinstance(complexity, int) or not isinstance(ceiling, int) or ceiling <= 0:
            return _skip(self)
        details = {"complexity": complexity, "ceiling": ceiling}
        if complexity >= ceiling * _COMPLEXITY_WARN_RATIO:
            return [
                _result(
                    self,
                    False,
                    f"The spec scores {complexity} against a ceiling of {ceiling}",
                    element_ref=_label(view),
                    suggestion="Split it into two views, or drop a condition, before it is refused",
                    details=details,
                )
            ]
        return [
            _result(
                self,
                True,
                f"The spec scores {complexity} against a ceiling of {ceiling}",
                element_ref=_label(view),
                details=details,
            )
        ]


class SavedViewPageSizeWithinCap(ValidationRule):
    """The saved page size should not exceed the entity cap."""

    rule_id = "saved_views.page_size_within_cap"
    name = "Saved page size is within the entity cap"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = (
        "A page size above the cap is clamped without telling anyone, so the view returns fewer rows than it asks for"
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "view":
            return _skip(self)
        view = _view(context)
        facts = _facts(context)
        page_size = facts.get("page_size")
        cap = facts.get("row_cap")
        if not isinstance(page_size, int) or not isinstance(cap, int) or cap <= 0:
            return _skip(self)
        details = {"page_size": page_size, "row_cap": cap}
        if page_size > cap:
            return [
                _result(
                    self,
                    False,
                    f"The view asks for {page_size} rows a page but the cap is {cap}",
                    element_ref=_label(view),
                    suggestion=f"Save it at {cap} rows a page so the number shown is the number returned",
                    details=details,
                )
            ]
        return [
            _result(
                self,
                True,
                f"The page size {page_size} is within the cap of {cap}",
                element_ref=_label(view),
                details=details,
            )
        ]


class SavedViewSpecIsNotEmpty(ValidationRule):
    """A saved view should actually narrow or shape something."""

    rule_id = "saved_views.spec_is_not_empty"
    name = "Saved view narrows or shapes its register"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A view with no filter, no sort and no column choice saves nothing the register did not already do"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "view":
            return _skip(self)
        view = _view(context)
        facts = _facts(context)
        if not facts.get("spec_parsed", False):
            return _skip(self)
        if facts.get("spec_is_empty", False):
            return [
                _result(
                    self,
                    False,
                    "This view saves no filter, no sort and no column choice",
                    element_ref=_label(view),
                    suggestion="Add the filter that makes this view worth opening, or delete it",
                )
            ]
        return [_result(self, True, "The view narrows or shapes its register", element_ref=_label(view))]


class SavedViewSharedViewDescribed(ValidationRule):
    """A view other people can see should say what it is for."""

    rule_id = "saved_views.shared_view_described"
    name = "Shared view carries a description"
    standard = "universal"
    severity = Severity.INFO
    category = RuleCategory.QUALITY
    description = "A colleague opening a shared view has only its name to go on unless it is described"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "view":
            return _skip(self)
        view = _view(context)
        share_scope = str(view.get("share_scope") or "")
        if share_scope == "private":
            return _skip(self)
        if not str(view.get("description") or "").strip():
            return [
                _result(
                    self,
                    False,
                    "This view is shared with other people but does not say what it is for",
                    element_ref=_label(view),
                    suggestion="Add a line describing the question this view answers",
                    details={"share_scope": share_scope},
                )
            ]
        return [_result(self, True, "The shared view carries a description", element_ref=_label(view))]


# ── Registration ────────────────────────────────────────────────────────────

_RULES: tuple[type[ValidationRule], ...] = (
    SavedViewEntityRegistered,
    SavedViewSpecParses,
    SavedViewFieldsWhitelisted,
    SavedViewFieldCapability,
    SavedViewEnumValuesCurrent,
    SavedViewShareScopeKnown,
    SavedViewTeamShareHasTeam,
    SavedViewSharedViewPinned,
    SavedViewWithinComplexityBudget,
    SavedViewPageSizeWithinCap,
    SavedViewSpecIsNotEmpty,
    SavedViewSharedViewDescribed,
)


def register_saved_views_rules() -> None:
    """Register every saved-views rule under the ``saved_views`` rule set.

    Idempotent - the registry overwrites by rule id, so a re-import or a hot
    reload re-registers cleanly. Called at import time below (the module loader
    imports every module's ``validators``) and again from the module's
    ``on_startup`` hook, because the platform has two registration routes and a
    rule that only takes one of them is dormant in the other deployment.
    """
    for rule_cls in _RULES:
        rule_registry.register(rule_cls(), [SAVED_VIEWS_RULE_SET])
    logger.debug("Registered %d saved-views validation rules", len(_RULES))


register_saved_views_rules()


# ── Orchestration used by the service ───────────────────────────────────────


def _finding(result: RuleResult) -> SavedViewFinding:
    """Render one failing rule result as a UI-ready finding."""
    return SavedViewFinding(
        rule_id=result.rule_id,
        severity=result.severity.value,
        category=result.category.value,
        message=result.message,
        key=f"saved_views.validation.{result.rule_id}",
        element_ref=result.element_ref,
        suggestion=result.suggestion,
        context=dict(result.details or {}),
    )


def _to_report(
    report: ValidationReport,
    *,
    target_type: str,
    target_id: Any,
) -> SavedViewValidationReport:
    """Collapse an engine report into the module's response shape."""
    return SavedViewValidationReport(
        target_type=target_type,
        target_id=target_id,
        status=report.status.value,
        error_count=len(report.errors),
        warning_count=len(report.warnings),
        info_count=len(report.infos),
        passed_count=len(report.passed_rules),
        findings=[_finding(r) for r in report.results if not r.passed and not r.is_engine_error],
        unsupported_rule_sets=list(report.unsupported_rule_sets),
    )


def _degraded(target_type: str, target_id: Any) -> SavedViewValidationReport:
    """The report returned when the engine itself could not run.

    SKIPPED, not PASSED: nothing was checked, and saying otherwise would turn
    an infrastructure failure into a clean bill of health.
    """
    return SavedViewValidationReport(
        target_type=target_type,
        target_id=target_id,
        status=ValidationStatus.SKIPPED.value,
        error_count=0,
        warning_count=0,
        info_count=0,
        passed_count=0,
        findings=[],
        unsupported_rule_sets=[SAVED_VIEWS_RULE_SET],
    )


async def evaluate_view(
    payload: dict[str, Any],
    *,
    project_id: str | None = None,
    locale: str = "",
) -> SavedViewValidationReport:
    """Run the view-scope saved-views rules over one stored definition.

    Args:
        payload: Carries ``view`` (the row as a plain dict), ``problems`` (the
            :func:`spec_problems` output) and ``entity_facts`` (registry caps
            and the spec's static complexity).
        project_id: The project the view belongs to, for the report header.
        locale: The caller's locale, carried through to the report metadata.

    Returns:
        The findings, or a SKIPPED report if the engine itself failed.
    """
    view = payload.get("view") or {}
    target_id = view.get("id")
    data = {"scope": "view", **payload}
    try:
        report = await validation_engine.validate(
            data=data,
            rule_sets=[SAVED_VIEWS_RULE_SET],
            target_type="saved_view",
            target_id=str(target_id or ""),
            project_id=project_id,
            metadata={"locale": locale},
        )
    except Exception:  # noqa: BLE001 - validation augments; never break the caller
        logger.warning("saved view validation failed for %s", target_id, exc_info=True)
        return _degraded("saved_view", target_id)
    return _to_report(report, target_type="saved_view", target_id=target_id)
