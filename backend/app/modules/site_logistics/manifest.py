# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site Logistics & Delivery module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.site_logistics.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_site_logistics",
    version="1.1.0",
    display_name="Site Logistics & Delivery",
    description=(
        "Plan and control what arrives on site: access gates with operating "
        "hours and slot capacity, material laydown zones, and a delivery "
        "booking board with approve/reject scheduling. Windows are validated "
        "against gate hours and checked for clashes so two approved deliveries "
        "never fight for the same gate. Deliveries are booked against the bill "
        "positions they carry, so every estimate line reads back as booked, "
        "delivered and outstanding. The logistics plan adds expansion stages with "
        "an area balance, gate load limits, utility connections, the logistics "
        "concept, transports with permits, customs data and the neighbourhood."
    ),
    author="OpenConstructionERP",
    category="business",
    # oe_boq: a delivery line points at the BOQ position it delivers, and the
    # bill-coverage table reads the estimate directly.
    # oe_project_governance: catalogue kind, gate evidence and the frame document
    # document; oe_schedule: stage dates are read from schedule activities.
    depends=["oe_projects", "oe_users", "oe_boq", "oe_project_governance", "oe_schedule", "oe_documents"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
