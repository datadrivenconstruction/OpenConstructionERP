# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Haul​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ tickets module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_haul_tickets",
    version="1.0.0",
    display_name="Haul Tickets",
    description=(
        "Every truck load to or from site as a ticket: earthworks, aggregates, concrete, asphalt and waste or "
        "spoil disposal, own fleet and hired hauliers. Gross, tare and net weights, volume or loads, rate per "
        "tonne, cubic metre, load or hour, BOQ position or cost code, receiver signature and photos. Fast field "
        "capture by QR, prefilled from the day's expected deliveries, weighbridge CSV or Excel import with "
        "duplicate detection, daily summaries per site and haulier, reconciliation against haulier invoices and "
        "a disposal register for environmental reporting. Verified tickets feed the position actuals."
    ),
    author="OpenConstructionERP Core Team",
    category="field",
    depends=["oe_projects"],
    optional_depends=["oe_site_logistics", "oe_equipment", "oe_procurement", "oe_boq", "oe_costmodel"],
    auto_install=True,
    enabled=True,
)
