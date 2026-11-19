# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Finance module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.finance.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_finance",
    version="0.1.0",
    display_name="Finance",
    description="Invoicing, payments, budgets, and Earned Value Management for construction projects",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_contacts"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
