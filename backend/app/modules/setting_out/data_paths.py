# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the setting_out module (see app.core.data_paths)."""

from app.core.data_paths import Chip, DataPath, DataPaths, Duty, Entity, External, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.setting_out",
    roles=("surveyor", "site_manager", "inspector"),
    duties=(
        Duty("surveyor", "data_paths.duty.setting_out.surveyor"),
        Duty("site_manager", "data_paths.duty.setting_out.site_manager"),
        Duty("inspector", "data_paths.duty.setting_out.inspector"),
    ),
    external=(External("file", "data_paths.external.design_files"),),
    chips=(Chip("SettingOutRecord", "data_paths.chip.stake_failed", (Where("verdict", "eq", "fail"),), "error"),),
    entities=(
        Entity("SettingOutRequest", label="data_paths.entity.setting_out_request", route="/survey/setting-out"),
        Entity("SettingOutPoint", label="data_paths.entity.stake_point", route="/survey/setting-out"),
        Entity("SettingOutRecord", label="data_paths.entity.as_staked", route="/survey/setting-out"),
    ),
    inputs=(
        DataPath(
            "oe_survey_core",
            "SettingOutRequest",
            via="SettingOutRequest.control_ref",
            label="data_paths.entity.control_point",
            route="/survey/points",
            importance="high",
            breaks="data_paths.breaks.no_control",
            where=(Where("control_ref", "ne", ""),),
        ),
        DataPath(
            "oe_boq",
            "SettingOutRequest",
            via="SettingOutRequest.element_ref_id",
            label="data_paths.entity.position",
            route="/boq",
            where=(Where("element_ref_type", "eq", "boq"),),
        ),
    ),
    outputs=(
        DataPath(
            "oe_ncr",
            "SettingOutRecord",
            via="SettingOutRecord.ncr_id",
            label="data_paths.entity.ncr",
            route="/ncr",
            importance="high",
            breaks="data_paths.breaks.no_defect_trail",
            where=(Where("ncr_id", "not_null"),),
        ),
    ),
)
