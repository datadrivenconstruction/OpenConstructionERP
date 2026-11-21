# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Enterprise Workflows module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.enterprise_workflows.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_enterprise_workflows",
    version="0.1.0",
    display_name="Enterprise Workflows",
    description="Configurable approval workflows for invoices, purchase orders, variations, and BOQs",
    author="OpenConstructionERP Core Team",
    category="enterprise",
    depends=["oe_users", "oe_projects"],
    auto_install=False,
    enabled=True,
    data_paths=DATA_PATHS,
)
