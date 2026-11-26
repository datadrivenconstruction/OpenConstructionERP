# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the notifications module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.notifications",
    entities=(
        Entity("Notification", label="data_paths.entity.notification"),
        Entity("NotificationDigestQueue", label="data_paths.entity.notification_digest_queue"),
        Entity("NotificationPreference", label="data_paths.entity.notification_preference"),
        Entity("WebhookTarget", label="data_paths.entity.webhook_target"),
    ),
    reason="No foreign key joins its tables to another module's tables; subscribes to collaboration.comment.created; publishes bid_management.bid_package.created_from_opportunity, contracts.contract.drafted_from_bid_award, notifications.notification.bulk_read, notifications.notification.created, notifications.notification.deleted, notifications.notification.read; reads code of bid_management, carbon, changeorders, collaboration, collaboration_locks, contracts and 13 more",
)
