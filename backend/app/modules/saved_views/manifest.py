# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Saved Views module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_saved_views",
    version="0.1.0",
    display_name="Saved Views",
    description=(
        "Record-level saved-search engine: save a filter spec against any "
        "registered entity and reuse it as a list, count, tile, or export."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)
