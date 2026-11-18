# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Norm pricing module.

Per-project settings for norm-based estimating (estimate wage, monthly hours,
funding class, labour location) and the graded labour rates derived from them.
Every national value comes from the country pack through :mod:`app.core.norm_bases`.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.norm_pricing.permissions import register_norm_pricing_permissions

    register_norm_pricing_permissions()
