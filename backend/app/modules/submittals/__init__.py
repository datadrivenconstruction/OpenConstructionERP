# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Submittals module.

Construction submittal management - shop drawings, product data, samples,
mock-ups, test reports, calculations, method statements, certificates and
warranties with multi-stage review/approval workflows.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions + approval-routes wiring."""
    from app.modules.submittals.approval_subscribers import (
        register_submittal_approval_subscribers,
    )
    from app.modules.submittals.permissions import register_submittals_permissions

    register_submittals_permissions()
    # Feature 06: drive the submittal FSM off terminal approval-routes
    # decisions when a project has a routed sign-off configured.
    register_submittal_approval_subscribers()
    # The register rules (stamp against status, resubmission link, lead time,
    # approval needed-by) join the "submittal" set the core rules already
    # populate, so one validation call reports both groups.
    from app.modules.submittals.rules import register_submittal_register_rules

    register_submittal_register_rules()
