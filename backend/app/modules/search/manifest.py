# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unified semantic search module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.search.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_search",
    version="0.1.0",
    display_name="Semantic Search",
    description=(
        "Cross-collection vector search - fans out to BOQ, documents, "
        "tasks, risks, BIM elements and chat history, then merges the "
        "results via Reciprocal Rank Fusion."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=[],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
