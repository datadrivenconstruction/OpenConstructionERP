# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Global presence module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.global_presence.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_global_presence",
    version="1.0.0",
    display_name="Global Presence",
    description=(
        "Real-time awareness of who is online and which page they are viewing. "
        "Ephemeral, in-memory state broadcast over a single global WebSocket room."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
