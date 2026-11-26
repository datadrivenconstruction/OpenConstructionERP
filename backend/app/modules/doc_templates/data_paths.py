# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the doc_templates module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.doc_templates",
    entities=(
        Entity("DocTemplateIssue", label="data_paths.entity.doc_template_issue"),
        Entity("DocClause", label="data_paths.entity.doc_clause"),
        Entity("DocLayout", label="data_paths.entity.doc_layout"),
        Entity("DocTemplate", label="data_paths.entity.doc_template"),
    ),
    reason="No foreign key joins its tables to another module's tables; reads code of changeorders, contracts, finance, letter_templates, meetings, offers and 4 more",
)
