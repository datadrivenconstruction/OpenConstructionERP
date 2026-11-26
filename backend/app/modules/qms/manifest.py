# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""QMS module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.qms.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_qms",
    version="1.0.0",
    display_name="Quality Management System (QMS)",
    description=("Unified ITP + Inspections + NCR + Punch List + Audits with COPQ analytics"),
    author="OpenConstructionERP",
    category="extension",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
