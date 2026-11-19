# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dataflow module manifest."""

from app.core.data_paths import DataPaths
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_dataflow",
    version="0.1.0",
    display_name="Data paths",
    description=(
        "Where each module's data comes from and goes to: live counts per path, the platform map, "
        "project data map and the parties working on the data"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DataPaths(reason="Reads every module's declared paths and owns no records of its own"),
)
