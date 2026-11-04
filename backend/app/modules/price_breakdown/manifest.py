# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Price Breakdown module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_price_breakdown",
    version="1.0.0",
    display_name="Price Breakdown",
    description=(
        "Unit-price analysis library: splits a position rate into labour, material, plant, subcontract and other, plus overhead, risk and profit markup."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=[],  # pure library; boq and others depend on us, not the other way
    auto_install=True,
    enabled=True,
)
