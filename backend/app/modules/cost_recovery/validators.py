# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost recovery validation rules (rule set ``cost_recovery``).

Rules run over a plain dict context::

    {
        "back_charge": {"id", "project_id", "responsible_party", "gross_amount",
                        "chargeable_pct", "recovered_amount", "currency",
                        "status", "previous_status"},
        "apportionments": [{"id", "party", "share_pct", "share_amount", "currency"}],
    }
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, ValidationContext, rule_registry
from app.core.validation.money_rules import (
    MAX_SANE_AMOUNT,
    MONEY_TOLERANCE,
    MoneyRule,
    blank,
    currency_of,
    rows,
    section,
    to_dec,
)
from app.modules.cost_recovery.back_charge import (
    STATUS_AGREED,
    STATUS_DISPUTED,
    STATUS_PROPOSED,
    STATUS_RECOVERED,
    STATUS_WAIVED,
)

COST_RECOVERY_RULE_SET = "cost_recovery"

#: Closed states are terminal; a recovery is only booked against an agreed claim.
BACK_CHARGE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    STATUS_PROPOSED: (STATUS_AGREED, STATUS_DISPUTED, STATUS_WAIVED),
    STATUS_AGREED: (STATUS_RECOVERED, STATUS_DISPUTED, STATUS_WAIVED),
    STATUS_DISPUTED: (STATUS_AGREED, STATUS_WAIVED),
    STATUS_RECOVERED: (),
    STATUS_WAIVED: (),
}

_ZERO = Decimal("0")
_ONE = Decimal("1")


class ApportionmentTotalsRule(MoneyRule):
    """The shares add up to the chargeable amount and to at most 100 per cent."""

    rule_id = "cost_recovery.apportionment_totals"
    name = "Apportionment shares add up to the chargeable amount"
    standard = COST_RECOVERY_RULE_SET
    description = "Sum of share amounts equals gross x chargeable pct; share pct sum does not exceed 1"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        bc = section(context, "back_charge")
        shares = rows(context, "apportionments")
        ref = str(bc.get("id", ""))
        if not shares:
            return [self.ok(ref)]
        out: list[RuleResult] = []
        gross = to_dec(bc.get("gross_amount"))
        pct = to_dec(bc.get("chargeable_pct"))
        amounts = [to_dec(s.get("share_amount")) for s in shares]
        if gross is not None and pct is not None and all(a is not None for a in amounts):
            bad = self.total_mismatch(context, ref, "apportionment", sum(amounts, _ZERO), gross * pct, currency_of(bc))
            if bad:
                out.append(bad)
        pcts = [to_dec(s.get("share_pct")) for s in shares]
        if all(p is not None for p in pcts) and sum(pcts, _ZERO) > _ONE + Decimal("0.0001"):
            out.append(
                self.fail(context, "value_in_range", ref=ref, field="share_pct", value=sum(pcts, _ZERO), low=0, high=1)
            )
        return out or [self.ok(ref)]


class BackChargeRangesRule(MoneyRule):
    """Amounts are non-negative, shares lie in 0..1, recovery never exceeds the charge."""

    rule_id = "cost_recovery.values_in_range"
    name = "Back-charge amounts and shares are sane"
    standard = COST_RECOVERY_RULE_SET
    description = "gross >= 0, chargeable_pct in 0..1, share_pct in 0..1, recovered <= gross x pct"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        bc = section(context, "back_charge")
        ref = str(bc.get("id", ""))
        gross = to_dec(bc.get("gross_amount"))
        pct = to_dec(bc.get("chargeable_pct"))
        recovered = to_dec(bc.get("recovered_amount"))
        checks = [
            (ref, "gross_amount", gross, _ZERO, MAX_SANE_AMOUNT),
            (ref, "chargeable_pct", pct, _ZERO, _ONE),
            (ref, "recovered_amount", recovered, _ZERO, MAX_SANE_AMOUNT),
        ]
        for share in rows(context, "apportionments"):
            sref = str(share.get("id", ref))
            checks.append((sref, "share_pct", to_dec(share.get("share_pct")), _ZERO, _ONE))
            checks.append((sref, "share_amount", to_dec(share.get("share_amount")), _ZERO, MAX_SANE_AMOUNT))
        out = [r for r in (self.out_of_range(context, *c) for c in checks) if r]
        if (
            gross is not None
            and pct is not None
            and recovered is not None
            and recovered - gross * pct > MONEY_TOLERANCE
        ):
            out.append(
                self.fail(
                    context,
                    "value_in_range",
                    ref=ref,
                    field="recovered_amount",
                    value=recovered,
                    low=0,
                    high=gross * pct,
                )
            )
        return out or [self.ok(ref)]


class BackChargeCurrencyRule(MoneyRule):
    """A back-charge with money states a currency, and its shares carry the same one."""

    rule_id = "cost_recovery.currency_consistent"
    name = "Back-charge currency stated and consistent"
    standard = COST_RECOVERY_RULE_SET
    description = "Currency present on the back-charge and identical on every apportionment row"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        bc = section(context, "back_charge")
        ref = str(bc.get("id", ""))
        if not to_dec(bc.get("gross_amount")):
            return [self.ok(ref)]
        found = self.currency_findings(
            context, ref, currency_of(bc), [currency_of(s) for s in rows(context, "apportionments")]
        )
        return found or [self.ok(ref)]


class BackChargeReferencesRule(MoneyRule):
    """A back-charge names its project and the party it is charged to."""

    rule_id = "cost_recovery.references_present"
    name = "Back-charge references present"
    standard = COST_RECOVERY_RULE_SET
    description = "project_id and responsible_party are required; each share names its party"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        bc = section(context, "back_charge")
        ref = str(bc.get("id", ""))
        out = [
            self.fail(context, "reference_present", ref=ref, field=field)
            for field in ("project_id", "responsible_party")
            if blank(bc.get(field))
        ]
        out += [
            self.fail(context, "reference_present", ref=str(s.get("id", ref)), field="party")
            for s in rows(context, "apportionments")
            if blank(s.get("party"))
        ]
        return out or [self.ok(ref)]


class BackChargeStatusTransitionRule(MoneyRule):
    """The status moved along an edge of the recovery workflow."""

    rule_id = "cost_recovery.status_transition"
    name = "Back-charge status transition allowed"
    standard = COST_RECOVERY_RULE_SET
    description = "Closed back-charges (recovered, waived) are final; recovery follows agreement"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        bc = section(context, "back_charge")
        ref = str(bc.get("id", ""))
        found = self.status_findings(context, ref, bc.get("previous_status"), bc.get("status"), BACK_CHARGE_TRANSITIONS)
        return found or [self.ok(ref)]


COST_RECOVERY_RULES = (
    ApportionmentTotalsRule,
    BackChargeRangesRule,
    BackChargeCurrencyRule,
    BackChargeReferencesRule,
    BackChargeStatusTransitionRule,
)


def register_cost_recovery_validation_rules() -> None:
    """Register the cost recovery rules with the platform rule registry."""
    for rule_class in COST_RECOVERY_RULES:
        rule_registry.register(rule_class(), [COST_RECOVERY_RULE_SET])
