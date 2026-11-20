# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the mine_survey module (see app.core.data_paths)."""

from app.core.data_paths import Chip, DataPath, DataPaths, Duty, Entity, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.mine_survey",
    roles=("surveyor", "quantity_surveyor", "site_manager"),
    duties=(
        Duty("surveyor", "data_paths.duty.mine_survey.surveyor"),
        Duty("quantity_surveyor", "data_paths.duty.mine_survey.quantity_surveyor"),
        Duty("site_manager", "data_paths.duty.mine_survey.site_manager"),
    ),
    chips=(
        Chip(
            "MinePeriodEntry",
            "data_paths.chip.not_on_claim",
            (Where("actual_volume_id", "not_null"), Where("claim_entry_id", "is_null")),
            "info",
        ),
    ),
    entities=(
        Entity("MineUnit", label="data_paths.entity.mine_unit", route="/survey/mine"),
        Entity("MinePeriod", label="data_paths.entity.mine_period", route="/survey/mine"),
        Entity("MinePeriodEntry", label="data_paths.entity.mine_period_entry", route="/survey/mine"),
    ),
    inputs=(
        DataPath(
            "oe_surfaces_volumes",
            "MinePeriodEntry",
            via="MinePeriodEntry.actual_volume_id",
            label="data_paths.entity.volume",
            route="/survey/volumes",
            importance="critical",
            breaks="data_paths.breaks.no_measured_quantity",
        ),
    ),
    outputs=(
        DataPath(
            "oe_progress",
            "MinePeriodEntry",
            via="MinePeriodEntry.claim_entry_id",
            label="data_paths.entity.progress_entry",
            importance="high",
            breaks="data_paths.breaks.not_paid",
            where=(Where("claim_entry_id", "not_null"),),
        ),
    ),
)
