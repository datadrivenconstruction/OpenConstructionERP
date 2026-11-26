# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the inbound_capture module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (captures correspondence that reaches a project from outside the app - a forwarded email, a chat / generic webhook, an SMS gateway - normalises each ad-hoc payload to one canonical message shape via the pure inbound normalizer, and persists it as an incoming correspondence record. Capture is idempotent on the provider's own message id, so a retried delivery never doubles up, and provider webhooks are authenticated through a per-provider signature-verification seam); publishes correspondence.created; reads code of correspondence",
)
