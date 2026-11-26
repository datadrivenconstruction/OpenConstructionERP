# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the claims_evidence module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (assembles a deterministic, ordered evidence pack for a claim or dispute from a project's cross-module activity timeline and its change-family records. The pack is content-addressable, so two parties can independently reproduce and verify it. Assembled on demand with no tables of its own and no migration); reads code of change_intelligence, changeorders, moc, reconciliation, rfi, timeline and 1 more",
)
