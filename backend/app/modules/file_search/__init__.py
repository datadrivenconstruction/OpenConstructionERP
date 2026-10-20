# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File full-text search module (W3).

OCR-extracted content index over every file kind in the file manager
(documents, sheets, markups, takeoffs, reports). Wraps two extractors:

* pypdfium2 (PDFium, via :mod:`app.core.pdf_reader`) - pulls embedded
  vector text out of PDFs at zero pixel-rendering cost. Used as the primary extractor for ``.pdf``.
* pytesseract - falls back to OCR for image-only pages (scanned PDFs,
  photos, markup raster overlays). Slow; only invoked when the PDF
  reports zero embedded text.

Both extractors are optional dependencies. If neither library is
installed, ``extract_text`` returns ``""`` and the row carries
``ocr_engine = 'none'``. The endpoint never crashes - the file is still
indexed by canonical name (``mode=filename`` still works).

Search itself uses ``tsvector`` on PostgreSQL (generated column over
``content_text``) and a ``LIKE`` fallback on SQLite, so the same code
runs in CI (SQLite) and prod (Postgres) with no branching at the
endpoint surface.
"""


async def on_startup() -> None:
    """Module startup hook - register RBAC permissions."""
    from app.modules.file_search.permissions import register_file_search_permissions

    register_file_search_permissions()
