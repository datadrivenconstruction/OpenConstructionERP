# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""BI Dashboards & Reporting module manifest.

Read-only module that consumes data from every other module and produces:

* KPI definitions + values (CPI, SPI, TRIR, COPQ, etc.)
* Role-based dashboards (CEO / CFO / PM / Site Manager / Safety Officer)
* Custom report definitions + schedules
* Threshold-based alert rules with throttling
* Saved filters

The module owns ONLY its own configuration tables. It never writes to
another module's tables, and every KPI formula gracefully degrades to
``Decimal("0")`` when its source module is absent (``ImportError``).
"""

from app.core.module_loader import ModuleManifest
from app.modules.bi_dashboards.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_bi_dashboards",
    version="1.0.0",
    display_name="BI Dashboards & Reporting",
    description=(
        "Role-based dashboards, KPI library, custom report builder, "
        "alerts, scheduled digests. Module 20 of the 18-module extension "
        "wave - pure consumer of cross-module data."
    ),
    author="OpenConstructionERP",
    category="extension",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
