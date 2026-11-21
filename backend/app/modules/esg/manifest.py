# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""ESG Site Performance module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.esg.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_esg",
    version="1.0.0",
    display_name="ESG Site Performance",
    description=(
        "Operational site ESG tracking - energy, water, waste, site CO2e, "
        "local labour, training and safety recorded per period against targets, "
        "with direction-aware KPIs and trends (distinct from embodied carbon)"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
