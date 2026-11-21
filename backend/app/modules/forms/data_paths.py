# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the forms module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.forms",
    roles=(
        "site_manager",
        "inspector",
    ),
    duties=(
        Duty("site_manager", "data_paths.duty.forms.site_manager"),
        Duty("inspector", "data_paths.duty.forms.inspector"),
    ),
    entities=(
        Entity("FormTemplate", label="data_paths.entity.form_template", route="/forms"),
        Entity("FormSubmission", label="data_paths.entity.form_submission", route="/forms"),
    ),
    outputs=(
        DataPath(
            "oe_inspections",
            "FormSubmission",
            via="FormSubmission.linked_inspection_id",
            label="data_paths.entity.inspection",
            where=(Where("linked_inspection_id", "not_null"),),
        ),
    ),
)
