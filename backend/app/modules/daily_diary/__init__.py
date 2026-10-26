# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Daily Site Diary module.

Legally significant daily site diary that aggregates weather snapshots,
visitor/delivery/event/completion entries, photo + video timelines,
drone surveys, reality-capture datasets, and an immutable signed archive
(SHA-256 content hash + signature payload).

Subscriber stubs for upstream auto-populate from HSE/Procurement/
Quality/Schedule are out of scope of the initial backend; the service
exposes ``auto_populate_entries_from_module_events`` as a pure helper
ready to plug into a subscriber.
"""


async def on_startup() -> None:
    """Module startup hook - register RBAC permissions + cross-module wiring."""
    from app.modules.daily_diary.events import register_subscribers
    from app.modules.daily_diary.permissions import register_daily_diary_permissions

    register_daily_diary_permissions()
    register_subscribers()

    from app.modules.daily_diary.clock_headcount import register_clock_headcount

    register_clock_headcount()
