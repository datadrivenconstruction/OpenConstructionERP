# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the signing module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.signing",
    entities=(
        Entity("SigningSession", label="data_paths.entity.signing_session"),
        Entity("Signature", label="data_paths.entity.signature"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of credentials",
)
