# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate check module: a traffic-light sanity review of an estimate before submission.

Every KPI of the estimate is compared with the company's past estimates and rated
Normal, Suspect or Warning. The KPIs are rules of the core validation engine (rule
set ``estimate_checks``); this module adds settings, per-user display preference
and the human acceptance of findings.
"""

from app.modules.estimate_checks.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Register permissions and validation rules."""
    from app.modules.estimate_checks.permissions import register_estimate_check_permissions
    from app.modules.estimate_checks.validators import register_estimate_check_rules

    register_estimate_check_permissions()
    register_estimate_check_rules()
