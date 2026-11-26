# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the cost_benchmarks module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.cost_benchmarks",
    entities=(
        Entity("BenchmarkRecord", label="data_paths.entity.benchmark_record"),
        Entity("BenchmarkElement", label="data_paths.entity.benchmark_element"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of boq, fx, price_index",
)
