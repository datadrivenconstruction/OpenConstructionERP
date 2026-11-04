# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site inventory validation rules (rule set ``site_inventory``).

Rules run over the movement about to be recorded, with the item's ledger totals
read by the service::

    {"movement": {"movement_type", "quantity", "unit_cost", "currency", "item_currency",
                  "occurred_at", "has_history", "on_hand", "inbound_total", "waste_total"}}

An item with no movement yet has no ledger to contradict, so stock rules pass until
its first receipt is booked.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section, to_dec
from app.core.validation.site_rules import SiteRule

SITE_INVENTORY_RULE_SET = "site_inventory"

_REMOVING = frozenset({"CONSUMPTION", "WASTE", "TRANSFER"})
#: Cutting, breakage and off-cuts above a tenth of what was delivered point at theft or a wrong quantity.
WASTE_ALLOWANCE = Decimal("0.10")


class StockNotNegativeRule(SiteRule):
    """Material that is not on site cannot be used, wasted or moved."""

    rule_id = "site_inventory.stock_not_negative"
    name = "Removal does not exceed stock on hand"
    standard = SITE_INVENTORY_RULE_SET
    description = "CONSUMPTION, WASTE and TRANSFER quantity must not exceed the item's stock on hand"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        m = section(context, "movement")
        qty, on_hand = to_dec(m.get("quantity")), to_dec(m.get("on_hand"))
        if (
            m.get("movement_type") in _REMOVING
            and m.get("has_history")
            and qty is not None
            and on_hand is not None
            and qty > on_hand
        ):
            return [
                self.site_fail(
                    context,
                    "limit_exceeded",
                    field="quantity",
                    value=qty,
                    limit_field="stock_on_hand",
                    limit=max(on_hand, Decimal("0")),
                )
            ]
        return [self.ok()]


class MovementNotFutureRule(SiteRule):
    """A movement on the ledger has happened."""

    rule_id = "site_inventory.movement_not_future"
    name = "Movement is not dated in the future"
    standard = SITE_INVENTORY_RULE_SET
    description = "occurred_at must not be later than now (one day of slack)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        bad = self.future_date(context, "", "occurred_at", section(context, "movement").get("occurred_at"))
        return [bad] if bad else [self.ok()]


class WasteAllowanceRule(SiteRule):
    """Waste beyond the usual allowance is worth a second look."""

    rule_id = "site_inventory.waste_allowance"
    name = "Waste stays within the allowance"
    standard = SITE_INVENTORY_RULE_SET
    severity = Severity.WARNING
    description = "Cumulative waste above 10 percent of the quantity received is reported"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        m = section(context, "movement")
        qty, inbound, waste = to_dec(m.get("quantity")), to_dec(m.get("inbound_total")), to_dec(m.get("waste_total"))
        if m.get("movement_type") == "WASTE" and qty is not None and inbound and inbound > 0:
            total = (waste or Decimal("0")) + qty
            allowed = inbound * WASTE_ALLOWANCE
            if total > allowed:
                return [
                    self.site_fail(
                        context,
                        "limit_exceeded",
                        field="waste_total",
                        value=total,
                        limit_field="inbound_total x 10%",
                        limit=allowed,
                    )
                ]
        return [self.ok()]


class CostNeedsCurrencyRule(SiteRule):
    """A priced movement says in what currency."""

    rule_id = "site_inventory.cost_needs_currency"
    name = "Priced movement states a currency"
    standard = SITE_INVENTORY_RULE_SET
    description = "unit_cost above zero needs a currency on the movement or on the item"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        m = section(context, "movement")
        cost = to_dec(m.get("unit_cost"))
        if cost is not None and cost > 0 and blank(m.get("currency")) and blank(m.get("item_currency")):
            return [self.fail(context, "currency_present")]
        return [self.ok()]


SITE_INVENTORY_RULES = (
    StockNotNegativeRule,
    MovementNotFutureRule,
    WasteAllowanceRule,
    CostNeedsCurrencyRule,
)


def register_site_inventory_validation_rules() -> None:
    """Register the site inventory rules with the platform rule registry."""
    for rule_class in SITE_INVENTORY_RULES:
        rule_registry.register(rule_class(), [SITE_INVENTORY_RULE_SET])


__all__ = ["SITE_INVENTORY_RULES", "SITE_INVENTORY_RULE_SET", "register_site_inventory_validation_rules"]
