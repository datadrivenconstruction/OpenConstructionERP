# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Retrieval module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.retrieval.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_retrieval",
    version="0.2.0",
    display_name="Find Records",
    description=(
        "Claim-grade retrieval across the project record. Search documents, correspondence, and "
        "change orders together, filtered by party, date window, reference and type, ranked with "
        "the provenance you need to reconstruct what happened, and pin the searches worth "
        "coming back to"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_documents", "oe_correspondence", "oe_changeorders"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
