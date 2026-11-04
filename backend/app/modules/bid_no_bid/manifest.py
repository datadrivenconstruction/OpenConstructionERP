# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid / no-bid scorecard module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_bid_no_bid",
    version="1.0.0",
    display_name="Bid / No-Bid",
    description=(
        "A one-page go / no-go decision for a tender: rate client, capacity, risk, margin and competition from "
        "1 to 5, weigh them, and see the score against your threshold. The recommendation is advice; the "
        "decision is a person's, an override needs a reason, every change is logged, and the decision and "
        "outcome feed the win-loss ledger."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_projects", "oe_tendering", "oe_win_loss"],
    optional_depends=["oe_crm"],
    auto_install=True,
    enabled=True,
)
