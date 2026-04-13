"""Project Intelligence module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_project_intelligence",
    version="1.0.0",
    display_name="Project Intelligence",
    description="AI-powered project completion analysis, scoring, and guided recommendations",
    author="OpenEstimate Core Team",
    category="intelligence",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
)
