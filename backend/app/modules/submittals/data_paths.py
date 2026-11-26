# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the submittals module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.submittals",
    entities=(Entity("Submittal", label="data_paths.entity.submittal"),),
    reason="No foreign key joins its tables to another module's tables; subscribes to approval_routes.instance.completed, approval_routes.instance.rejected, submittal.approved, submittal.created, submittal.deleted, submittal.reviewed and 2 more; publishes submittal.approved, submittal.created, submittal.deleted, submittal.rejected, submittal.reviewed, submittal.revise_resubmit and 2 more; reads code of approval_routes, documents, rfi",
)
