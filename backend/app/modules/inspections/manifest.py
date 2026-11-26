# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Inspections module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.inspections.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_inspections",
    version="0.1.0",
    display_name="Quality Inspections",
    description="Quality inspection management - concrete pours, waterproofing, MEP, fire stopping, handover with checklists and pass/fail workflows",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
