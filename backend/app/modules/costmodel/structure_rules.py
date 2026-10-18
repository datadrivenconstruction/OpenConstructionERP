# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost structure validation rules V1 to V5, rule set ``cost_structure``.

The structure view runs this set on every read (see
:meth:`~app.modules.costmodel.structure_service.CostStructureService.findings`).
Each rule reads one plain-data payload under ``context.data["cost_structure"]``
and is silent on any other data, so the set can sit next to the BOQ rules in a
general validation run without misfiring.

* V1 ``account_codes``: a code once per structure, one code list per structure,
  no parent loops, no deeper than the list allows.
* V2 ``posted_to_postable``: every cost line reaches an open, postable account;
  what does not is the "no account" or "invalid account" suspense.
* V3 ``rollup``: the structure's total is the money on its lines plus the own
  amounts of its accounts, nothing lost and nothing twice; an own amount on a
  node that has children is pointed out.
* V4 ``allocation_complete``: the shares of a split position add up to 100 %
  or to the position's quantity, within 0.01 %.
* V5 ``vector_inherited``: a contract line made from a bill position stays on
  that position's cost lines unless someone overrode it with a reason.

Messages come from the validation message bundle in the caller's locale.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.code_lists import same_code
from app.core.currency_registry import sentence_amount
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.core.validation.messages import DEFAULT_LOCALE, translate
from app.modules.costmodel.structure import MODE_QUANTITY, check_shares

logger = logging.getLogger(__name__)

RULE_SET = "cost_structure"
PAYLOAD_KEY = "cost_structure"

#: The tolerance V3 allows between the reported total and the money it is made of.
ROLLUP_TOLERANCE = Decimal("0.01")


def _payload(context: ValidationContext) -> dict[str, Any] | None:
    data = context.data
    if isinstance(data, dict) and isinstance(data.get(PAYLOAD_KEY), dict):
        return data[PAYLOAD_KEY]
    return None


def _locale(context: ValidationContext) -> str:
    metadata = getattr(context, "metadata", None)
    if isinstance(metadata, dict):
        locale = metadata.get("locale")
        if isinstance(locale, str) and locale.strip():
            return locale.strip()
    return DEFAULT_LOCALE


def _dec(raw: object) -> Decimal:
    try:
        value = Decimal(str(raw if raw not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return value if value.is_finite() else Decimal("0")


class _StructureRule(ValidationRule):
    """Shared plumbing: payload lookup and translated results."""

    standard = "universal"
    category = RuleCategory.CONSISTENCY

    def _result(
        self,
        context: ValidationContext,
        message_key: str,
        *,
        severity: Severity | None = None,
        element_ref: str | None = None,
        money: tuple[str, ...] = (),
        **params: Any,
    ) -> RuleResult:
        """A failed result. Params named in ``money`` are spelled as amounts in the payload currency.

        ``details`` keeps every param as a plain string (a raw decimal for money),
        so a client can format or sort it; only the sentence gets the rendering.
        """
        locale = _locale(context)
        currency = str((_payload(context) or {}).get("currency") or "")
        shown = {k: (sentence_amount(_dec(v), currency) if k in money else v) for k, v in params.items()}
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=False,
            message=translate(f"cost_structure.{message_key}.fail", locale, **shown),
            element_ref=element_ref,
            details={"problem": message_key, **{k: str(v) for k, v in params.items()}},
            suggestion=translate(f"cost_structure.{message_key}.suggestion", locale, **shown),
        )

    def _passed(self) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=True,
            message="",
        )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        if payload is None:
            return []
        found = self.check(context, payload)
        return found or [self._passed()]


class AccountCodesRule(_StructureRule):
    """V1: codes are unique, one list per structure, no loops, depth within the list."""

    rule_id = "cost_structure.account_codes"
    name = "Account codes form one clean tree"
    severity = Severity.ERROR
    description = "Each code once, one code list per structure, no parent loops, no deeper than the list."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        accounts = [a for a in payload.get("accounts") or [] if isinstance(a, dict)]
        out: list[RuleResult] = []

        seen: list[dict[str, Any]] = []
        for a in accounts:
            twin = next((s for s in seen if same_code(s.get("code"), a.get("code"))), None)
            if twin is not None:
                out.append(
                    self._result(
                        context, "account_code_duplicate", element_ref=str(a.get("id")), code=a.get("code") or ""
                    )
                )
            else:
                seen.append(a)

        standards = sorted({str(a.get("standard") or "") for a in accounts if a.get("standard")})
        if len(standards) > 1:
            out.append(self._result(context, "mixed_standard", standards=", ".join(standards)))

        by_id = {str(a.get("id")): a for a in accounts}
        reported: set[str] = set()
        for a in accounts:
            start = str(a.get("id"))
            if start in reported:
                continue
            path: list[str] = []
            node: str | None = start
            while node is not None and node in by_id and node not in path:
                path.append(node)
                parent = by_id[node].get("parent_id")
                node = str(parent) if parent else None
            if node is not None and node in path:
                loop = path[path.index(node) :]
                reported.update(loop)
                out.append(
                    self._result(
                        context,
                        "account_parent_cycle",
                        element_ref=node,
                        code=by_id[node].get("code") or "",
                        count=len(loop),
                    )
                )

        limits = payload.get("depth_limits") or {}
        for a in accounts:
            limit = limits.get(str(a.get("standard") or ""))
            level = int(a.get("level") or 1)
            if limit and level > int(limit):
                out.append(
                    self._result(
                        context,
                        "account_too_deep",
                        severity=Severity.WARNING,
                        element_ref=str(a.get("id")),
                        code=a.get("code") or "",
                        level=level,
                        max=int(limit),
                    )
                )
        return out


