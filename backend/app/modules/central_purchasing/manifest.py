# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Central purchasing module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.central_purchasing.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_central_purchasing",
    version="0.1.0",
    display_name="Central Purchasing",
    description=(
        "One tender for several projects: shares per project, an exact award split, and one contract "
        "or purchase order per project and company, or a framework agreement per company with call-offs"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects", "oe_contracts", "oe_procurement", "oe_costmodel", "oe_legal_entities"],
    # Framework mode stores the agreed rates in its price list when it is installed.
    optional_depends=["oe_framework_agreements", "oe_subcontractors"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
