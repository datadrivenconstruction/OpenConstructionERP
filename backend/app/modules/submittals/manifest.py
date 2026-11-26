# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Submittals module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.submittals.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_submittals",
    version="0.1.0",
    display_name="Submittals",
    description="Construction submittal management - shop drawings, product data, samples, mock-ups, test reports, calculations, method statements, certificates and warranties with review/approval workflows",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
