# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File References module manifest.

Two surfaces:

* ISO 19650 naming validation - per-file violation rows with an
  acknowledge workflow.
* Generic cross-entity references - link a file to an RFI / Issue /
  Task / Submittal / Punch-list item.
"""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_file_references",
    version="1.0.0",
    display_name="File References",
    description=(
        "ISO 19650 filename validation + generic cross-entity references "
        "linking files to RFIs, issues, tasks, and submittals."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
)
