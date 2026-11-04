# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bill of Quantities module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_boq",
    version="0.1.0",
    display_name="Bill of Quantities",
    description="Core BOQ editor with hierarchical structure, positions, and cost calculations",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_measurement", "oe_price_breakdown"],
    auto_install=True,
    enabled=True,
)
