# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the project_handbook module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.project_handbook",
    entities=(
        Entity("Handbook", label="data_paths.entity.handbook"),
        Entity("HandbookChapter", label="data_paths.entity.handbook_chapter"),
        Entity("HandbookChapterVersion", label="data_paths.entity.handbook_chapter_version"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes chapter.approved, chapter.submitted; reads code of contacts, documents, engineering_brief, project_governance, staffing, stakeholders",
)
