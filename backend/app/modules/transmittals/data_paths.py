# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the transmittals module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.transmittals",
    entities=(
        Entity("Transmittal", label="data_paths.entity.transmittal"),
        Entity("TransmittalItem", label="data_paths.entity.transmittal_item"),
        Entity("TransmittalRecipient", label="data_paths.entity.transmittal_recipient"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes transmittal.acknowledged, transmittal.issued, transmittal.responded; reads code of project_governance, rfi",
)
