# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Reporting & Dashboards module.

Provides KPI snapshots, reusable report templates, scheduled report
delivery (cron) and generated-report history for projects and
portfolios.
"""


async def on_startup() -> None:
    """Module startup hook - register RBAC permissions.

    Invoked by :class:`app.core.module_loader` after the module's models,
    hooks and router are loaded. Registering here (rather than in
    ``main.py``) keeps the permission contract colocated with the module
    that enforces it, exactly like the sibling ``boq`` / ``finance``
    modules.
    """
    from app.modules.reporting.permissions import register_reporting_permissions

    register_reporting_permissions()
    from app.modules.reporting.validators import register_reporting_validation_rules

    register_reporting_validation_rules()
