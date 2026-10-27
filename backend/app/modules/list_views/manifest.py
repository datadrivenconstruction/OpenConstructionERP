# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""List Views module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_list_views",
    version="1.0.0",
    display_name="List Views",
    description=(
        "Saved table layouts for every list page: visible columns, widths, sort and the header "
        "filters as a named layout, personal or shared with the team. Separate from oe_saved_views, "
        "which runs server-side filter specs against registered entities and stores no column "
        "layout; this one keeps presentation state for any table, registered or not."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
)
