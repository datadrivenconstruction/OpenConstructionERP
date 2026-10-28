# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Resumable Uploads validation surface.

Validation is first-class for this module. The deterministic checks live in
:mod:`app.modules.resumable_uploads.chunking` (chunk-index bounds, per-index
size, assembled-size and SHA-256 integrity) and the magic-byte / extension /
size gate is reused from the existing document upload pipeline at completion
time (``DocumentService.upload_document``), so a resumable upload is held to
exactly the same content rules as a single-shot upload.

This file is the conventional ``validators.py`` entry point: it re-exports
the validation helpers so callers have one obvious place to find them, and
documents which layer enforces what.

Enforced here / via chunking:
    * chunk index must be in ``[0, total_chunks)``                (400)
    * chunk body must be non-empty and exactly the contracted size (400)
    * total_size / chunk_size / total_chunks must be within bounds (400)
    * assembled byte count must equal the declared total_size      (400)
    * client SHA-256, when supplied, must match the assembled file (400)

Enforced at completion by the documents pipeline (reused, not forked):
    * magic-byte signature must match an allowed format            (400)
    * blocked executable / script extensions are rejected          (400)
    * the documents-module size cap is applied                     (413)
"""

from __future__ import annotations

from app.modules.resumable_uploads.chunking import (
    ChunkValidationError,
    compute_total_chunks,
    expected_chunk_size,
    is_complete,
    missing_chunks,
    validate_chunk,
    verify_assembled,
)

__all__ = [
    "ChunkValidationError",
    "compute_total_chunks",
    "expected_chunk_size",
    "is_complete",
    "missing_chunks",
    "validate_chunk",
    "verify_assembled",
]
