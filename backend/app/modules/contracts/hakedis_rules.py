# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for a payment certificate (hakediş): the ``hakedis`` rule set.

The set is what a certificate has to satisfy before the document behind it may
be certified. Every ERROR blocks certification; a WARNING is a prompt to look
again and blocks nothing.

The rules read the plain dict
:func:`app.modules.contracts.hakedis_document.rule_context` builds, the same
one for a progress claim and for a subcontractor's payment application, so the
report on the screen is the check the certify button runs.

The engine records a rule that raises as an execution failure and does not
count it as a finding. The gate treats such a failure as blocking, and the
rules below read every figure through helpers that cannot raise, so that a
malformed context shows up as a finding rather than as silence.
"""

from __future__ import annotations

import logging
from datetime import date
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
from app.modules.contracts.hakedis_document import HAKEDIS_RULE_SET
from app.modules.contracts.messages import translate

logger = logging.getLogger(__name__)

#: Half of the smallest unit of any currency this prints: two amounts that
#: differ by less are the same amount.
_EPSILON = Decimal("0.005")

#: Tolerance on the sum of the lump-sum weights, in percent points.
_WEIGHT_EPSILON = Decimal("0.01")

DEC_ZERO = Decimal("0")
DEC_HUNDRED = Decimal("100")

#: Hold reasons another rule of the set already reports under its own name.
_REPORTED_ELSEWHERE: frozenset[str] = frozenset(
    {"previous_unknown", "previous_not_certified", "taxes_stale", "taxes_outdated", "operand_held", "base_held"}
)

#: Hold reasons that mean the stored taxes no longer belong to the document.
_STALE_REASONS: frozenset[str] = frozenset({"taxes_stale", "taxes_outdated"})


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _section(context: ValidationContext, key: str) -> dict[str, Any]:
    value = _data(context).get(key)
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _amount(value: Any) -> Decimal | None:
    """A context amount, or ``None`` when it is absent or not a number."""
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return amount if amount.is_finite() else None


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _language(context: ValidationContext) -> str:
    """The language a line's own label is read in: Turkish, or English."""
    return "tr" if _locale(context).lower().startswith("tr") else "en"


def _iso_day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _summary(context: ValidationContext) -> dict[str, dict[str, Any]]:
    return {str(line.get("key")): line for line in _rows(_data(context).get("summary"))}


def _line_value(line: dict[str, Any] | None) -> Decimal | None:
    if not line or line.get("status") != "value":
        return None
    return _amount(line.get("amount"))


def _line_name(line: dict[str, Any], context: ValidationContext) -> str:
    labels = line.get("labels") if isinstance(line.get("labels"), dict) else {}
    name = str(labels.get(_language(context)) or line.get("key") or "")
    letter = str(line.get("letter") or "")
    return f"{letter}. {name}" if letter else name


def _percent(value: Decimal) -> str:
    return format(value.normalize(), "f")


class _HakedisRule(ValidationRule):
    """Shared result builders for the ``hakedis`` rules."""

    standard = HAKEDIS_RULE_SET
    category = RuleCategory.CONSISTENCY

    def _ref(self, context: ValidationContext) -> str:
        return str(_section(context, "document").get("id") or "")

    def _money(self, context: ValidationContext, amount: Decimal) -> str:
        return sentence_amount(amount, str(_data(context).get("currency") or ""))

    def _ok(self, context: ValidationContext) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=True,
            message=translate("common.ok", locale=_locale(context)),
            element_ref=self._ref(context),
        )

    def _fail(
        self,
        context: ValidationContext,
        fail_key: str,
        suggestion_key: str,
        *,
        element_ref: str = "",
        severity: Severity | None = None,
        **params: Any,
    ) -> RuleResult:
        locale = _locale(context)
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=False,
            message=translate(fail_key, locale=locale, **params),
            element_ref=element_ref or self._ref(context),
            suggestion=translate(suggestion_key, locale=locale),
            details={name: str(value) for name, value in params.items()},
        )


class CumulativeWithinContractRule(_HakedisRule):
    """Work certified to date must not run past the contract sum.

    The contract sum already carries the approved change orders, so work that
    an approved adjustment covers passes; work beyond it needs the adjustment
    approved first, not a certificate that quietly exceeds the contract.
    """

    rule_id = "hakedis.cumulative_exceeds_contract"
    name = "Work to date stays within the contract sum"
    severity = Severity.ERROR
    description = "The cumulative value of work done must not exceed the contract sum with its approved changes"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        contract = _amount(_section(context, "contract").get("value"))
        cumulative = _amount(_section(context, "work").get("cumulative_total"))
        if contract is None or cumulative is None or contract <= DEC_ZERO:
            return [self._ok(context)]
        if cumulative - contract <= _EPSILON:
            return [self._ok(context)]
        return [
            self._fail(
                context,
                "hakedis.cumulative_exceeds_contract.fail",
                "hakedis.cumulative_exceeds_contract.suggestion",
                cumulative=self._money(context, cumulative),
                contract=self._money(context, contract),
                over=self._money(context, cumulative - contract),
            )
        ]


