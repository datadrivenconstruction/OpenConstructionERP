# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules of the technical request register (rule set ``rfi``).

Two rules, both reading the pure functions in
:mod:`app.modules.rfi.request_types` that the create and issue paths enforce:

* ``rfi.request_type_required_fields`` - every issued request (anything past
  ``draft`` and not ``void``) carries the fields its type requires.
* ``rfi.request_type_catalogue_consistent`` - the project's catalogue has
  unique codes and prefixes and valid shapes, and every request names a type
  the catalogue still has.

``context.data`` is ``{"types": [RequestTypeSpec, ...], "requests": [dict, ...]}``
as :meth:`app.modules.rfi.service.RFIService.validate_register` builds it.
"""

from __future__ import annotations

from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.rfi.request_types import RequestTypeSpec, catalogue_problems, missing_required_fields

__all__ = [
    "RFI_RULE_SET",
    "RequestTypeCatalogueConsistent",
    "RequestTypeRequiredFields",
    "register_rfi_rules",
]

RFI_RULE_SET = "rfi"

# A request in these states has been issued to the other party, so the fields
# its type requires are owed. ``void`` was withdrawn and owes nothing.
_ISSUED_STATUSES = frozenset({"open", "answered", "closed"})


def _payload(context: ValidationContext) -> tuple[list[RequestTypeSpec], list[dict[str, Any]]]:
    data = context.data if isinstance(context.data, dict) else {}
    types = [t for t in data.get("types", []) if isinstance(t, RequestTypeSpec)]
    requests = [r for r in data.get("requests", []) if isinstance(r, dict)]
    return types, requests


class RequestTypeRequiredFields(ValidationRule):
    """Each issued request carries the fields its type requires."""

    rule_id = "rfi.request_type_required_fields"
    name = "Request carries the fields its type requires"
    standard = "rfi"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = (
        "A request past draft must carry every field its type requires, for example the "
        "specification a deviation or concession request departs from."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        types, requests = _payload(context)
        by_code = {t.code: t for t in types}
        results: list[RuleResult] = []
        for req in requests:
            spec = by_code.get(str(req.get("request_type") or ""))
            if spec is None or req.get("status") not in _ISSUED_STATUSES:
                continue
            missing = missing_required_fields(spec, req)
            if missing:
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=self.severity,
                        category=self.category,
                        passed=False,
                        message=f"{req.get('rfi_number')} is missing: {', '.join(missing)}",
                        element_ref=str(req.get("id")),
                        details={"request_type": spec.code, "missing": missing, "rfi_number": req.get("rfi_number")},
                        suggestion="Fill the fields the request type requires.",
                    )
                )
        if not results:
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message="Every issued request carries the fields its type requires.",
                    element_ref=context.project_id,
                )
            )
        return results


class RequestTypeCatalogueConsistent(ValidationRule):
    """The catalogue is usable and every request names a type it holds."""

    rule_id = "rfi.request_type_catalogue_consistent"
    name = "Request type catalogue is consistent"
    standard = "rfi"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = (
        "Request type codes and number prefixes are unique in the project, each type has a valid "
        "shape, and every request names a type the catalogue still holds."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        types, requests = _payload(context)
        results: list[RuleResult] = []
        for problem in catalogue_problems(types):
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=problem.detail,
                    element_ref=problem.type_code,
                    details={"problem": problem.code, "request_type": problem.type_code},
                )
            )
        known = {t.code for t in types}
        orphans: dict[str, list[str]] = {}
        for req in requests:
            code = str(req.get("request_type") or "")
            if code not in known:
                orphans.setdefault(code, []).append(str(req.get("rfi_number")))
        for code, numbers in sorted(orphans.items()):
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=f"{len(numbers)} request(s) name type {code!r}, which is not in the catalogue",
                    element_ref=code,
                    details={"problem": "unknown_type", "request_type": code, "requests": numbers[:20]},
                    suggestion="Add the type back to the catalogue, or load the preset it came from.",
                )
            )
        if not results:
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message="The request type catalogue is consistent.",
                    element_ref=context.project_id,
                )
            )
        return results


def register_rfi_rules() -> None:
    """Register the register's rules under the ``rfi`` rule set (the registry is keyed by id, so this is idempotent)."""
    rule_registry.register(RequestTypeRequiredFields(), rule_sets=[RFI_RULE_SET])
    rule_registry.register(RequestTypeCatalogueConsistent(), rule_sets=[RFI_RULE_SET])
