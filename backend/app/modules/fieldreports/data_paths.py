# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the fieldreports module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.fieldreports",
    entities=(
        Entity("FieldReport", label="data_paths.entity.field_report"),
        Entity("FieldReportTemplate", label="data_paths.entity.field_report_template"),
        Entity("SiteEquipmentLog", label="data_paths.entity.site_equipment_log"),
        Entity("SiteWorkforceLog", label="data_paths.entity.site_workforce_log"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes fieldreports.report.submitted; reads code of documents",
)
