"""DWG Takeoff module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_dwg_takeoff",
    version="1.0.0",
    display_name="DWG Takeoff",
    description="2D DWG/DXF drawing viewer with measurements, annotations, and BOQ linking",
    author="OpenEstimate Core Team",
    category="extension",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
)
