# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dispatch board module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_dispatch",
    version="0.1.0",
    display_name="Dispatch board",
    description=(
        "Magnet board for crews, people and machines: place them on sites, yard and shop day by day, "
        "see conflicts, book moves ahead, send each foreman tomorrow's plan and prefill the site timesheet"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_projects", "oe_resources", "oe_equipment"],
    optional_depends=["oe_field_time", "oe_notifications", "oe_labor_rates"],
    auto_install=True,
    enabled=True,
)
