# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement concept module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.procurement_concept.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_procurement_concept",
    version="0.1.0",
    display_name="Procurement concept",
    description=(
        "Award concept: packages by trade, section or system, advance packages, procedure and "
        "threshold check per package, prequalification to a short list, market sounding, "
        "award schedule from need dates and lead times, framework agreements with call-offs"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    # oe_project_governance owns the catalogue store, the frame document and
    # gate readiness; bid_management and rfq_bidding are the execution vehicles
    # this module creates and reads back. Module 3's package plan is read through
    # its table contract (plan_source.py), so it is not a hard dependency.
    depends=["oe_users", "oe_projects", "oe_project_governance", "oe_bid_management", "oe_rfq_bidding"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
