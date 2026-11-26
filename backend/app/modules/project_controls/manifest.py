# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Project Controls module manifest.

A thin, read-only consumer module (connective-tissue feature 09). It joins
the cost spine, schedule, quality, safety, risk and change data into one
executive controls snapshot via the shared ``bi_dashboards.kpis`` registry.

It owns NO tables and writes to no other module. The snapshot endpoint is a
single-round-trip aggregation over KPIs other modules already compute, with
status banding and cross-module drill-down deep links.
"""

from app.core.module_loader import ModuleManifest
from app.modules.project_controls.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_project_controls",
    version="1.0.0",
    display_name="Project Controls",
    description=(
        "Executive cross-module controls dashboard. Cost (EVM), schedule, "
        "quality, safety, risk and change KPIs side by side, currency-honest, "
        "with one-click drill-down to the owning module. Pure read-only "
        "consumer over the shared KPI registry."
    ),
    author="OpenConstructionERP",
    category="extension",
    depends=["oe_projects", "oe_users", "oe_bi_dashboards"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
