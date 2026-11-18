# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory checks: neutral checks, rule ids and wording from the pack.

Each check below asks one question any market with the matching law asks, and
knows no number. A jurisdiction table binds a check to a rule id, a severity and
the sentence a user reads, so ``retention.over_cap`` is ``us.retainage.over_cap``
in a US state pack and could be something else in another market.

Checks:

* ``retention.over_cap`` - retention held above the statutory cap.
* ``retention.below_floor`` - the owner holds less than the statutory reserve.
* ``notice.due`` - a lien or payment notice falls due (an error once it is past).
* ``tax.rate_is_base_rate`` - the bid uses the base rate, not the address rate.
* ``tax.item_unclassified`` - an installed item has no class the tax law needs.
* ``tax.contract_form_missing`` - the contract form that decides the treatment is not chosen.
* ``tax.taxable_line_priced_free`` - a line the law taxes was priced tax-free.
* ``tax.exemption_certificate_missing`` - an exemption is claimed without its certificate.
* ``tax.surtax_over_item_cap`` - a per-item surtax was priced above its cap.
* ``wage.determination_missing`` - public work lacks the wage schedule the law requires.
* ``contract.preempted_clause`` - a clause the law preempts from a date.

The validation engine sees one :class:`StatutoryRule` per rule id. It reads the
jurisdiction from the context, finds that jurisdiction's binding of the id, and
passes when the jurisdiction does not bind it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

logger = logging.getLogger(__name__)

STATUTORY_RULE_SET = "statutory"

CHECKS: frozenset[str] = frozenset(
    {
        "retention.over_cap",
        "retention.below_floor",
        "notice.due",
        "tax.rate_is_base_rate",
        "tax.item_unclassified",
        "tax.contract_form_missing",
        "tax.taxable_line_priced_free",
        "tax.exemption_certificate_missing",
        "tax.surtax_over_item_cap",
        "wage.determination_missing",
        "contract.preempted_clause",
    }
)

_SEVERITIES = {"error": Severity.ERROR, "warning": Severity.WARNING, "info": Severity.INFO}


@dataclass
class Finding:
    """One statutory finding, ready for the UI and the validation engine."""

    rule_id: str
    check: str
    severity: str
    message: str
    params: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    element_ref: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "rule_id": self.rule_id,
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "params": self.params,
            "source": self.source,
            "element_ref": self.element_ref,
        }


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _render(template: str, params: dict[str, Any]) -> str:
    return template.format_map(_SafeDict({k: "" if v is None else v for k, v in params.items()}))


def _pct(value: Any) -> str:
    if value is None:
        return ""
    return format(Decimal(str(value)).normalize(), "f")


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def bindings(table: dict[str, Any]) -> list[dict[str, Any]]:
    """The jurisdiction's check bindings, malformed ones dropped with a warning."""
    out = []
    for raw in table.get("validation_rules") or []:
        if raw.get("check") not in CHECKS or not raw.get("id") or raw.get("severity") not in _SEVERITIES:
            logger.warning("statutory: %s carries an unusable rule %r", table.get("code"), raw)
            continue
        out.append(raw)
    return out


def run_checks(table: dict[str, Any], facts: dict[str, Any], computed: dict[str, Any]) -> list[Finding]:
    """Every finding ``facts`` raise under ``table``.

    Args:
        table: The jurisdiction table.
        facts: The request facts, as plain JSON-like data.
        computed: Engine outputs: ``retention`` (RetentionCheck dict), ``notices``
            (list of NoticeDue dicts) and ``tax`` (TaxResult dict), each optional.
    """
    findings: list[Finding] = []
    for binding in bindings(table):
        findings.extend(_run_one(binding, table, facts, computed))
    return findings


def _finding(binding: dict[str, Any], params: dict[str, Any], *, severity: str | None = None, **kw: Any) -> Finding:
    template = str(binding.get("message") or binding["id"])
    if not params.get("period") and binding.get("message_without_period"):
        template = str(binding["message_without_period"])
    return Finding(
        rule_id=str(binding["id"]),
        check=str(binding["check"]),
        severity=severity or str(binding["severity"]),
        message=_render(template, params),
        params=params,
        source=str(params.get("source") or ""),
        **kw,
    )


