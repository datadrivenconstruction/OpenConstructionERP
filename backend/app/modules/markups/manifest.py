# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Markups & Annotations module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.markups.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_markups",
    version="0.1.0",
    display_name="Markups & Annotations",
    description="Drawing markups, scale calibration, and stamp templates for document annotation",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
