"""‌⁠‍oe_notifications — in-app notification system with i18n keys and per-user preferences."""


async def on_startup() -> None:
    """‌⁠‍Module startup hook — wire cross-module event subscribers + dispatchers.

    Three things happen on boot:

    1. ``register_notification_subscribers()`` wires every cross-module
       mutation event (rfi.assigned, boq.boq.created, …) into the
       in-app notification service.

    2. ``register_dispatchers()`` (Epic B / B2) attaches the real email
       + webhook sinks to ``notifications.dispatch.email`` and
       ``notifications.dispatch.webhook`` — pre-Epic-B these channels
       silently dropped because nothing subscribed.

    3. ``start_scheduler()`` (Epic B / B4-B5) starts the in-process
       periodic worker that flushes the digest queue every 5 minutes
       and cleans up aged notifications every 24 hours.
    """
    from app.modules.notifications.dispatcher import register_dispatchers
    from app.modules.notifications.events import register_notification_subscribers
    from app.modules.notifications.notification_worker import start_scheduler

    register_notification_subscribers()
    register_dispatchers()
    try:
        start_scheduler()
    except Exception:  # noqa: BLE001 — worker is best-effort
        import logging

        logging.getLogger(__name__).debug(
            "notifications: scheduler failed to start",
            exc_info=True,
        )
