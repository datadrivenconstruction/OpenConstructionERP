# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Match module manifest — auto-mounted at ``/api/v1/match/``."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_match",
    version="0.1.0",
    display_name="Element Match",
    description=(
        "Element-to-CWICR vector matcher. Takes a BIM/PDF/DWG/photo "
        "element and returns ranked CWICR cost-position candidates "
        "with classification, unit, region, and lex boosts."
    ),
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_costs"],
    optional_depends=["oe_ai"],
    auto_install=True,
    enabled=True,
)
