# OpenConstructionERP - DataDrivenConstruction (DDC)
# DDC-CWICR-OE-2026
"""Progress module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_progress",
    version="1.0.0",
    display_name="Progress Tracking",
    description=(
        "Site-execution progress measurement: percent-complete per BOQ position, "
        "per-period deltas, cumulative rollup, S-curve generation, parent rollup "
        "from children, geo-tagged field entries."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
)
