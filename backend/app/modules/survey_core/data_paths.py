# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the survey_core module (see app.core.data_paths)."""

from app.core.data_paths import Chip, DataPath, DataPaths, Duty, Entity, External, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.survey_core",
    roles=("surveyor", "engineer", "site_manager"),
    duties=(
        Duty("surveyor", "data_paths.duty.survey_core.surveyor"),
        Duty("engineer", "data_paths.duty.survey_core.engineer"),
        Duty("site_manager", "data_paths.duty.survey_core.site_manager"),
    ),
    external=(
        External("party", "data_paths.external.surveyor", role="surveyor"),
        External("file", "data_paths.external.instrument_files"),
    ),
    chips=(Chip("SurveyTraverse", "data_paths.chip.traverse_failed", (Where("verdict", "eq", "fail"),), "error"),),
    entities=(
        Entity("SurveyPoint", label="data_paths.entity.survey_point", route="/survey/points"),
        Entity("SurveyPointSet", label="data_paths.entity.point_set", route="/survey/points"),
        Entity("SurveyTraverse", label="data_paths.entity.traverse", route="/survey/calc"),
    ),
    outputs=(
        DataPath(
            "oe_surfaces_volumes",
            "SurveySurface",
            via="SurveySurface.point_set_id",
            label="data_paths.entity.surface",
            route="/survey/volumes",
            importance="critical",
            breaks="data_paths.breaks.no_ground_model",
        ),
        DataPath(
            "oe_setting_out",
            "SettingOutRequest",
            via="SettingOutRequest.control_ref",
            label="data_paths.entity.setting_out_request",
            route="/survey/setting-out",
            importance="high",
            breaks="data_paths.breaks.no_control",
            where=(Where("control_ref", "ne", ""),),
        ),
    ),
)