class PreviousMatchesLastCertifiedRule(_HakedisRule):
    """What this certificate calls previous is what the last one certified.

    Two comparisons against the previous document's frozen copy: its total
    against this certificate's previous-certificates line, and its work to
    date against the previous column of this works list. The second is the
    one that finds a claim billed between the two that neither certificate
    shows.
    """

    rule_id = "hakedis.previous_matches_last_certified"
    name = "Previous figures match the last certified certificate"
    severity = Severity.ERROR
    description = "The previous total and the previous work column must equal the last certified certificate's figures"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        previous = _section(context, "previous")
        frozen_total = _amount(previous.get("frozen_total"))
        frozen_work = _amount(previous.get("frozen_work_cumulative"))
        results: list[RuleResult] = []
        carried = _line_value(_summary(context).get(str(previous.get("line_key") or "")))
        if frozen_total is not None and carried is not None and abs(carried - frozen_total) > _EPSILON:
            results.append(
                self._fail(
                    context,
                    "hakedis.previous_matches_last_certified.fail",
                    "hakedis.previous_matches_last_certified.suggestion",
                    reference=str(previous.get("reference") or ""),
                    carried=self._money(context, carried),
                    certified=self._money(context, frozen_total),
                )
            )
        work_previous = _amount(_section(context, "work").get("previous_total"))
        if frozen_work is not None and work_previous is not None and abs(work_previous - frozen_work) > _EPSILON:
            results.append(
                self._fail(
                    context,
                    "hakedis.previous_matches_last_certified.work_fail",
                    "hakedis.previous_matches_last_certified.suggestion",
                    reference=str(previous.get("reference") or ""),
                    carried=self._money(context, work_previous),
                    certified=self._money(context, frozen_work),
                )
            )
        return results or [self._ok(context)]


class PreviousKnownRule(_HakedisRule):
    """The previous certificate's total has to be known.

    Held when the previous document is not certified yet, or was certified
    before certificates were frozen and nobody has stated its total since.
    """

    rule_id = "hakedis.previous_unknown"
    name = "The previous certificate's total is known"
    severity = Severity.ERROR
    description = "A certificate cannot be certified while the total of the one before it is not final"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        previous = _section(context, "previous")
        line = _summary(context).get(str(previous.get("line_key") or ""))
        if not line or line.get("status") != "held":
            return [self._ok(context)]
        if line.get("reason") == "previous_not_certified":
            return [
                self._fail(
                    context,
                    "hakedis.previous_unknown.not_certified",
                    "hakedis.previous_unknown.suggestion",
                    reference=str(previous.get("reference") or ""),
                )
            ]
        return [self._fail(context, "hakedis.previous_unknown.fail", "hakedis.previous_unknown.suggestion")]


class WeightsSumRule(_HakedisRule):
    """On a lump-sum certificate the weights of the items add up to one hundred."""

    rule_id = "hakedis.weights_sum"
    name = "Lump-sum weights add up to 100"
    severity = Severity.ERROR
    description = "The weight percentages (pursantaj) of a lump-sum works list must total 100"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _section(context, "document").get("flavour") != "lump_sum":
            return [self._ok(context)]
        weights = [
            _amount(line.get("weight_pct"))
            for line in _rows(_section(context, "work").get("lines"))
            if line.get("weight_pct") not in (None, "")
        ]
        known = [weight for weight in weights if weight is not None]
        if not known:
            return [self._ok(context)]
        total = sum(known, DEC_ZERO)
        if abs(total - DEC_HUNDRED) <= _WEIGHT_EPSILON:
            return [self._ok(context)]
        return [
            self._fail(context, "hakedis.weights_sum.fail", "hakedis.weights_sum.suggestion", total=_percent(total))
        ]


