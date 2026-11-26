# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the search module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (cross-collection vector search - fans out to BOQ, documents, tasks, risks, BIM elements and chat history, then merges the results via Reciprocal Rank Fusion); reads code of boq, changeorders, correspondence, costs, documents, moc and 6 more",
)
