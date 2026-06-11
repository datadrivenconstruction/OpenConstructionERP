# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File tags module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_file_tags",
    version="0.1.0",
    display_name="File Tags",
    description=(
        "Project-scoped polymorphic tags for every file kind. Includes "
        "bulk assign/unassign endpoints and an AECO seed-defaults helper "
        "(disciplines + phases)."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
)
