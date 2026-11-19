# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set ``bundle``: a bundled tender checked on publish, on award and on call-off.

The service builds one plain payload and every rule reads only its own part, so a
rule never queries the database::

    {
        "currency": "EUR",
        "entities_exist": bool,              # legal entities are in use on this install
        "tolerance_pct": "0",
        "lines": [{"code", "unit", "quantity", "shares": [{"project", "quantity", "cost_line_id"}]}],
        "projects": [{"name", "legal_entity_id", "net", "budget"}],
        "award": {"total", "split_sum"},
        "call_off": {"project", "in_bundle", "lines": [{"code", "unit", "used", "share"}]},
    }

Rules (``bundle.*``; errors block publish and award, warnings inform):
    project_share_missing      error   a line has no share for a project
    share_sum_mismatch         error   the shares of a line do not add up to its quantity
    share_cost_line_missing    warning a share has no cost line, so no cost report shows it
    entity_missing             error   a project has no legal entity while entities are in use
    project_over_budget        warning a project's award exceeds its budget
    award_split_unreconciled   error   the project shares do not add up to the award
    calloff_project_not_in_bundle error a call-off names a project outside the bundle
    calloff_over_share         warning a call-off takes a project past its share of a line
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.currency_registry import sentence_amount
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.core.validation.messages import translate
from app.modules.central_purchasing.split import budget_check

RULE_SET = "bundle"


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _qty(value: Decimal) -> str:
    """A quantity as people write it: no trailing zeros, thousands grouped."""
    text = f"{value.normalize():,f}"
    return text


def _list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [x for x in (data.get(key) or []) if isinstance(x, dict)]


Finding = tuple[str, dict[str, Any]]


def project_share_missing(data: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for line in _list(data, "lines"):
        for share in line.get("shares") or []:
            if _dec(share.get("quantity")) is None:
                out.append((f"line:{line.get('code')}", {"code": line.get("code"), "project": share.get("project")}))
    return out


def share_sum_mismatch(data: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for line in _list(data, "lines"):
        qty = _dec(line.get("quantity")) or Decimal("0")
        total = sum((_dec(s.get("quantity")) or Decimal("0") for s in line.get("shares") or []), Decimal("0"))
        if total != qty:
            out.append((f"line:{line.get('code')}", {"code": line.get("code"), "sum": _qty(total), "qty": _qty(qty)}))
    return out


def share_cost_line_missing(data: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for line in _list(data, "lines"):
        for share in line.get("shares") or []:
            qty = _dec(share.get("quantity"))
            if qty and not share.get("cost_line_id"):
                out.append((f"line:{line.get('code')}", {"code": line.get("code"), "project": share.get("project")}))
    return out


def entity_missing(data: dict[str, Any]) -> list[Finding]:
    if not data.get("entities_exist"):
        return []
    return [
        (f"project:{p.get('name')}", {"project": p.get("name")})
        for p in _list(data, "projects")
        if not p.get("legal_entity_id")
    ]


def project_over_budget(data: dict[str, Any]) -> list[Finding]:
    cur = str(data.get("currency") or "")
    tol = _dec(data.get("tolerance_pct")) or Decimal("0")
    out: list[Finding] = []
    for p in _list(data, "projects"):
        net = _dec(p.get("net"))
        if net is None:
            continue
        check = budget_check(net, _dec(p.get("budget")), tol)
        if check.over:
            out.append(
                (
                    f"project:{p.get('name')}",
                    {
                        "project": p.get("name"),
                        "net": sentence_amount(net, cur),
                        "budget": sentence_amount(_dec(p.get("budget")) or Decimal("0"), cur),
                        "delta": sentence_amount(check.delta, cur),
                    },
                )
            )
    return out


def award_split_unreconciled(data: dict[str, Any]) -> list[Finding]:
    award = data.get("award")
    if not isinstance(award, dict):
        return []
    total, got = _dec(award.get("total")), _dec(award.get("split_sum"))
    if total is None or got is None or total == got:
        return []
    cur = str(data.get("currency") or "")
    return [("award", {"sum": sentence_amount(got, cur), "total": sentence_amount(total, cur)})]


def calloff_project_not_in_bundle(data: dict[str, Any]) -> list[Finding]:
    call = data.get("call_off")
    if not isinstance(call, dict) or call.get("in_bundle", True):
        return []
    return [(f"project:{call.get('project')}", {"project": call.get("project")})]


def calloff_over_share(data: dict[str, Any]) -> list[Finding]:
    call = data.get("call_off")
    if not isinstance(call, dict) or not call.get("in_bundle", True):
        return []
    out: list[Finding] = []
    for line in [x for x in call.get("lines") or [] if isinstance(x, dict)]:
        used, share = _dec(line.get("used")), _dec(line.get("share"))
        if used is None or share is None or used <= share:
            continue
        out.append(
            (
                f"line:{line.get('code')}",
                {
                    "project": call.get("project"),
                    "used": _qty(used),
                    "share": _qty(share),
                    "unit": line.get("unit") or "",
                    "code": line.get("code"),
                },
            )
        )
    return out


#: (key, severity, name, check) in the order the spec lists them.
CHECKS: tuple[tuple[str, Severity, str, Any], ...] = (
    ("project_share_missing", Severity.ERROR, "Every project has a share of every line", project_share_missing),
    ("share_sum_mismatch", Severity.ERROR, "Shares add up to the line quantity", share_sum_mismatch),
    ("share_cost_line_missing", Severity.WARNING, "Every share has a cost line", share_cost_line_missing),
    ("entity_missing", Severity.ERROR, "Every project has a legal entity", entity_missing),
    ("project_over_budget", Severity.WARNING, "Project award within its budget", project_over_budget),
    ("award_split_unreconciled", Severity.ERROR, "Project shares add up to the award", award_split_unreconciled),
    (
        "calloff_project_not_in_bundle",
        Severity.ERROR,
        "Call-off project is in the bundle",
        calloff_project_not_in_bundle,
    ),
    ("calloff_over_share", Severity.WARNING, "Call-off within the project share", calloff_over_share),
)


class _BundleRule(ValidationRule):
    standard = RULE_SET
    category = RuleCategory.CONSISTENCY
    key = ""
    check: Any = None

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        locale = str((context.metadata or {}).get("locale") or "en")
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=translate(f"{RULE_SET}.{self.key}.fail", locale=locale, **params),
                element_ref=ref,
                details={f"param_{k}": str(v) for k, v in params.items()},
                suggestion=translate(f"{RULE_SET}.{self.key}.suggestion", locale=locale),
            )
            for ref, params in type(self).check(data)
        ]


RULES: tuple[type[_BundleRule], ...] = tuple(
    type(
        f"Bundle_{key}",
        (_BundleRule,),
        {
            "rule_id": f"{RULE_SET}.{key}",
            "key": key,
            "name": name,
            "description": name,
            "severity": severity,
            "check": staticmethod(check),
        },
    )
    for key, severity, name, check in CHECKS
)


def register_bundle_rules() -> None:
    """Register the ``bundle.*`` rules with the platform rule registry."""
    for rule_class in RULES:
        rule_registry.register(rule_class(), [RULE_SET])


__all__ = ["CHECKS", "RULES", "RULE_SET", "register_bundle_rules"]
