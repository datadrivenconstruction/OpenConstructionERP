# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the reporting module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.reporting",
    entities=(
        Entity("GeneratedReport", label="data_paths.entity.generated_report"),
        Entity("KPISnapshot", label="data_paths.entity.kpi_snapshot"),
        Entity("ReportTemplate", label="data_paths.entity.report_template"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes reporting.kpi_snapshot.created, reporting.report.generated, reporting.template.created, reporting.template.scheduled; reads code of ai_agents, bim_hub, boq, contacts, costmodel, dashboard and 9 more",
)
