# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WIP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ report module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_wip_report",
    version="1.0.0",
    display_name="WIP Report",
    description=(
        "Work in progress schedule with over and under billing, per project and for the portfolio, on the "
        "percentage-of-completion cost-to-cost method. Reads contract value and approved change orders, cost "
        "to date and estimate at completion from the cost-value reconciliation, and billings from progress "
        "claims and invoices; closes month-end snapshots, shows gross profit fade or gain against the "
        "previous close and the backlog, and exports to Excel and PDF."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_projects"],
    optional_depends=["oe_contracts", "oe_changeorders", "oe_cvr", "oe_finance"],
    auto_install=True,
    enabled=True,
)
