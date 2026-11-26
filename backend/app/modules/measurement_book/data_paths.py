# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the measurement_book module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.measurement_book",
    entities=(Entity("MeasurementBookEntry", label="data_paths.entity.measurement_book_entry"),),
    inputs=(
        DataPath(
            "oe_boq",
            "MeasurementBookEntry",
            via="MeasurementBookEntry.boq_position_id",
            label="data_paths.entity.position",
        ),
    ),
)
