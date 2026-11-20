# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Stockpiles module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.stockpiles.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_stockpiles",
    version="0.1.0",
    display_name="Stockpiles",
    description=(
        "Stockpile surveys: the volume of a pile above its base surface, tonnes from a stated density "
        "(measured, supplier or assumed), and the variance against book stock. A variance becomes an "
        "adjustment proposal for the site inventory that a person confirms before anything is booked."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_survey_core", "oe_surfaces_volumes"],
    optional_depends=["oe_site_inventory", "oe_documents"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
