# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Match Elements module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_match_elements",
    version="0.1.0",
    display_name="CAD Match → Cost",
    description="Map BIM/CAD/PDF/photo elements to CWICR cost positions; auto-load scaled resources into BOQ",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_costs", "oe_boq", "oe_bim_hub"],
    auto_install=True,
    enabled=True,
)
