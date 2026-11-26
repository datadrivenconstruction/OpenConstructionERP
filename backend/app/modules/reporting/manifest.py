# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Reporting module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.reporting.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_reporting",
    version="1.0.0",
    display_name="Reporting & Dashboards",
    description="KPI snapshots, report templates, and generated reports for projects and portfolios",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_boq", "oe_bim_hub"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
