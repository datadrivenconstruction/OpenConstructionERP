# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the i18n_foundation module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Duty, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.i18n_foundation",
    roles=(
        "accountant",
        "planner",
    ),
    duties=(
        Duty("accountant", "data_paths.duty.i18n_foundation.accountant"),
        Duty("planner", "data_paths.duty.i18n_foundation.planner"),
    ),
    entities=(
        Entity("ExchangeRate", label="data_paths.entity.exchange_rate"),
        Entity("WorkCalendar", label="data_paths.entity.work_calendar"),
        Entity("TaxConfiguration", label="data_paths.entity.tax_configuration"),
    ),
)
