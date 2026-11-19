# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the takeoff module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Param

DATA_PATHS = DataPaths(
    why="data_paths.why.takeoff",
    roles=(
        "estimator",
        "quantity_surveyor",
    ),
    entities=(
        Entity("TakeoffDocument", label="data_paths.entity.takeoff_document", route="/takeoff"),
        Entity("TakeoffMeasurement", label="data_paths.entity.measurement", route="/takeoff"),
    ),
    inputs=(
        DataPath(
            "oe_documents",
            "TakeoffDocument",
            via="TakeoffDocument.source_document_id",
            label="data_paths.entity.document",
            route="/files",
        ),
        DataPath(
            "oe_bim_hub",
            "CadExtractionSession",
            via="CadExtractionSession.bim_model_id",
            label="data_paths.entity.bim_link",
            route="/bim",
        ),
    ),
    outputs=(
        DataPath(
            "oe_boq",
            "TakeoffMeasurement",
            via="TakeoffMeasurement.linked_boq_position_id",
            label="data_paths.entity.position",
            route="/boq",
            importance="high",
            breaks="data_paths.breaks.no_quantities",
        ),
    ),
    parameters=(
        Param(
            "TakeoffMeasurement.scale_pixels_per_unit",
            drives=(
                "TakeoffMeasurement.measurement_value",
                "oe_boq.Position.quantity",
            ),
            label="data_paths.param.scale",
        ),
    ),
)