class PercentRegressedRule(_HakedisRule):
    """An item's progress to date fell below what was already certified.

    A negative period figure is how an earlier over-measurement is corrected,
    so it is allowed; it is also what a typing error looks like, so it is
    pointed out.
    """

    rule_id = "hakedis.percent_regressed"
    name = "Progress does not go backwards"
    severity = Severity.WARNING
    description = "An item whose quantity, percent or amount this period is negative reduces work already certified"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for line in _rows(_section(context, "work").get("lines")):
            figures = [_amount(line.get(name)) for name in ("period_quantity", "period_pct", "period_amount")]
            if not any(figure is not None and figure < DEC_ZERO for figure in figures):
                continue
            results.append(
                self._fail(
                    context,
                    "hakedis.percent_regressed.fail",
                    "hakedis.percent_regressed.suggestion",
                    element_ref=str(line.get("index") or ""),
                    line=str(line.get("code") or line.get("description") or line.get("index") or ""),
                )
            )
        return results or [self._ok(context)]


class IncomeWithholdingSingleYearRule(_HakedisRule):
    """Income withholding is selected on a contract that fits in one calendar year.

    The withholding on construction work applies to work that spans more than
    one calendar year. Whether a particular contract does is a question of
    fact with edge cases the dates alone do not settle, so this only asks the
    person to check.
    """

    rule_id = "hakedis.income_withholding_single_year"
    name = "Income withholding is checked on a single-year contract"
    severity = Severity.WARNING
    description = "Income withholding on construction work concerns work spanning more than one calendar year"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _section(context, "taxes").get("income_withholding") != "selected":
            return [self._ok(context)]
        contract = _section(context, "contract")
        start, end = _iso_day(contract.get("start")), _iso_day(contract.get("end"))
        if start is None or end is None or start.year != end.year:
            return [self._ok(context)]
        return [
            self._fail(
                context,
                "hakedis.income_withholding_single_year.fail",
                "hakedis.income_withholding_single_year.suggestion",
                start=start.isoformat(),
                end=end.isoformat(),
            )
        ]


class AdvanceRecoveryWithinAdvanceRule(_HakedisRule):
    """The advance recovered to date must not exceed the advance paid.

    Where the contract states no advance there is nothing to compare with; a
    recovery is then pointed out instead of blocked.
    """

    rule_id = "hakedis.advance_recovery_exceeds_advance"
    name = "Advance recovered stays within the advance paid"
    severity = Severity.ERROR
    description = "The advance recovered on this and the earlier certificates must not exceed the advance paid"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        this = _line_value(_summary(context).get("advance_recovery")) or DEC_ZERO
        before = _amount(_section(context, "previous").get("advance_recovered")) or DEC_ZERO
        recovered = before + this
        if recovered <= _EPSILON:
            return [self._ok(context)]
        advance = _amount(_section(context, "contract").get("advance_amount"))
        if advance is None:
            return [
                self._fail(
                    context,
                    "hakedis.advance_recovery_exceeds_advance.unknown",
                    "hakedis.advance_recovery_exceeds_advance.suggestion",
                    severity=Severity.WARNING,
                    recovered=self._money(context, recovered),
                )
            ]
        if recovered - advance <= _EPSILON:
            return [self._ok(context)]
        return [
            self._fail(
                context,
                "hakedis.advance_recovery_exceeds_advance.fail",
                "hakedis.advance_recovery_exceeds_advance.suggestion",
                recovered=self._money(context, recovered),
                advance=self._money(context, advance),
            )
        ]


class RetentionMatchesConfigRule(_HakedisRule):
    """The retention on the certificate is the retention the document holds.

    The certificate takes the configured percent of its base. The document
    behind it holds its own retention, worked out by the retention policy, and
    that is the figure the payment follows. When the two differ the
    certificate would promise a net the payment does not make.
    """

    rule_id = "hakedis.retention_matches_config"
    name = "Retention matches what the document holds"
    severity = Severity.WARNING
    description = "The retention line of the certificate should equal the retention held on the source document"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        line = _summary(context).get("retention")
        certificate = _line_value(line)
        stored = _amount(_section(context, "document").get("stored_retention"))
        if certificate is None or stored is None or abs(certificate - stored) <= _EPSILON:
            return [self._ok(context)]
        return [
            self._fail(
                context,
                "hakedis.retention_matches_config.fail",
                "hakedis.retention_matches_config.suggestion",
                certificate=self._money(context, certificate),
                stored=self._money(context, stored),
                percent=_percent(_amount((line or {}).get("rate_pct")) or DEC_ZERO),
            )
        ]


class NetPayableNotNegativeRule(_HakedisRule):
    """The amount payable must not be negative."""

    rule_id = "hakedis.net_payable_negative"
    name = "The amount payable is not negative"
    severity = Severity.ERROR
    description = "Deductions must not exceed the accrued amount of the certificate"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payable = _line_value(_summary(context).get("payable"))
        if payable is None or payable >= DEC_ZERO:
            return [self._ok(context)]
        return [
            self._fail(
                context,
                "hakedis.net_payable_negative.fail",
                "hakedis.net_payable_negative.suggestion",
                payable=self._money(context, payable),
            )
        ]


