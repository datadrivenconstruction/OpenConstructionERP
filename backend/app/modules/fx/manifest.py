# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Currency / FX module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.fx.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_fx",
    version="1.0.0",
    display_name="Currency / FX",
    description=(
        "Exchange-rate register: published rate sets with provenance, point-in-time conversion, "
        "per-project currency policy with pinning, and revaluation that separates scope movement "
        "from rate movement"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_costs"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
