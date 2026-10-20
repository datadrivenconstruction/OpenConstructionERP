# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File full-text search module manifest."""

from app.core.module_loader import InferenceDeclaration, InferenceRole, ModuleManifest

manifest = ModuleManifest(
    name="oe_file_search",
    version="0.1.0",
    display_name="File Search",
    description=(
        "OCR-backed full-text content search across project documents, "
        "sheets, markups and reports. PDFium + Tesseract extractors, "
        "Postgres tsvector / SQLite LIKE fallback."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_documents"],
    auto_install=True,
    enabled=True,
    inference=InferenceDeclaration(
        role=InferenceRole.CALLS_MODEL,
        what="Characters in a scanned page or an image into text, so a document with no embedded text is searchable",
        basis=(
            "Tesseract runs locally in extractors.py and nothing leaves the host. Declared as a "
            "model call rather than as rule-based because the engine is a trained recogniser and "
            "not a template matcher, which is the honest reading even though the embedded-text "
            "path beside it is ordinary parsing"
        ),
    ),
)
