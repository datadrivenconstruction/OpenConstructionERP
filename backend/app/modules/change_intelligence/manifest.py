# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Change Intelligence module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.change_intelligence.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_change_intelligence",
    version="0.1.0",
    display_name="Change Intelligence",
    description=(
        "Analytical layer over the change-management family (change orders, "
        "variation notices / requests / orders, management-of-change entries). "
        "Reads their live state to answer what is waiting on whom and for how "
        "long (cycle-time telemetry), with no tables of its own and no "
        "migration - it queries the existing change records"
    ),
    author="OpenConstructionERP Core Team",
    category="controls",
    depends=[
        "oe_users",
        "oe_projects",
        "oe_changeorders",
        "oe_variations",
        "oe_moc",
        "oe_contracts",
        "oe_correspondence",
        "oe_notifications",
        "oe_meetings",
        "oe_risk",
        "oe_rfi",
        "oe_submittals",
    ],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
