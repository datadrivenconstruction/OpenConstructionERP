# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the field_diary module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.field_diary",
    entities=(
        Entity("DiaryEntry", label="data_paths.entity.diary_entry"),
        Entity("FieldMagicLink", label="data_paths.entity.field_magic_link"),
        Entity("FieldModuleGrant", label="data_paths.entity.field_module_grant"),
        Entity("FieldSession", label="data_paths.entity.field_session"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes field_diary.entry.submitted, field_diary.grant.created; reads code of documents, fieldreports, haul_tickets, inspections, ncr, punchlist and 3 more",
)
