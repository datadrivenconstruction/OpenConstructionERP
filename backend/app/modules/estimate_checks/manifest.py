# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate check module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_estimate_checks",
    version="1.0.0",
    display_name="Estimate Check",
    description=(
        "Traffic-light sanity review of an estimate before it is submitted: labour, equipment, material, "
        "subcontractor and markup ratios compared with the usual range of the company's past estimates, "
        "plus data quality checks. Findings can be accepted with a reason; thresholds are editable."
    ),
    author="OpenConstructionERP Core Team",
    category="estimation",
    depends=["oe_projects", "oe_boq"],
    optional_depends=["oe_costs"],
    auto_install=True,
    enabled=True,
)
