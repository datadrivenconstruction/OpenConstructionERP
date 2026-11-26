# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the meetings module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.meetings",
    entities=(
        Entity("Meeting", label="data_paths.entity.meeting"),
        Entity("MeetingGlossaryTerm", label="data_paths.entity.meeting_glossary_term"),
        Entity("MeetingActionItem", label="data_paths.entity.meeting_action_item"),
        Entity("MeetingMinutes", label="data_paths.entity.meeting_minutes"),
    ),
    reason="No foreign key joins its tables to another module's tables; publishes meeting.action_items_created; reads code of ai, ai_agents, boq, contacts, documents, notifications and 5 more",
)
