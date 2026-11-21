# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Temporary-works module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.temporary_works.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_temporary_works",
    version="1.0.0",
    display_name="Temporary Works Register",
    description=(
        "Safety-critical governance register for construction temporary works "
        "(falsework, formwork, propping, excavation support, scaffold, facade "
        "retention, crane bases, dewatering and more). Each item runs a gated "
        "lifecycle - design brief, independent design check by category (0 to "
        "3), Temporary Works Coordinator permit to load, inspection before use, "
        "and permit to strike or dismantle. The module derives per-status and "
        "per-category counts, the design-clearance progress, the overdue-to-load "
        "and overdue-to-strike lists, the per-item load and strike gate status, "
        "and the single most important safety signal: any item bearing load with "
        "no valid permit to load in force."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # Hard dep supplies the project scope every table foreign-keys into.
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
