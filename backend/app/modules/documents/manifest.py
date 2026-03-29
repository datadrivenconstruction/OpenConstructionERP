"""Document Management module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_documents",
    version="0.1.0",
    display_name="Document Management",
    description="Upload, categorize, and manage project documents with tagging and search",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
)
