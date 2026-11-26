# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""MoC module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.moc.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_moc",
    version="1.0.0",
    display_name="Management of Change",
    description=(
        "Structured workflow for proposing, reviewing, approving and "
        "implementing engineering or scope changes with full audit trail."
    ),
    author="OpenConstructionERP Core Team",
    category="project_controls",
    depends=["oe_projects", "oe_variations", "oe_changeorders"],
    auto_install=True,
    data_paths=DATA_PATHS,
)
