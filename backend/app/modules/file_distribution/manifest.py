# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Distribution module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_file_distribution",
    version="1.0.0",
    display_name="File Distribution",
    description=(
        "Cross-project file search and reusable distribution lists / "
        "subscriptions so transmittals, share links and review packages "
        "always go to the right humans."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users", "oe_documents"],
    # ``file_search`` is intentionally NOT declared here - the search
    # endpoint detects it at runtime and falls back to canonical_name.
    optional_depends=["oe_file_search"],
    auto_install=True,
    enabled=True,
)
