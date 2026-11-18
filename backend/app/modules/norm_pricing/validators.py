# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules of the norm pricing module.

The rules live in the core rule catalogue (:mod:`app.core.validation.rules.norm_base`)
because a country pack switches them on by name, and a pack may only name rules the
core registers. Two rule sets: ``norm_base`` (code present, code shape, retired prefix,
graded labour, grade on the scale) and ``public_funding`` (markup caps, client estimate
at the cap, material price evidence).
"""

from app.core.validation.rules.norm_base import NORM_BASE_RULE_SET, NORM_BASE_RULES, PUBLIC_FUNDING_RULE_SET

__all__ = ["NORM_BASE_RULES", "NORM_BASE_RULE_SET", "PUBLIC_FUNDING_RULE_SET"]
