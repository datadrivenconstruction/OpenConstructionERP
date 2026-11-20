# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the surfaces_volumes module (see app.core.data_paths)."""

from app.core.data_paths import Chip, DataPath, DataPaths, Duty, Entity, External, Sum, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.surfaces_volumes",
    roles=("surveyor", "quantity_surveyor", "site_manager"),
    duties=(
        Duty("surveyor", "data_paths.duty.surfaces_volumes.surveyor"),
        Duty("quantity_surveyor", "data_paths.duty.surfaces_volumes.quantity_surveyor"),
        Duty("site_manager", "data_paths.duty.surfaces_volumes.site_manager"),
    ),
    external=(External("file", "data_paths.external.landxml"),),
    chips=(Chip("SurveyVolume", "data_paths.chip.volume_unconfirmed", (Where("status", "eq", "draft"),), "warning"),),
    entities=(
        Entity("SurveySurface", label="data_paths.entity.surface", route="/survey/volumes"),
        Entity("SurveyVolume", label="data_paths.entity.volume", route="/survey/volumes"),
        Entity(
            "SurveyVolume",
            label="data_paths.entity.confirmed_volume",
            route="/survey/volumes",
            where=(Where("status", "eq", "confirmed"),),
        ),
    ),
    inputs=(
        DataPath(
            "oe_survey_core",
            "SurveySurface",
            via="SurveySurface.point_set_id",
            label="data_paths.entity.point_set",
            route="/survey/points",
            importance="critical",
            breaks="data_paths.breaks.no_ground_model",
        ),
    ),
    outputs=(
        DataPath(
            "oe_boq",
            "SurveyVolume",
            via="SurveyVolume.boq_position_id",
            label="data_paths.entity.position",
            route="/boq",
            measure=Sum("cut_m3"),
            importance="high",
            breaks="data_paths.breaks.no_measured_quantity",
            where=(Where("boq_position_id", "not_null"),),
        ),
        DataPath(
            "oe_stockpiles",
            "Stockpile",
            via="Stockpile.base_surface_id",
            label="data_paths.entity.stockpile",
            route="/survey/stockpiles",
        ),
        DataPath(
            "oe_mine_survey",
            "MinePeriodEntry",
            via="MinePeriodEntry.actual_volume_id",
            label="data_paths.entity.mine_period_entry",
            route="/survey/mine",
        ),
    ),
)
