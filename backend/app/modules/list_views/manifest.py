# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""List Views module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_list_views",
    version="1.0.0",
    display_name="List Views",
    description=(
        "Saved table layouts for every list page: filters, columns and sort as a named view, "
        "personal or shared with the team."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
)
