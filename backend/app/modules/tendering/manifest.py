# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tendering module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_tendering",
    version="0.1.0",
    display_name="Main Contract Tender",
    description=(
        "Main contract tender priced from the bill of quantities: distribute, collect and compare bids, "
        "award the main contract and write the winning rates back into the BOQ"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
)
