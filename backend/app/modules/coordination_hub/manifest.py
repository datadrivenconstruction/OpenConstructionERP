# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Coordination Hub module manifest."""

from app.core.data_paths import DataPaths
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_coordination_hub",
    version="1.0.0",
    display_name="Coordination Hub",
    description=(
        "Project-level Model Coordination dashboard: unifies federations, "
        "clashes, smart views, rule packs and BCF activity into one read-only "
        "rollup with BOQ-impact totals. No new tables - pure aggregator over "
        "the sibling BIM modules."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DataPaths(reason="Read-only dashboard over federations, clashes and BCF activity; owns no records"),
)
