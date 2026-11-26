# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the file_distribution module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.file_distribution",
    entities=(
        Entity("FileDistributionList", label="data_paths.entity.file_distribution_list"),
        Entity("FileDistributionSubscription", label="data_paths.entity.file_distribution_subscription"),
        Entity("FileDistributionMember", label="data_paths.entity.file_distribution_member"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of documents, file_search, notifications",
)
