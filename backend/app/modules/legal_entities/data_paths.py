# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the legal_entities module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.legal_entities",
    entities=(
        Entity("LegalEntity", label="data_paths.entity.legal_entity"),
        Entity("Branch", label="data_paths.entity.branch"),
        Entity("LegalEntityMember", label="data_paths.entity.legal_entity_member"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of finance",
)