class PostedToPostableRule(_StructureRule):
    """V2: every cost line reaches an open account that takes postings."""

    rule_id = "cost_structure.posted_to_postable"
    name = "Every cost line on a postable account"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Money on no account, or on a closed or non-postable one, sits in suspense."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        accounts = {str(a.get("id")): a for a in payload.get("accounts") or [] if isinstance(a, dict)}
        no_account: list[dict[str, Any]] = []
        invalid: list[dict[str, Any]] = []
        for line in payload.get("lines") or []:
            if not isinstance(line, dict):
                continue
            account = accounts.get(str(line.get("account_id"))) if line.get("account_id") else None
            if account is None:
                no_account.append(line)
            elif not account.get("is_leaf_postable", True) or account.get("status") == "closed":
                invalid.append(line)
        out: list[RuleResult] = []
        if no_account:
            out.append(
                self._result(
                    context,
                    "no_account",
                    money=("amount",),
                    count=len(no_account),
                    amount=str(sum((_dec(ln.get("amount")) for ln in no_account), Decimal("0"))),
                    code=no_account[0].get("code") or "",
                )
            )
        if invalid:
            out.append(
                self._result(
                    context,
                    "invalid_account",
                    money=("amount",),
                    count=len(invalid),
                    amount=str(sum((_dec(ln.get("amount")) for ln in invalid), Decimal("0"))),
                    code=invalid[0].get("code") or "",
                )
            )
        return out


class RollupRule(_StructureRule):
    """V3: the total is exactly its parts; own amounts on parent nodes are pointed out."""

    rule_id = "cost_structure.rollup"
    name = "Structure total adds up"
    severity = Severity.ERROR
    description = "The structure total equals the money on its lines plus the accounts' own amounts."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        accounts = [a for a in payload.get("accounts") or [] if isinstance(a, dict)]
        lines = [ln for ln in payload.get("lines") or [] if isinstance(ln, dict)]
        out: list[RuleResult] = []

        parents = {str(a.get("parent_id")) for a in accounts if a.get("parent_id")}
        for a in accounts:
            own = _dec(a.get("own_amount"))
            if own != 0 and str(a.get("id")) in parents:
                out.append(
                    self._result(
                        context,
                        "own_amount_on_parent",
                        severity=Severity.WARNING,
                        element_ref=str(a.get("id")),
                        money=("amount",),
                        code=a.get("code") or "",
                        amount=str(own),
                    )
                )

        if "reported_total" in payload:
            expected = sum((_dec(ln.get("amount")) for ln in lines), Decimal("0"))
            expected += sum((_dec(a.get("own_amount")) for a in accounts), Decimal("0"))
            reported = _dec(payload.get("reported_total"))
            if abs(reported - expected) > ROLLUP_TOLERANCE:
                out.append(
                    self._result(
                        context,
                        "rollup_mismatch",
                        money=("reported", "expected", "difference"),
                        reported=str(reported),
                        expected=str(expected),
                        difference=str(reported - expected),
                    )
                )
        return out


class AllocationCompleteRule(_StructureRule):
    """V4: a split position's shares add up to the whole position."""

    rule_id = "cost_structure.allocation_complete"
    name = "Split positions fully allocated"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Shares add up to 100 % or to the position's quantity, within 0.01 %."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        out: list[RuleResult] = []
        for row in payload.get("allocations") or []:
            if not isinstance(row, dict):
                continue
            modes = [m for m in row.get("modes") or [] if m]
            ordinal = row.get("ordinal") or ""
            ref = str(row.get("position_id") or "")
            if len(set(modes)) > 1:
                out.append(self._result(context, "allocation_mixed_modes", element_ref=ref, ordinal=ordinal))
                continue
            mode = modes[0] if modes else "percent"
            check = check_shares(mode, row.get("shares") or [], row.get("quantity"))
            if not check.within_tolerance:
                out.append(
                    self._result(
                        context,
                        "allocation_incomplete",
                        element_ref=ref,
                        ordinal=ordinal,
                        total=str(check.total),
                        expected=str(check.expected),
                        unit="" if mode == MODE_QUANTITY else "%",
                    )
                )
        return out


class VectorInheritedRule(_StructureRule):
    """V5: a contract line made from a bill position keeps that position's vector."""

    rule_id = "cost_structure.vector_inherited"
    name = "Contract lines inherit the position's cost lines"
    severity = Severity.WARNING
    description = (
        "A line taken from a bill position sits on one of that position's cost lines, or carries a reasoned override."
    )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        out: list[RuleResult] = []
        for row in payload.get("inherited") or []:
            if not isinstance(row, dict) or row.get("override_audited"):
                continue
            vector = {str(v) for v in row.get("vector") or []}
            # A split line sits on every line of its split, so each share must be on the vector.
            held = {str(v) for v in row.get("cost_line_ids") or []}
            if row.get("cost_line_id"):
                held.add(str(row["cost_line_id"]))
            if not vector or not held or held <= vector:
                continue
            out.append(
                self._result(
                    context,
                    "vector_not_inherited",
                    element_ref=str(row.get("id") or ""),
                    code=row.get("code") or "",
                )
            )
        return out


COST_STRUCTURE_RULES: tuple[type[_StructureRule], ...] = (
    AccountCodesRule,
    PostedToPostableRule,
    RollupRule,
    AllocationCompleteRule,
    VectorInheritedRule,
)


def register_cost_structure_rules() -> None:
    """Register V1 to V5 into the ``cost_structure`` rule set."""
    for rule_cls in COST_STRUCTURE_RULES:
        rule_registry.register(rule_cls(), [RULE_SET])
    logger.debug("Registered cost structure validation rules")
