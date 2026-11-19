# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DACH pack validation: the ``datev.*`` export rules and the German subcontract deduction rules."""

from __future__ import annotations

from app.core.validation.engine import rule_registry
from app.modules.dach_pack.subcontract_rules import register_german_subcontract_rules
from app.modules.finance.booking_rules import DATEV_RULES

DATEV_RULE_SET = "datev_export"


def register_datev_rules() -> None:
    for rule in DATEV_RULES:
        rule_registry.register(rule(), rule_sets=[DATEV_RULE_SET])


register_datev_rules()
register_german_subcontract_rules()
