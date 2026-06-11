"""‌⁠‍Markups & Annotations module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_markups",
    version="0.1.0",
    display_name="Markups & Annotations",
    description="Drawing markups, scale calibration, and stamp templates for document annotation",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
)
