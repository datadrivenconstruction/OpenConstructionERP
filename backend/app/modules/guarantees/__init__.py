# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Guarantees​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ register module (bank guarantees and bonds).

One register for every guarantee and bond on a project: bid bonds per bidder,
performance bonds, advance payment and retention guarantees, warranty bonds and
parent company guarantees, whether the company gave them to a client or received
them from a subcontractor. The register is the single source of truth; contract
security rows of a bond type are projections it writes.
"""

from app.modules.guarantees.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Register permissions, validation rules, event subscriptions and the daily job."""
    from app.modules.guarantees.events import register_guarantees_subscriptions
    from app.modules.guarantees.jobs import register_jobs
    from app.modules.guarantees.permissions import register_guarantees_permissions
    from app.modules.guarantees.validators import register_guarantees_rules

    register_guarantees_permissions()
    register_guarantees_rules()
    register_guarantees_subscriptions()
    register_jobs()
