# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site-prep module (pre-construction mobilisation and site-setup readiness).

Before construction can start, the site must be mobilised. This module tracks
readiness per project: a plan with a target commencement date, and a checklist of
readiness items grouped by mobilisation category (access, welfare, temporary
utilities, security and hoarding, temporary works, environmental controls,
logistics and laydown, permits and consents, inductions and training). Readiness
itself is never stored - per-category and overall percentages, the commencement
gate status, and the blocked and overdue lists are derived from the items by the
pure functions in :mod:`app.modules.site_prep.readiness`.
"""


async def on_startup() -> None:
    """Module startup hook - register the read/write permissions."""
    from app.modules.site_prep.permissions import register_site_prep_permissions

    register_site_prep_permissions()
    from app.modules.site_prep.validators import register_site_prep_validation_rules

    register_site_prep_validation_rules()