class TaxesNotStaleRule(_HakedisRule):
    """The stored taxes were computed on this certificate's amounts."""

    rule_id = "hakedis.taxes_stale"
    name = "Taxes are computed on the certificate's current amounts"
    severity = Severity.ERROR
    description = "Taxes computed on an amount, a date or a rate that has since changed must be recalculated"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        stale = bool(_section(context, "taxes").get("stale")) or any(
            line.get("status") == "held" and line.get("reason") in _STALE_REASONS for line in _summary(context).values()
        )
        if not stale:
            return [self._ok(context)]
        return [self._fail(context, "hakedis.taxes_stale.fail", "hakedis.taxes_stale.suggestion")]


class TaxesConfirmedRule(_HakedisRule):
    """A person has confirmed the tax figures."""

    rule_id = "hakedis.taxes_confirmed"
    name = "The tax figures are confirmed"
    severity = Severity.ERROR
    description = "A certificate with tax lines cannot be certified while its taxes are a draft"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        taxes = _section(context, "taxes")
        if not _data(context).get("tax_lines") or not taxes.get("stored") or taxes.get("stale"):
            # Nothing stored, or stale: the lines are held and reported as such.
            return [self._ok(context)]
        if taxes.get("status") == "confirmed":
            return [self._ok(context)]
        return [self._fail(context, "hakedis.taxes_confirmed.fail", "hakedis.taxes_confirmed.suggestion")]


class LinesCompleteRule(_HakedisRule):
    """Every line of the certificate has a figure, or is marked not applicable."""

    rule_id = "hakedis.lines_complete"
    name = "No line of the certificate is held"
    severity = Severity.ERROR
    description = "A line with no figure holds every total built on it, so the certificate cannot be certified"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        language = _language(context)
        results: list[RuleResult] = []
        for line in _summary(context).values():
            if line.get("status") != "held" or line.get("reason") in _REPORTED_ELSEWHERE:
                continue
            texts = line.get("reason_texts") if isinstance(line.get("reason_texts"), dict) else {}
            results.append(
                self._fail(
                    context,
                    "hakedis.lines_complete.fail",
                    "hakedis.lines_complete.suggestion",
                    element_ref=str(line.get("key") or ""),
                    line=_line_name(line, context),
                    reason=str(texts.get(language) or line.get("reason") or ""),
                )
            )
        return results or [self._ok(context)]


class WorkValueMatchesMeasureRule(_HakedisRule):
    """An item's recorded amount is what its quantity or percent gives.

    The certificate prints the amounts the source document carries. Where the
    quantity times the unit price, or the percent of the item's value, comes
    to something else, the two columns of the same row disagree on paper.
    """

    rule_id = "hakedis.work_value_differs"
    name = "Recorded amounts match the measured quantities"
    severity = Severity.WARNING
    description = "The amount recorded for an item should equal its quantity times unit price, or its percent of value"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for line in _rows(_section(context, "work").get("lines")):
            computed = _amount(line.get("computed_cumulative_amount"))
            stated = _amount(line.get("cumulative_amount"))
            if computed is None or stated is None or abs(computed - stated) <= _EPSILON:
                continue
            results.append(
                self._fail(
                    context,
                    "hakedis.work_value_differs.fail",
                    "hakedis.work_value_differs.suggestion",
                    element_ref=str(line.get("index") or ""),
                    line=str(line.get("code") or line.get("description") or line.get("index") or ""),
                    stated=self._money(context, stated),
                    computed=self._money(context, computed),
                )
            )
        return results or [self._ok(context)]


HAKEDIS_RULES: tuple[type[ValidationRule], ...] = (
    LinesCompleteRule,
    PreviousKnownRule,
    PreviousMatchesLastCertifiedRule,
    CumulativeWithinContractRule,
    WeightsSumRule,
    PercentRegressedRule,
    WorkValueMatchesMeasureRule,
    AdvanceRecoveryWithinAdvanceRule,
    RetentionMatchesConfigRule,
    NetPayableNotNegativeRule,
    TaxesNotStaleRule,
    TaxesConfirmedRule,
    IncomeWithholdingSingleYearRule,
)


def register_hakedis_rules() -> None:
    """Register the certificate rules with the platform rule registry."""
    for rule_class in HAKEDIS_RULES:
        rule_registry.register(rule_class(), [HAKEDIS_RULE_SET])
    logger.debug("contracts: registered %d payment certificate rules", len(HAKEDIS_RULES))


__all__ = ["HAKEDIS_RULES", "register_hakedis_rules"]
