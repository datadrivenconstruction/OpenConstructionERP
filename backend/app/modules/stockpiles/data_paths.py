# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the stockpiles module (see app.core.data_paths)."""

from app.core.data_paths import Chip, DataPath, DataPaths, Duty, Entity, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.stockpiles",
    roles=("surveyor", "site_manager", "accountant"),
    duties=(
        Duty("surveyor", "data_paths.duty.stockpiles.surveyor"),
        Duty("site_manager", "data_paths.duty.stockpiles.site_manager"),
        Duty("accountant", "data_paths.duty.stockpiles.accountant"),
    ),
    chips=(
        Chip(
            "StockpileAdjustment",
            "data_paths.chip.adjustment_proposed",
            (Where("status", "eq", "proposed"),),
            "warning",
        ),
    ),
    entities=(
        Entity("Stockpile", label="data_paths.entity.stockpile", route="/survey/stockpiles"),
        Entity("StockpileSurvey", label="data_paths.entity.stockpile_survey", route="/survey/stockpiles"),
        Entity("StockpileAdjustment", label="data_paths.entity.stock_adjustment", route="/survey/stockpiles"),
    ),
    inputs=(
        DataPath(
            "oe_surfaces_volumes",
            "StockpileSurvey",
            via="StockpileSurvey.pile_surface_id",
            label="data_paths.entity.surface",
            route="/survey/volumes",
            importance="critical",
            breaks="data_paths.breaks.no_pile_volume",
        ),
    ),
    outputs=(
        DataPath(
            "oe_site_inventory",
            "StockpileAdjustment",
            via="StockpileAdjustment.movement_id",
            label="data_paths.entity.stock_movement",
            importance="high",
            breaks="data_paths.breaks.book_stock_wrong",
            where=(Where("movement_id", "not_null"),),
        ),
    ),
)
