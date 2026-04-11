"""oe_notifications — in-app notification system with i18n keys and per-user preferences."""


async def on_startup() -> None:
    """Module startup hook — wire cross-module event subscribers.

    Without this the notifications module is a passive store: routes
    work, but no upstream module ever calls ``create_notification()``
    so the table stays empty.  The subscriber framework consumes a
    curated set of mutation events from boq / meetings / cde / bim_hub
    and turns them into per-user notifications.  See ``events.py``
    for the full list.
    """
    from app.modules.notifications.events import register_notification_subscribers

    register_notification_subscribers()
