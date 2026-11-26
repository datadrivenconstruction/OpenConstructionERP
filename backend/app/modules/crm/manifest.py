# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CRM module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.crm.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_crm",
    version="0.1.0",
    display_name="CRM Sales Pipeline",
    description=("Sales pipeline: accounts, leads, opportunities, activities, forecasting, win/loss analytics"),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
