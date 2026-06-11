"""‌⁠‍Project Intelligence module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_project_intelligence",
    version="1.0.0",
    display_name="Project Intelligence",
    description="AI-powered project completion analysis, scoring, and guided recommendations",
    author="OpenConstructionERP Core Team",
    # Promoted to "core" so the dashboard at /project-intelligence is always
    # available. Core modules ignore persisted-disable state at boot and cannot
    # be turned off via the /v1/modules/{name}/disable endpoint.
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
)
