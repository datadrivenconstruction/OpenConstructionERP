# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""List-views validation rules.

All rules register under the ``list_views`` rule set and read one payload:
``{"view": {"name", "scope_key", "state", "is_shared"}}``. ERROR rules block a
save; WARNING rules come back with the saved view so the picker can show them
next to the view name.

* ``list_views.name_present``          - ERROR. A view needs a visible name.
* ``list_views.scope_key_format``      - ERROR. The page key must be a plain key.
* ``list_views.state_size``            - ERROR. The layout stays under 32 KB.
* ``list_views.sort_column_visible``   - WARNING. Sorting by a hidden column.
* ``list_views.filter_column_visible`` - WARNING. Filtering on a hidden column.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.list_views.schemas import SCOPE_KEY_PATTERN

logger = logging.getLogger(__name__)

LIST_VIEWS_RULE_SET = "list_views"
MAX_STATE_BYTES = 32 * 1024


def _view(context: ValidationContext) -> dict[str, Any]:
    data = context.data
    if isinstance(data, dict) and isinstance(data.get("view"), dict):
        return data["view"]
    return {}


def _state(view: dict[str, Any]) -> dict[str, Any]:
    state = view.get("state")
    return state if isinstance(state, dict) else {}


def _label(view: dict[str, Any]) -> str:
    return str(view.get("name") or view.get("scope_key") or "list view")


def _result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    view: dict[str, Any],
    *,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=_label(view),
        details=details or {},
        suggestion=suggestion,
    )


class ListViewNamePresent(ValidationRule):
    """A view must carry a non-blank name."""

    rule_id = "list_views.name_present"
    name = "List view has a name"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A nameless view cannot be told apart in the view picker"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        view = _view(context)
        ok = bool(str(view.get("name") or "").strip())
        if ok:
            return [_result(self, True, "The view has a name", view)]
        return [_result(self, False, "The view has no name", view, suggestion="Give the view a short name")]


class ListViewScopeKeyFormat(ValidationRule):
    """The page key must be a plain identifier or route."""

    rule_id = "list_views.scope_key_format"
    name = "List view page key is well formed"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A malformed page key would attach the view to no page"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        view = _view(context)
        key = str(view.get("scope_key") or "")
        ok = re.fullmatch(SCOPE_KEY_PATTERN, key) is not None
        msg = f"Page key {key!r} is well formed" if ok else f"Page key {key!r} is not a valid page key"
        return [_result(self, ok, msg, view, details={"scope_key": key})]


class ListViewStateSize(ValidationRule):
    """The saved layout must stay small."""

    rule_id = "list_views.state_size"
    name = "List view layout stays small"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Layouts load with every list page; an oversized one slows every visit"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        view = _view(context)
        size = len(json.dumps(_state(view), separators=(",", ":")).encode())
        ok = size <= MAX_STATE_BYTES
        msg = f"Layout is {size} bytes" + ("" if ok else f", above the {MAX_STATE_BYTES} byte limit")
        return [_result(self, ok, msg, view, details={"bytes": size})]


class ListViewSortColumnVisible(ValidationRule):
    """Sorting by a hidden column reads as an unsorted list."""

    rule_id = "list_views.sort_column_visible"
    name = "List view sorts by a visible column"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "A list sorted by a column nobody can see looks random"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        view = _view(context)
        state = _state(view)
        sort = state.get("sort") if isinstance(state.get("sort"), dict) else None
        columns = [c for c in state.get("columns") or [] if isinstance(c, str)]
        if not sort or not columns:
            return []
        key = str(sort.get("key") or "")
        if key in columns:
            return [_result(self, True, f"Sorted by visible column {key!r}", view, details={"sort_key": key})]
        return [
            _result(
                self,
                False,
                f"Sorted by hidden column {key!r}",
                view,
                suggestion="Show the column or sort by another one",
                details={"sort_key": key},
            )
        ]


class ListViewFilterColumnVisible(ValidationRule):
    """A filter on a hidden column hides rows for no visible reason."""

    rule_id = "list_views.filter_column_visible"
    name = "List view filters only visible columns"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Rows filtered out by a column nobody can see look missing"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        view = _view(context)
        state = _state(view)
        columns = [c for c in state.get("columns") or [] if isinstance(c, str)]
        filters = state.get("filters") if isinstance(state.get("filters"), dict) else {}
        if not columns or not filters:
            return []
        hidden = sorted(k for k in filters if k not in columns)
        if not hidden:
            return [_result(self, True, "Every filter is on a visible column", view)]
        return [
            _result(
                self,
                False,
                f"Filters on hidden columns: {', '.join(hidden)}",
                view,
                suggestion="Show those columns or clear their filters",
                details={"hidden": hidden},
            )
        ]


_RULES: tuple[type[ValidationRule], ...] = (
    ListViewNamePresent,
    ListViewScopeKeyFormat,
    ListViewStateSize,
    ListViewSortColumnVisible,
    ListViewFilterColumnVisible,
)


def register_list_views_rules() -> None:
    """Register every list-views rule; idempotent (the registry overwrites by id)."""
    for rule_cls in _RULES:
        rule_registry.register(rule_cls(), [LIST_VIEWS_RULE_SET])
    logger.debug("Registered %d list-views validation rules", len(_RULES))


register_list_views_rules()


async def check_view(view: dict[str, Any]) -> list[RuleResult]:
    """Run every list-views rule on one payload and return the failing results."""
    context = ValidationContext(data={"view": view})
    failing: list[RuleResult] = []
    for rule_cls in _RULES:
        failing.extend(r for r in await rule_cls().validate(context) if not r.passed)
    return failing
