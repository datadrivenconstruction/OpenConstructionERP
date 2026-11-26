# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the bi_dashboards module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.bi_dashboards",
    entities=(
        Entity("Dashboard", label="data_paths.entity.dashboard"),
        Entity("KPIDefinition", label="data_paths.entity.kpi_definition"),
        Entity("KPIValue", label="data_paths.entity.kpi_value"),
        Entity("ReportDefinition", label="data_paths.entity.report_definition"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes bi.alert.triggered, bi.dashboard.evaluated, bi.dashboard.viewed, bi.filter.shared, bi.kpi.definition_created, bi.kpi.definition_deleted and 3 more; reads code of bid_management, boq, carbon, changeorders, costmodel, costs and 19 more",
)
