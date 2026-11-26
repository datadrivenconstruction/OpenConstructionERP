# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DWG Takeoff module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.dwg_takeoff.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_dwg_takeoff",
    version="1.0.0",
    display_name="DWG Takeoff",
    description="2D DWG/DXF drawing viewer with measurements, annotations, and BOQ linking",
    author="OpenConstructionERP Core Team",
    category="extension",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
