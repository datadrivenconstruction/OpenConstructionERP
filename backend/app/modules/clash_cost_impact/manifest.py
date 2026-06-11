# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Clash cost-impact module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_clash_cost_impact",
    version="1.0.0",
    display_name="Clash Cost Impact",
    description=(
        "Bridges clash detection (BIM coordination) and the BOQ module to "
        "surface an estimated rework cost per clash and a project-level "
        "open-impact rollup - the unique-to-AGPL-ERP move competitors "
        "cannot match, since they ship coordination without a BOQ side."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_clash", "oe_boq", "oe_projects"],
    auto_install=True,
    enabled=True,
)
