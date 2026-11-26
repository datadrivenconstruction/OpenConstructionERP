# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Meetings module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.meetings.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_meetings",
    version="0.1.0",
    display_name="Meetings",
    description="Meeting minutes management - agendas, attendees, action items, and status tracking",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