def _run_one(
    binding: dict[str, Any], table: dict[str, Any], facts: dict[str, Any], computed: dict[str, Any]
) -> list[Finding]:
    check = binding["check"]
    state = str(table.get("name") or table.get("code"))
    retention = computed.get("retention") or {}
    tax_facts = facts.get("tax") or None
    tax_out = computed.get("tax") or {}
    profile = table.get("tax") or {}
    options = binding.get("params") or {}

    if check == "retention.over_cap" and retention.get("over_cap"):
        return [
            _finding(
                binding,
                {
                    "pct": _pct(retention.get("retention_pct")),
                    "cap": _pct(retention.get("cap_pct")),
                    "cap_amount": retention.get("cap_amount"),
                    "state": state,
                    "source": retention.get("cap_source"),
                },
            )
        ]
    if check == "retention.below_floor" and retention.get("below_floor"):
        return [
            _finding(
                binding,
                {
                    "pct": _pct(retention.get("retention_pct")),
                    "floor": _pct(retention.get("floor_pct")),
                    "state": state,
                    "source": retention.get("floor_source"),
                },
            )
        ]
    if check == "notice.due":
        kinds = set(options.get("kinds") or [])
        out = []
        for notice in computed.get("notices") or []:
            if kinds and notice.get("kind") not in kinds:
                continue
            overdue = notice.get("status") == "overdue"
            out.append(
                _finding(
                    binding,
                    {
                        "notice": notice.get("name"),
                        "date": notice.get("due_date"),
                        "month": notice.get("period"),
                        "period": notice.get("period"),
                        "source": notice.get("source"),
                        "code": notice.get("code"),
                    },
                    severity="error" if overdue else str(binding["severity"]),
                    element_ref=str(notice.get("code") or ""),
                )
            )
        return out
    if tax_facts is None:
        return _non_tax(binding, check, facts, options)

    form_code = tax_facts.get("contract_form")
    forms = profile.get("contract_forms") or {}
    form = forms.get(form_code or "") or {}
    lines = tax_facts.get("lines") or []
    if check == "tax.contract_form_missing":
        if not form:
            return [_finding(binding, {"forms": ", ".join(sorted(forms))})]
        return []
    if check == "tax.rate_is_base_rate":
        base = _dec(profile.get("base_rate_pct"))
        rate = _dec(tax_facts.get("rate_pct"))
        if base is not None and rate is not None and rate == base and not _dec(tax_facts.get("surtax_pct")):
            return [_finding(binding, {"rate": _pct(rate), "lookup": profile.get("rate_lookup_url") or ""})]
        return []
    if check == "tax.item_unclassified":
        classes = set(profile.get("item_classes") or [])
        return [
            _finding(
                binding, {"line": line.get("description") or line.get("id")}, element_ref=str(line.get("id") or "")
            )
            for line in lines
            if classes and line.get("kind") not in classes and line.get("kind") not in set(options.get("ignore") or [])
        ]
    if check == "tax.taxable_line_priced_free":
        kinds = set(options.get("kinds") or [])
        forms_only = set(options.get("contract_forms") or [])
        if forms_only and form_code not in forms_only:
            return []
        taxed = {
            str(r.get("id")): r for r in tax_out.get("lines") or [] if _dec(r.get("tax")) and _dec(r.get("tax")) > 0
        }
        return [
            _finding(
                binding, {"line": line.get("description") or line.get("id")}, element_ref=str(line.get("id") or "")
            )
            for line in lines
            if (not kinds or line.get("kind") in kinds)
            and str(line.get("id")) in taxed
            and _dec(line.get("priced_tax")) == Decimal("0")
        ]
    if check == "tax.exemption_certificate_missing":
        certificate = form.get("exemption_certificate")
        if certificate and not tax_facts.get("exemption_certificate_on_file"):
            return [_finding(binding, {"certificate": certificate})]
        return []
    if check == "tax.surtax_over_item_cap":
        computed_lines = {str(r.get("id")): r for r in tax_out.get("lines") or []}
        cap = (profile.get("surtax") or {}).get("item_cap")
        out = []
        for line in lines:
            priced = _dec(line.get("priced_surtax"))
            row = computed_lines.get(str(line.get("id")))
            if priced is None or row is None:
                continue
            if priced > (_dec(row.get("surtax")) or Decimal("0")) + Decimal("0.01"):
                out.append(
                    _finding(
                        binding,
                        {"line": line.get("description") or line.get("id"), "cap": cap},
                        element_ref=str(line.get("id") or ""),
                    )
                )
        return out
    return _non_tax(binding, check, facts, options)


def _non_tax(binding: dict[str, Any], check: str, facts: dict[str, Any], options: dict[str, Any]) -> list[Finding]:
    if check == "wage.determination_missing":
        wage = facts.get("wage") or {}
        if not wage.get("public_work"):
            return []
        have = {str(a) for a in wage.get("determination_authorities") or []}
        accepted = set(options.get("accepted_authorities") or [])
        if have & accepted:
            return []
        only_when = set(options.get("only_when_present") or [])
        if only_when and not (have & only_when):
            return []
        return [_finding(binding, {"accepted": ", ".join(sorted(accepted))})]
    if check == "contract.preempted_clause":
        clause = options.get("clause")
        start = _date(options.get("agreement_date_from"))
        agreed = _date(facts.get("agreement_date"))
        if clause in (facts.get("contract_clauses") or []) and start and agreed and agreed >= start:
            return [_finding(binding, {"clause": clause, "date": start.isoformat()})]
    return []


class StatutoryRule(ValidationRule):
    """One rule id, answered by whichever jurisdiction the context names."""

    standard = STATUTORY_RULE_SET
    category = RuleCategory.COMPLIANCE

    def __init__(self, rule_id: str, severity: str, name: str) -> None:
        self.rule_id = rule_id
        self.name = name
        self.severity = _SEVERITIES[severity]
        self.description = name

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Evaluate the context's facts and report this rule's findings."""
        from app.modules.statutory.service import evaluate_facts

        data = context.data if isinstance(context.data, dict) else {}
        outcome = evaluate_facts(data)
        mine = [f for f in outcome.get("findings", []) if f["rule_id"] == self.rule_id]
        if not mine:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message="OK",
                )
            ]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=_SEVERITIES.get(f["severity"], self.severity),
                category=self.category,
                passed=False,
                message=f["message"],
                element_ref=f.get("element_ref"),
                details={"params": f["params"], "source": f["source"]},
            )
            for f in mine
        ]


def register_statutory_rules() -> int:
    """Register one rule per id that any loaded jurisdiction binds. Idempotent."""
    from app.core.jurisdiction_rules import all_jurisdictions

    seen: dict[str, StatutoryRule] = {}
    for table in all_jurisdictions().values():
        for binding in bindings(table):
            rule_id = str(binding["id"])
            if rule_id not in seen:
                seen[rule_id] = StatutoryRule(rule_id, str(binding["severity"]), str(binding.get("name") or rule_id))
    for rule in seen.values():
        rule_registry.register(rule, [STATUTORY_RULE_SET])
    return len(seen)


__all__ = [
    "CHECKS",
    "STATUTORY_RULE_SET",
    "Finding",
    "StatutoryRule",
    "bindings",
    "register_statutory_rules",
    "run_checks",
]
