# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Closeout module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.closeout.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_closeout",
    version="0.1.0",
    display_name="Handover & Closeout",
    description=(
        "Per-project digital handover and closeout package assembly - "
        "configurable checklist, CDE document binding, live closure "
        "evidence from punchlist/inspections/COBie, completeness tracking, "
        "idempotent ZIP build with PDF cover and machine-readable manifest"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_documents"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
