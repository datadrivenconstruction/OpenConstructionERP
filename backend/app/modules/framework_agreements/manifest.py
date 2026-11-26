# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Framework agreements module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.framework_agreements.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_framework_agreements",
    version="0.1.0",
    display_name="Framework Agreements",
    description=(
        "Unit rates agreed once and ordered job by job: price list, rate periods with escalation, "
        "condition adjustments, call-off orders priced only from the agreement, and the cap in view"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects", "oe_contracts", "oe_variations", "oe_price_index"],
    # Packs whose law and practice we sourced: EU directives, Germany, the UK and the US.
    markets=["EU", "GB", "US"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
