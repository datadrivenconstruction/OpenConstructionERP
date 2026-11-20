# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the land_parcels module (see app.core.data_paths)."""

from app.core.data_paths import Chip, DataPath, DataPaths, Duty, Entity, External, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.land_parcels",
    roles=("surveyor", "project_manager", "authority"),
    duties=(
        Duty("surveyor", "data_paths.duty.land_parcels.surveyor"),
        Duty("project_manager", "data_paths.duty.land_parcels.project_manager"),
        Duty("authority", "data_paths.duty.land_parcels.authority"),
    ),
    external=(
        External("party", "data_paths.external.land_registry", role="authority"),
        External("file", "data_paths.external.cadastre_files"),
    ),
    chips=(
        Chip(
            "LandParcel",
            "data_paths.chip.parcel_not_acquired",
            (Where("status", "in", ("needed", "negotiating", "expropriation")),),
            "warning",
        ),
    ),
    entities=(
        Entity("LandParcel", label="data_paths.entity.parcel", route="/survey/parcels"),
        Entity("LandRight", label="data_paths.entity.land_right", route="/survey/parcels"),
        Entity("LandWorkZone", label="data_paths.entity.work_zone", route="/survey/parcels"),
    ),
    outputs=(
        DataPath(
            "oe_boq",
            "LandParcel",
            via="LandParcel.boq_position_id",
            label="data_paths.entity.position",
            route="/boq",
            importance="high",
            breaks="data_paths.breaks.no_land_cost",
            where=(Where("boq_position_id", "not_null"),),
        ),
    ),
)
