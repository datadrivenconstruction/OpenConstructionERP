# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Architecture Map module manifest."""

from app.core.data_paths import DataPaths
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_architecture_map",
    version="1.0.0",
    display_name="Architecture Map",
    description="Interactive visual map of system architecture",
    author="OpenConstructionERP Core Team",
    category="developer_tools",
    depends=[],
    auto_install=True,
    data_paths=DataPaths(reason="Read-only map of the system architecture; owns no records"),
)
