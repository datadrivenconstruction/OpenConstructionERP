# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the letter_templates module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.letter_templates",
    entities=(Entity("LetterTemplateOverride", label="data_paths.entity.letter_template_override"),),
    reason="No foreign key joins its tables to another module's tables; reads code of doc_templates, tendering",
)
