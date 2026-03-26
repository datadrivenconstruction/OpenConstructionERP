"""CAD import/conversion module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_cad",
    version="0.1.0",
    display_name="CAD Import",
    description="CAD file import and conversion pipeline (DWG, DGN, RVT, IFC)",
    author="OpenEstimate Core Team",
    category="extension",
    depends=["oe_projects"],
    auto_install=False,
    enabled=True,
)
