# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Condition & Maintenance Plan module.

Condition ratings of assets and building elements on a configurable scale
(shipped neutral default, pack-provided national scales, project scales), and a
multi-year maintenance plan derived from them as proposals a person approves.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and validation rules."""
    from app.modules.condition.permissions import register_condition_permissions
    from app.modules.condition.validators import register_condition_validation_rules

    register_condition_permissions()
    register_condition_validation_rules()
