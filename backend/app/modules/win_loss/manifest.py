# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid outcome ledger module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_win_loss",
    version="0.1.0",
    display_name="Bid Outcome Ledger",
    description=(
        "Record how each bid we submitted ended: won, lost or withdrawn, the winning and second price, "
        "the number of competitors, the money left on the table and the hit rate by client, trade and size"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
)
