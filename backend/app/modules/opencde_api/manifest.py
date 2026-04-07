"""OpenCDE API module manifest.

Exposes project data in BuildingSMART-compliant OpenCDE Foundation API 1.1
and BCF API 3.0 format for interoperability with external BIM tools.
"""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_opencde_api",
    version="0.1.0",
    display_name="OpenCDE API",
    description="BuildingSMART OpenCDE Foundation API 1.1 + BCF API 3.0 compliance layer",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_collaboration"],
    optional_depends=["oe_documents"],
    auto_install=True,
    enabled=True,
)
