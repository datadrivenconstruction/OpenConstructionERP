# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid Management module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_bid_management",
    version="0.1.0",
    display_name="Subcontract Packages",
    description=(
        "Trade and supply packages to subcontractors and suppliers: invitations, Q&A, bid leveling with plugs, "
        "award to a subcontract agreement (subcontract package) or a purchase order (supply package)"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)
