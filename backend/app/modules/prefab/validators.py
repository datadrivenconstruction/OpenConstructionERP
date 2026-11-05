# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Prefab validation rules (rule set ``prefab``).

Rules run over a plain dict context built by the caller::

    {"unit": {"id", "ref", "status", "target_install_date", "bim_element_ids", "operation"}}

``unit.operation`` is ``create``, ``update`` or ``advance``. ``metadata["today"]`` (ISO date) overrides
the reference day.
"""

from __future__ import annotations

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, section
from app.core.validation.quality_rules import parse_day, today_of
from app.modules.prefab.guard import POST_QA_STAGES

PREFAB_RULE_SET = "prefab"

#: Stages from which a unit is on its way to site and the crane / receiving slot has to be planned.
_ON_THE_WAY = frozenset({"dispatched"})


class _PrefabRule(MoneyRule):
    standard = PREFAB_RULE_SET
    message_section = "prefab"
    own_message_keys = frozenset({"entry_past_qa", "bim_ids_invalid", "install_date_passed", "dispatch_without_date"})


class UnitEntryStageRule(_PrefabRule):
    """A unit is registered before QA, never straight into dispatch, delivery or installation."""

    rule_id = "prefab.entry_before_qa"
    name = "Prefab unit is registered before QA"
    description = "a new unit cannot start at dispatched, delivered or installed: QA would be skipped"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        u = section(context, "unit")
        ref = str(u.get("id") or u.get("ref") or "")
        if u.get("operation") == "create" and u.get("status") in POST_QA_STAGES:
            return [self.fail(context, "entry_past_qa", ref=ref, unit=u.get("ref", ""))]
        return [self.ok(ref)]


class UnitBimElementsRule(_PrefabRule):
    """The linked BIM element ids are real and each appears once."""

    rule_id = "prefab.bim_elements_clean"
    name = "Prefab unit BIM element ids are clean"
    description = "blank or repeated entries in bim_element_ids break the link to the model"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        u = section(context, "unit")
        ref = str(u.get("id") or u.get("ref") or "")
        ids = u.get("bim_element_ids") or []
        cleaned = [str(i).strip() for i in ids]
        if any(not i for i in cleaned) or len(set(cleaned)) != len(cleaned):
            return [self.fail(context, "bim_ids_invalid", ref=ref)]
        return [self.ok(ref)]


class UnitInstallDateRule(_PrefabRule):
    """A unit not yet installed has a target date that is still ahead."""

    rule_id = "prefab.install_date_ahead"
    name = "Prefab target install date is not behind us"
    severity = Severity.WARNING
    description = "target_install_date is in the past while the unit is not installed"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        u = section(context, "unit")
        ref = str(u.get("id") or u.get("ref") or "")
        due = parse_day(u.get("target_install_date"))
        if due is not None and u.get("status") != "installed" and due < today_of(context):
            return [self.fail(context, "install_date_passed", ref=ref, date=due.isoformat())]
        return [self.ok(ref)]


class UnitDispatchPlannedRule(_PrefabRule):
    """A unit leaving the factory has a target install date, so site can plan the lift."""

    rule_id = "prefab.dispatch_has_install_date"
    name = "Dispatched prefab unit has an install date"
    severity = Severity.WARNING
    description = "dispatched without target_install_date leaves site without a delivery and crane slot"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        u = section(context, "unit")
        ref = str(u.get("id") or u.get("ref") or "")
        if u.get("status") in _ON_THE_WAY and blank(u.get("target_install_date")):
            return [self.fail(context, "dispatch_without_date", ref=ref)]
        return [self.ok(ref)]


PREFAB_RULES = (UnitEntryStageRule, UnitBimElementsRule, UnitInstallDateRule, UnitDispatchPlannedRule)


def register_prefab_validation_rules() -> None:
    """Register the prefab rules with the platform rule registry."""
    for rule_class in PREFAB_RULES:
        rule_registry.register(rule_class(), [PREFAB_RULE_SET])


__all__ = ["PREFAB_RULES", "PREFAB_RULE_SET", "register_prefab_validation_rules"]
