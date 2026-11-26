# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deadlines module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.deadlines.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_deadlines",
    version="0.1.0",
    display_name="Deadlines",
    description=(
        "Cross-module overdue escalation - a unified deadline register plus a background "
        "sweep that notifies owners, escalates to managers past a grace window, and rolls "
        "repeat overdue items into the notification digest"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_notifications"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
