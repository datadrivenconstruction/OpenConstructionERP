# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Resumable Uploads module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_resumable_uploads",
    version="1.0.0",
    display_name="Resumable Uploads",
    description=(
        "Chunked, resumable uploads for large CAD and PDF files. A session "
        "tracks received chunks so an interrupted upload resumes instead of "
        "restarting. On completion chunks are assembled and handed to the "
        "existing document store and conversion pipeline."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users", "oe_documents"],
    auto_install=True,
    enabled=True,
)
