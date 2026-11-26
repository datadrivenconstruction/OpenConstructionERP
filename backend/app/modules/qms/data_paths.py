# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the qms module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.qms",
    entities=(
        Entity("ITPPlan", label="data_paths.entity.itp_plan"),
        Entity("QMSAudit", label="data_paths.entity.qms_audit"),
        Entity("QMSCalibration", label="data_paths.entity.qms_calibration"),
        Entity("QMSNCR", label="data_paths.entity.qmsncr"),
    ),
    reason="No foreign key joins its tables to another module's tables; subscribes to hse.capa.completed, hse.capa.root_cause_recorded; publishes bi_dashboards.kpi_recompute, notifications.dispatch, procurement.supplier_rating_update, qms.audit.completed, qms.audit.linked_to_subcontractor, qms.calibration.expiring and 10 more; reads code of approval_routes, hse_advanced, punchlist, variations",
)
