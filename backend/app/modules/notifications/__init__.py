# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""oe_notifications - in-app notification system with i18n keys and per-user preferences."""


async def on_startup() -> None:
    """Module startup hook - wire cross-module event subscribers + dispatchers.

    Three things happen on boot:

    1. ``register_notification_subscribers()`` wires every cross-module
       mutation event (rfi.assigned, boq.boq.created, …) into the
       in-app notification service.

    2. ``register_dispatchers()`` (Epic B / B2) attaches the real email
       + webhook sinks to ``notifications.dispatch.email`` and
       ``notifications.dispatch.webhook`` - pre-Epic-B these channels
       silently dropped because nothing subscribed.

    3. Declares the in-process worker (digest flush every 5 minutes,
       cleanup every 24 hours) as the ``notification_worker`` registry
       process; startup boots it.
    """
    from app.core.processes import process_registry
    from app.core.processes.builtin import register_notification_worker
    from app.modules.notifications.dispatcher import register_dispatchers
    from app.modules.notifications.events import register_notification_subscribers
    from app.modules.notifications.permissions import register_notification_permissions

    register_notification_permissions()
    register_notification_subscribers()
    register_dispatchers()
    register_notification_worker(process_registry)
