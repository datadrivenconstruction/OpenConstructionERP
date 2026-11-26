# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the guarantees module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.guarantees",
    entities=(
        Entity("Guarantee", label="data_paths.entity.guarantee"),
        Entity("GuaranteeFacility", label="data_paths.entity.guarantee_facility"),
        Entity("GuaranteeDocument", label="data_paths.entity.guarantee_document"),
        Entity("GuaranteeEvent", label="data_paths.entity.guarantee_event"),
    ),
    reason="No foreign key joins its tables to another module's tables; subscribes to contracts.claim.certified, tendering.package.awarded; publishes created, expiring, reduced, status_changed, updated; reads code of contracts, documents, finance, notifications, tendering",
)
