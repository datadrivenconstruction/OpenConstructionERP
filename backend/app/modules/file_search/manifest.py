# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File full-text search module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_file_search",
    version="0.1.0",
    display_name="File Search",
    description=(
        "OCR-backed full-text content search across project documents, "
        "sheets, markups and reports. PyMuPDF + Tesseract extractors, "
        "Postgres tsvector / SQLite LIKE fallback."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_documents"],
    auto_install=True,
    enabled=True,
)
