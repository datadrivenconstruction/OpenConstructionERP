# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rules for saved searches.

A saved search is a promise: click it later and the same evidence comes back.
Most of the ways that promise breaks are silent, because a search that returns
nothing looks exactly like a project with nothing in it. These rules turn each
of those into a finding at the moment the search is pinned, when the person is
still looking at the facets and can fix them.

Four rules in the ``retrieval_saved_search`` rule set:

* ``retrieval_saved_search.label_present``     - ERROR. A pin needs a name.
  A list of unnamed rows is a list nobody can pick from.
* ``retrieval_saved_search.has_facet``         - ERROR. At least one facet must
  be set. An all-empty search means "everything", which is worth running and
  not worth pinning: every empty pin is the same pin.
* ``retrieval_saved_search.date_window_sane``  - ERROR. Date bounds must be ISO
  calendar dates, and a two-sided window must not run backwards. The facet
  engine compares these as strings, so ``20/06/2026`` and a reversed window
  both filter everything out without complaining.
* ``retrieval_saved_search.known_record_type`` - WARNING, not an error. The
  search endpoint indexes exactly three record types; a pin naming anything
  else can only ever come back empty. It stays a warning because the indexed
  set is expected to grow, and a pin written ahead of that should be saved
  rather than refused.

Every rule reads the plain facet dict the service hands it, so none of them
needs a database session and all of them are unit-testable in isolation.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.retrieval.saved_search_logic import (
    FACET_FIELDS,
    INDEXED_RECORD_TYPES,
    date_window_ordered,
    is_iso_date,
    is_meaningful,
)

logger = logging.getLogger(__name__)

#: The rule set every saved-search rule registers under, and the one the
#: service passes to ``validation_engine.validate``.
RETRIEVAL_SAVED_SEARCH_RULE_SET = "retrieval_saved_search"


def _facets(context: ValidationContext) -> dict[str, str]:
    """The facet mapping carried on the context (or an empty one)."""
    data = context.data if isinstance(context.data, dict) else {}
    raw = data.get("query")
    if not isinstance(raw, dict):
        return dict.fromkeys(FACET_FIELDS, "")
    return {field: str(raw.get(field) or "") for field in FACET_FIELDS}


def _label(context: ValidationContext) -> str:
    """The label carried on the context, trimmed."""
    data = context.data if isinstance(context.data, dict) else {}
    return str(data.get("label") or "").strip()


def _result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    *,
    element_ref: str | None = None,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> RuleResult:
    """Build a RuleResult carrying the rule's own id / name / severity / category."""
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


class SavedSearchLabelPresent(ValidationRule):
    """A pinned search must carry a non-empty label."""

    rule_id = "retrieval_saved_search.label_present"
    name = "Saved Search Has A Label"
    standard = "retrieval_saved_search"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A saved search must be named, otherwise the list cannot be read."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        label = _label(context)
        if label:
            return [_result(self, True, "OK")]
        return [
            _result(
                self,
                False,
                "The saved search has no label.",
                suggestion="Give the search a short name describing what it finds.",
            )
        ]


class SavedSearchHasFacet(ValidationRule):
    """A pinned search must narrow the record by at least one facet."""

    rule_id = "retrieval_saved_search.has_facet"
    name = "Saved Search Narrows Something"
    standard = "retrieval_saved_search"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A saved search with no facets is the whole project record and pins nothing."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        facets = _facets(context)
        if is_meaningful(facets):
            return [_result(self, True, "OK")]
        return [
            _result(
                self,
                False,
                "The saved search sets no facets, so it matches the entire project record.",
                suggestion="Add search text, or narrow by party, record type, reference or date.",
                details={"facets": FACET_FIELDS},
            )
        ]


class SavedSearchDateWindowSane(ValidationRule):
    """Date bounds must be ISO dates, and a two-sided window must run forwards."""

    rule_id = "retrieval_saved_search.date_window_sane"
    name = "Saved Search Date Window Is Usable"
    standard = "retrieval_saved_search"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = (
        "Date facets are compared as ISO strings, so a malformed or reversed window silently filters every record out."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        facets = _facets(context)
        date_from = facets.get("date_from", "")
        date_to = facets.get("date_to", "")
        if not date_from and not date_to:
            # No window at all: nothing to check, and reporting a pass here
            # would let a search with no dates collect a mark for a check that
            # never examined anything.
            return []

        problems: list[str] = []
        for field, value in (("date_from", date_from), ("date_to", date_to)):
            if value and not is_iso_date(value):
                problems.append(f"{field} '{value}' is not an ISO calendar date (YYYY-MM-DD)")
        if not problems and not date_window_ordered(date_from, date_to):
            problems.append(f"the window runs backwards: {date_from} is after {date_to}")

        if not problems:
            return [_result(self, True, "OK")]
        return [
            _result(
                self,
                False,
                f"The saved search date window is unusable: {'; '.join(problems)}.",
                suggestion="Use YYYY-MM-DD for both bounds and put the earlier date first.",
                details={"date_from": date_from, "date_to": date_to, "problems": problems},
            )
        ]


class SavedSearchKnownRecordType(ValidationRule):
    """A record-type facet must name a type the search endpoint indexes."""

    rule_id = "retrieval_saved_search.known_record_type"
    name = "Saved Search Record Type Is Indexed"
    standard = "retrieval_saved_search"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "Retrieval indexes documents, correspondence and change orders. A search pinned "
        "to any other record type can only ever return nothing."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record_type = _facets(context).get("record_type", "")
        if not record_type:
            return []
        if record_type in INDEXED_RECORD_TYPES:
            return [_result(self, True, "OK", element_ref=record_type)]
        return [
            _result(
                self,
                False,
                f"Record type '{record_type}' is not indexed, so this search returns nothing.",
                element_ref=record_type,
                suggestion=f"Use one of: {', '.join(INDEXED_RECORD_TYPES)}, or clear the filter.",
                details={"record_type": record_type, "indexed": list(INDEXED_RECORD_TYPES)},
            )
        ]


_SAVED_SEARCH_RULES: tuple[ValidationRule, ...] = (
    SavedSearchLabelPresent(),
    SavedSearchHasFacet(),
    SavedSearchDateWindowSane(),
    SavedSearchKnownRecordType(),
)


def register_retrieval_rules() -> None:
    """Register the saved-search rules with the core rule registry.

    Idempotent - the registry overwrites a rule by id, so a re-import or hot
    reload re-registers cleanly. Called from the module ``on_startup`` hook,
    which is what makes ``retrieval_saved_search`` a reachable rule set rather
    than a name nothing answers to.
    """
    for rule in _SAVED_SEARCH_RULES:
        rule_registry.register(rule, [RETRIEVAL_SAVED_SEARCH_RULE_SET])
    logger.debug("Registered %d retrieval validation rules", len(_SAVED_SEARCH_RULES))


__all__ = [
    "RETRIEVAL_SAVED_SEARCH_RULE_SET",
    "SavedSearchDateWindowSane",
    "SavedSearchHasFacet",
    "SavedSearchKnownRecordType",
    "SavedSearchLabelPresent",
    "register_retrieval_rules",
]
