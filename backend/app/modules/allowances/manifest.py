# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Allowances & contingency register module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.allowances.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_allowances",
    version="0.1.0",
    display_name="Allowances & Contingency",
    description=(
        "A register of the money an estimate carries but has not yet measured - "
        "provisional sums, prime-cost sums and design / construction "
        "contingencies - each with a held amount and a running drawdown as scope "
        "firms up. Rolls the remaining allowances into the estimate total per "
        "currency and shows how much has been spent against each."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
