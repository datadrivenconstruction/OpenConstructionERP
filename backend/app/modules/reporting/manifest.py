"""Reporting module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_reporting",
    version="0.1.0",
    display_name="Reporting",
    description="Reports, exports, and dashboards for cost estimation data",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
)
