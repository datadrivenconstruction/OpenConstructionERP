"""Cost-match module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_cost_match",
    version="0.1.0",
    display_name="Cost Match",
    description=(
        "Automatic CWICR item matching for material layers: exact "
        "match first, then semantic via Qdrant when [semantic] extra is "
        "installed, then needs-review candidates."
    ),
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_costs", "oe_dashboards"],
    optional_depends=["oe_ai"],
    auto_install=True,
    enabled=True,
)
