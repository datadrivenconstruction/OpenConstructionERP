# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contracts module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.contracts.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_contracts",
    version="0.1.0",
    display_name="Contract Types Engine",
    description=(
        "Multi-type contract engine: lump-sum, GMP, cost-plus, T&M, "
        "unit-price, design-build with progress claims, retention, "
        "gainshare, LDs, final account"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
