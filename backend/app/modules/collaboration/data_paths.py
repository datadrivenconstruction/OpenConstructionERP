# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the collaboration module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.collaboration",
    entities=(
        Entity("Comment", label="data_paths.entity.comment"),
        Entity("CommentMention", label="data_paths.entity.comment_mention"),
        Entity("Viewpoint", label="data_paths.entity.viewpoint"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes collaboration.comment.created; reads code of bcf, bim_hub, boq, documents, inspections, meetings and 9 more",
)
