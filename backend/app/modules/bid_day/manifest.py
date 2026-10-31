# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid day module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_bid_day",
    version="1.0.0",
    display_name="Bid Day",
    description=(
        "The last hours before a tender goes in: one live board per tender with every trade package, the quotes "
        "received for it and the estimate's own figure as baseline. Change a figure, add a late phone or email "
        "quote or switch the chosen quote and the bid total recalculates at once, with the change logged. Scope "
        "gaps are plugged per quote so quotes compare like for like, the lowest adjusted quote is suggested with "
        "its reason, markups are set on the board, and the submitted bid is frozen as an immutable snapshot that "
        "exports to PDF and Excel and can be pushed back into the estimate."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_projects", "oe_tendering", "oe_bid_management"],
    optional_depends=["oe_fx", "oe_boq", "oe_collaboration_locks"],
    auto_install=True,
    enabled=True,
)
