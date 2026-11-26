# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the users module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.users",
    entities=(
        Entity("User", label="data_paths.entity.user"),
        Entity("APIKey", label="data_paths.entity.api_key"),
        Entity("UserSession", label="data_paths.entity.user_session"),
    ),
    outputs=(
        DataPath("oe_approval_routes", "Route", via="Route.created_by", label="data_paths.entity.route"),
        DataPath("oe_boq", "BOQActivityLog", via="BOQActivityLog.user_id", label="data_paths.entity.boq_activity_log"),
        DataPath(
            "oe_carbon",
            "SustainabilityReport",
            via="SustainabilityReport.generated_by",
            label="data_paths.entity.sustainability_report",
        ),
        DataPath("oe_cases", "UserCase", via="UserCase.owner_id", label="data_paths.entity.user_case"),
        DataPath(
            "oe_changeorders",
            "ChangeOrderApproval",
            via="ChangeOrderApproval.approver_user_id",
            label="data_paths.entity.change_order_approval",
        ),
        DataPath("oe_collaboration", "Comment", via="Comment.author_id", label="data_paths.entity.comment"),
    ),
)
