# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dashboards module manifest - analytical dashboards + snapshots."""

from app.core.module_loader import ModuleManifest
from app.modules.dashboards.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_dashboards",
    version="0.1.0",
    display_name="Dashboards",
    description=(
        "Analytical dashboard layer: Parquet snapshots, DuckDB-backed "
        "insight cards, cascade filters, 3D viewer sync, historical diffs."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
