"""Takeoff module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_takeoff",
    version="0.1.0",
    display_name="Quantity Takeoff",
    description="Manual and AI-assisted quantity takeoff from drawings and models",
    author="OpenEstimate Core Team",
    category="extension",
    depends=["oe_projects", "oe_cad"],
    auto_install=False,
    enabled=True,
)
