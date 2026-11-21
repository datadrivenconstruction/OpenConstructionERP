# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Approval Workflows (W8) module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.file_approvals.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_file_approvals",
    version="1.0.0",
    display_name="File Approvals",
    description=(
        "Multi-step approval workflows for project files with stamp "
        "burning on final approval. PDFs are overlay-stamped via pypdf "
        "when available; non-PDFs (and the no-pypdf fallback) get a "
        "JSON sidecar describing the stamp position + text + approver."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
