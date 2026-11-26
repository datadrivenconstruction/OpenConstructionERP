# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the commitment_release module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.commitment_release",
    entities=(
        Entity("AbortScenario", label="data_paths.entity.abort_scenario"),
        Entity("AuthorityAssignment", label="data_paths.entity.authority_assignment"),
        Entity("CommitmentItem", label="data_paths.entity.commitment_item"),
        Entity("CommitmentMatrix", label="data_paths.entity.commitment_matrix"),
    ),
    reason="No foreign key joins its tables to another module's tables; subscribes to approval_routes.instance.cancelled, approval_routes.instance.completed, approval_routes.instance.rejected, contracts.contract.drafted_from_bid_award; publishes commitment_release.item.aborted, commitment_release.item.created, commitment_release.item.decision_overdue, commitment_release.item.re_release_required, commitment_release.item.transferred, commitment_release.matrix.set and 4 more; reads code of approval_routes, bid_management, boq, changeorders, contracts, costmodel and 12 more",
)
