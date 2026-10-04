# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Elemental cost plan module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_cost_plan",
    version="1.0.0",
    display_name="Elemental Cost Plan",
    display_name_i18n={"de": "Elementbasierter Kostenplan", "ru": "Поэлементный план затрат"},
    description=(
        "Rolls a bill of quantities up into an NRM 1 elemental cost plan: group elements 0-8 "
        "with their elements, the building works estimate, the bill's markup cascade below it, "
        "cost per m2 of GIFA and share of total on every line, unallocated positions listed "
        "rather than dropped, and an Excel export with the same structure. Read-only."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # Reads the bill, its markups and the project's floor area. Owns no tables,
    # so no migration is authored here.
    depends=["oe_boq", "oe_projects"],
    auto_install=True,
    enabled=True,
)
