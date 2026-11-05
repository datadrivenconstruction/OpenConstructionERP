# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Design-side site-supervision module.

Plan and record the design team's supervision visits to a project (the
"design-side inspection" known as author supervision / ЖАН in the CIS, contract
administration inspection in the UK, construction administration in the US, and
Objektüberwachung / HOAI LP8 in Germany). Each visit gathers observations -
conformance notes, deviations, hidden-works acceptance items, instructions and
motivated refusals - that carry a structured record serialisable to a
supervision-log XML and an optional link into the change / MOC route.

It is deliberately jurisdiction-neutral: it records what was inspected and
observed, when, by whom and in which discipline, never a country's rule.
Per-country vocabularies come from the regional packs. The module surfaces
plan-versus-fact tracking (overdue planned visits, completion ratio), a
hidden-works acceptance register for handover, and a plan-coverage validation
check for closeout.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.site_supervision.permissions import (
        register_site_supervision_permissions,
    )

    register_site_supervision_permissions()
    from app.modules.site_supervision.rules import register_site_supervision_validation_rules

    register_site_supervision_validation_rules()
