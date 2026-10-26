# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WIP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ report module: work in progress schedule with over and under billing.

Percentage of completion on the cost-to-cost method, per project and for the portfolio.
Inputs stay in their modules (contracts, change orders, cost-value reconciliation,
claims and invoices); this module stores only month-end snapshots and the project
manager's estimate at completion when it overrides the cost report.
"""

from app.modules.wip_report.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Register permissions, validation rules and event subscriptions."""
    from app.modules.wip_report.events import register_wip_report_subscriptions
    from app.modules.wip_report.permissions import register_wip_report_permissions
    from app.modules.wip_report.validators import register_wip_report_rules

    register_wip_report_permissions()
    register_wip_report_rules()
    register_wip_report_subscriptions()
