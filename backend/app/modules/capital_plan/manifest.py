# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Capital plan module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_capital_plan",
    version="0.1.0",
    display_name="Capital Plan",
    description=(
        "Rank projects against a limited annual budget: yearly funding envelopes, "
        "phased project spend, what-if scenarios and greedy funding suggestions"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects", "oe_portfolio"],
    auto_install=True,
    enabled=True,
)
