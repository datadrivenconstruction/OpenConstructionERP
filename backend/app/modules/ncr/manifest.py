# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""NCR module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.ncr.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_ncr",
    version="0.1.0",
    display_name="Non-Conformance Reports",
    description="NCR management - material, workmanship, design non-conformances with root cause analysis and corrective actions",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    optional_depends=["oe_documents"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
