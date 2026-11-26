# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CVR (Cost-Value Reconciliation) & Cashflow module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.cvr.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_cvr",
    version="1.0.0",
    display_name="Cost-Value Reconciliation & Cashflow",
    description=(
        "Commercial monthly CVR - reconcile cost-to-date against value earned per "
        "cost head, forecast final cost, value and margin, and forecast project "
        "cashflow as a cumulative S-curve, with interim payment applications."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
