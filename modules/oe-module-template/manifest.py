"""Module template manifest.

Copy this directory and customize for your module.
Rename the directory to your module name (e.g., oe_my_module → my_module).
"""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_template",
    version="0.1.0",
    display_name="Module Template",
    description="Template for creating new OpenEstimate modules",
    author="Your Name",
    category="community",  # core, integration, regional, community
    depends=[],  # e.g., ["oe_projects", "oe_boq"]
    auto_install=False,
    enabled=True,
)
