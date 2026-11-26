# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the erp_chat module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.erp_chat",
    entities=(
        Entity("ChatSession", label="data_paths.entity.chat_session"),
        Entity("ChatAction", label="data_paths.entity.chat_action"),
        Entity("ChatMessage", label="data_paths.entity.chat_message"),
        Entity("ChatTurnFeedback", label="data_paths.entity.chat_turn_feedback"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes erp_chat.message.created; reads code of ai, boq, costs, punchlist, rfi, risk and 4 more",
)
