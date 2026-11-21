# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Saved Views module manifest."""

from app.core.data_paths import DataPaths
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_saved_views",
    version="1.0.0",
    display_name="Saved Views",
    description=(
        "Record-level saved-search engine: save a filter spec against any "
        "registered entity, share it with a team or a project, and reuse it as "
        "a list, count, tile, or export."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # oe_teams owns team membership; a team share resolves through it and the
    # saved-view table carries a foreign key into its team table.
    depends=["oe_users", "oe_projects", "oe_teams"],
    auto_install=True,
    enabled=True,
    data_paths=DataPaths(reason="Stores saved filter definitions only; feeds no other module's numbers"),
)
