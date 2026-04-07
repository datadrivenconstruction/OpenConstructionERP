"""Comments & Viewpoints module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_collaboration",
    version="0.1.0",
    display_name="Comments & Viewpoints",
    description="Threaded comments with @mentions and viewpoints for any entity",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
)
