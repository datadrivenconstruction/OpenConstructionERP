# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quality concept module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.quality_concept.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_quality_concept",
    version="0.1.0",
    display_name="Quality and acceptance concept",
    description=(
        "Quality requirements, certification targets, proof concept per package, commissioning "
        "stages from delivery limit to proof of operation, acceptance plan with legal effects, "
        "documentation requirements and evidence preservation; coverage read from linked evidence"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # Evidence stays in its owning modules and is only linked and read; the
    # governance store holds this module's catalogues and reads its readiness.
    depends=[
        "oe_users",
        "oe_projects",
        "oe_project_governance",
        "oe_construction_control",
        "oe_commissioning",
        "oe_requirements",
        "oe_closeout",
        "oe_defects_liability",
        "oe_qms",
    ],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
