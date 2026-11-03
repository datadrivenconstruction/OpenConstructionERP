# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data feeds: read-only flat tables over business data for spreadsheets and BI tools.

The module owns no tables. Every feed comes from the explicit allow-list in
:mod:`app.modules.bi_feed.feeds`; the file endpoints and the optional PostgreSQL
views are generated from that one list.
"""


async def on_startup() -> None:
    """Register the module's validation rules (idempotent)."""
    from app.modules.bi_feed.validators import register_bi_feed_rules

    register_bi_feed_rules()
