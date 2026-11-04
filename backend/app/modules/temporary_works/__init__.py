# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Temporary-works module (safety-critical temporary-works governance register).

Construction temporary works - falsework, formwork, propping, excavation support,
scaffold, facade retention, crane bases, dewatering and the rest - carry
construction loads while the permanent works are incomplete, so their failure is
life-threatening. This module tracks the governance every such item must pass
through: a design brief, an independent design check whose rigour scales with a
category (0 to 3), a Temporary Works Coordinator permit to load, an inspection
before use, and a permit to strike or dismantle. Clearance itself is never
stored - the per-status and per-category counts, the design-clearance progress,
the overdue lists, the per-item load and strike gate status, and the critical
"bearing load without a valid permit" breach list are all derived from the items
and their permits by the pure functions in
:mod:`app.modules.temporary_works.register`.
"""

from app.modules.temporary_works.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Module startup hook - register the read/write permissions."""
    from app.modules.temporary_works.permissions import (
        register_temporary_works_permissions,
    )

    register_temporary_works_permissions()
    from app.modules.temporary_works.validators import register_temporary_works_validation_rules

    register_temporary_works_validation_rules()
