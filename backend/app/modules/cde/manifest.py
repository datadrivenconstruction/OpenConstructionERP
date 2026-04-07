"""CDE module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_cde",
    version="0.1.0",
    display_name="Common Data Environment (ISO 19650)",
    description="ISO 19650 compliant Common Data Environment — document containers, revisions, state transitions, and suitability codes",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_documents"],
    auto_install=True,
    enabled=True,
)
