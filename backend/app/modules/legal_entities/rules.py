# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ``entity.*`` rules registered with the validation engine (rule set ``legal_entities``).

Each rule wraps one pure check from :mod:`app.modules.legal_entities.validators`
and reads a plain dict context; every section is optional and a rule judges
only what it finds::

    {
        "entity": {"id", "code", "country_code", "is_active", "tax_ids"},
        "project": {"id", "legal_entity_id", "legal_entity_branch_id", "is_new"},
        "site": {"legal_entity_id"},
        "seller": {...EN 16931 seller fields...},
        "default_entity_exists": bool,
        "entities_exist": bool,
        "linked_entity_ids": [...],
    }

The message is the rule's English text; screens show the translation keyed by
the rule id (``validation.entity.*``) and fall back to it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.legal_entities import validators as v

RULE_SET = "legal_entities"


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


class _EntityRule(ValidationRule):
    standard = RULE_SET
    category = RuleCategory.CONSISTENCY
    check: Callable[[dict[str, Any]], list[v.Issue]]

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        ref = str(_section(data, "project").get("id") or _section(data, "entity").get("id") or "")
        found = type(self).check(data)
        if not found:
            return [RuleResult(self.rule_id, self.name, self.severity, self.category, True, "OK", element_ref=ref)]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=Severity.ERROR if i.severity == "error" else Severity.WARNING,
                category=self.category,
                passed=False,
                message=i.message,
                element_ref=ref,
                details={"field": i.field},
            )
            for i in found
        ]


def _rule(rule_id: str, name: str, severity: Severity, check: Callable[[dict[str, Any]], list[v.Issue]]) -> type:
    return type(
        rule_id.replace(".", "_"),
        (_EntityRule,),
        {"rule_id": rule_id, "name": name, "severity": severity, "description": name, "check": staticmethod(check)},
    )


def _tax_format(d: dict[str, Any]) -> list[v.Issue]:
    e = _section(d, "entity")
    return v.check_tax_ids(str(e.get("country_code") or ""), e.get("tax_ids")) if e else []


def _inactive(d: dict[str, Any]) -> list[v.Issue]:
    e, p = _section(d, "entity"), _section(d, "project")
    if not e or not p.get("is_new"):
        return []
    return v.check_active_for_new_project(code=str(e.get("code") or ""), is_active=bool(e.get("is_active", True)))


def _site(d: dict[str, Any]) -> list[v.Issue]:
    site, p = _section(d, "site"), _section(d, "project")
    if not site:
        return []
    return v.check_site_entity(site_entity_id=site.get("legal_entity_id"), entity_id=p.get("legal_entity_id"))


def _without(d: dict[str, Any]) -> list[v.Issue]:
    p = _section(d, "project")
    if not p:
        return []
    return v.check_project_has_entity(
        assigned=p.get("legal_entity_id") is not None,
        default_exists=bool(d.get("default_entity_exists")),
        entities_exist=bool(d.get("entities_exist")),
    )


def _seller(d: dict[str, Any]) -> list[v.Issue]:
    if "seller" not in d:
        return []
    e = _section(d, "entity")
    return v.check_seller_complete(
        _section(d, "seller"), e.get("country_code") or _section(d, "seller").get("country_code")
    )


def _cross(d: dict[str, Any]) -> list[v.Issue]:
    return v.check_cross_entity(list(d.get("linked_entity_ids") or []))


RULES = (
    _rule("entity.tax_id_format", "Tax id matches the country format", Severity.WARNING, _tax_format),
    _rule("entity.inactive_on_new_project", "Inactive company takes no new project", Severity.ERROR, _inactive),
    _rule("entity.site_wrong_entity", "Site belongs to the project's company", Severity.ERROR, _site),
    _rule("entity.project_without_entity", "Project has a company", Severity.ERROR, _without),
    _rule("entity.invoice_seller_incomplete", "Seller details complete", Severity.ERROR, _seller),
    _rule("entity.cross_entity_reference", "Records of one company only", Severity.WARNING, _cross),
)


def register_legal_entities_validation_rules() -> None:
    """Register the ``entity.*`` rules with the platform rule registry."""
    for rule_class in RULES:
        rule_registry.register(rule_class(), [RULE_SET])


__all__ = ["RULES", "RULE_SET", "register_legal_entities_validation_rules"]
