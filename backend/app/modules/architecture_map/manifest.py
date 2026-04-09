"""Architecture Map module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_architecture_map",
    version="1.0.0",
    display_name="Architecture Map",
    description="Interactive visual map of system architecture",
    author="OpenEstimate Core Team",
    category="developer_tools",
    depends=[],
    auto_install=True,
)
