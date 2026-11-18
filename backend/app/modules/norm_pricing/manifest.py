# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Norm pricing module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_norm_pricing",
    version="0.1.0",
    display_name="Norm Pricing",
    description=(
        "Norm-based estimating settings per project: estimate wage, monthly hours, funding class and "
        "labour location, the graded hourly labour rates derived from them with the derivation shown, "
        "and the norm-code and funding-cap checks of the norm_base and public_funding rule sets. "
        "Shown only where a country pack supplies a norm base or pricing rules."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
)
