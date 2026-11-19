# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Full EVM module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.full_evm.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_full_evm",
    version="1.0.0",
    display_name="Full EVM",
    description=(
        "Earned Value Management register: approved performance measurement baselines with a "
        "cumulative planned-value curve, period measurements, and the full metric set (PV, EV, "
        "AC, SV, CV, SPI, CPI, EAC, ETC, VAC, TCPI) with every EAC formula reported side by side"
    ),
    author="OpenConstructionERP Core Team",
    category="enterprise",
    # oe_finance supplies the EVM snapshots the forecast surface reads.
    # oe_eac supplies the shared EAC method vocabulary and metric glossary, so
    # "combined" means the same formula everywhere on the platform.
    # oe_projects backs the per-project ownership check on every endpoint.
    depends=["oe_finance", "oe_eac", "oe_projects"],
    auto_install=False,
    enabled=True,
    data_paths=DATA_PATHS,
)
