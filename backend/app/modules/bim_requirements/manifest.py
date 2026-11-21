# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BIM Requirements Import/Export module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.bim_requirements.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_bim_requirements",
    version="1.0.0",
    display_name="BIM Requirements",
    description=(
        "Universal import/export for BIM requirement formats: "
        "IDS XML, COBie, Excel/CSV, Revit Shared Parameters, BIMQ JSON"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
