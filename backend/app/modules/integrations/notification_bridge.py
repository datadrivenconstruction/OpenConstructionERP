# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deliver in-app notifications to connected chat connectors (issue #279).

Pre-#279 a user could connect Telegram (or Slack / Teams / Discord /
WhatsApp) on the Integrations page - the credentials were stored in an
:class:`IntegrationConfig` row and a manual "Test" button sent a single
message - but no real platform event ever reached the connector. The
connector was write-only.

This module closes that gap. It subscribes to the
``notifications.notification.created`` event that
:class:`app.modules.notifications.service.NotificationService` publishes for
EVERY notification row, resolves the recipient's ACTIVE connector configs,
and forwards a concise rendered message (title + body) to each connector
whose ``events`` filter matches the notification type.

Design notes:

* **Per-user scoping is already correct.** ``IntegrationConfig`` is keyed by
  ``user_id`` and the ``notification.created`` event carries the recipient
  ``user_id``, so we never have to map project events to users ourselves -
  we simply deliver to the connectors owned by the notified user.

* **Event-filter matching is shared with the webhook sink.** We reuse
  :func:`app.modules.notifications.dispatcher._event_filter_matches` so the
  connector filter behaves exactly like the webhook ``event_filter``
  (``*`` matches all, ``boq.*`` matches the namespace, otherwise exact).
  ``IntegrationConfig.events`` is a JSON list, so we join it into the
  comma-separated form the matcher expects.

* **Failures are isolated per connector.** Each send is wrapped in its own
  try/except; one misbehaving connector never blocks the others or the
  upstream event. The subscriber opens its own short-lived session via
  ``async_session_factory()`` exactly like the notifications wave
  subscribers, so a delivery failure can never roll back the notification
  write.

* **Outbound URLs are re-validated.** The webhook-based channels (Slack,
  Teams, Discord) post to a user-supplied URL, so we run them through the
  same SSRF deny-list (:func:`resolve_and_validate_external_url`) the Test
  buttons use before dispatching.

This module is purely additive: it adds a new event subscriber and does not
change any existing notification dispatch behaviour.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.core.url_safety import UnsafeUrlError, resolve_and_validate_external_url
from app.database import async_session_factory
from app.modules.integrations.models import IntegrationConfig
from app.modules.notifications.dispatcher import _event_filter_matches
from app.modules.notifications.templates import combine_title_body
from app.modules.notifications.templates import render as render_template

logger = logging.getLogger(__name__)

# Connectors that post to a user-supplied URL. These get an extra SSRF
# re-validation right before dispatch, mirroring the Test-button paths.
_URL_CHANNELS = frozenset({"slack", "teams", "discord"})


def _events_filter_to_pattern(events: object) -> str:
    """Render an ``IntegrationConfig.events`` value as a matcher pattern.

    ``events`` is a JSON list on the model (default ``["*"]``). The shared
    :func:`_event_filter_matches` helper takes a comma-separated string, so
    join the list. A missing / malformed value falls back to ``"*"`` so a
    connector configured before the events column existed still receives
    everything (its historical behaviour was "all events").
    """
    if events is None:
        return "*"
    if isinstance(events, str):
        return events
    if isinstance(events, (list, tuple)):
        parts = [str(p).strip() for p in events if str(p).strip()]
        return ",".join(parts) if parts else "*"
    return "*"


async def _send_to_connector(
    config: IntegrationConfig,
    title: str,
    message: str,
    action_url: str | None,
) -> bool:
    """Dispatch one rendered message through a single connector.

    Returns True when the connector accepted the message. Never raises -
    the caller isolates failures per connector, and this helper returns
    False (logged at debug) on any problem so one broken connector cannot
    affect the others.
    """
    itype = (config.integration_type or "").strip().lower()
    cfg = config.config or {}

    # Re-validate user-supplied URLs against the SSRF deny-list before we
    # post to them (a row inserted before a stricter check, or DNS that
    # rebinds to a private IP, must not be able to reach internal hosts).
    if itype in _URL_CHANNELS:
        webhook_url = cfg.get("webhook_url", "")
        if not webhook_url:
            return False
        try:
            await resolve_and_validate_external_url(webhook_url)
        except UnsafeUrlError as exc:
            logger.warning(
                "integrations bridge: blocked unsafe %s webhook url for config %s: %s",
                itype,
                config.id,
                exc,
            )
            return False

    try:
        if itype == "telegram":
            from app.modules.integrations.telegram import send_telegram_notification

            bot_token = cfg.get("bot_token", "")
            chat_id = cfg.get("chat_id", "")
            if not bot_token or not chat_id:
                return False
            return await send_telegram_notification(
                bot_token=bot_token,
                chat_id=chat_id,
                title=title,
                message=message,
                action_url=action_url,
            )

        if itype == "slack":
            from app.modules.integrations.slack import send_slack_notification

            return await send_slack_notification(
                webhook_url=cfg.get("webhook_url", ""),
                title=title,
                message=message,
                action_url=action_url,
            )

        if itype == "teams":
            from app.modules.integrations.teams import send_teams_notification

            return await send_teams_notification(
                webhook_url=cfg.get("webhook_url", ""),
                title=title,
                message=message,
                action_url=action_url,
            )

        if itype == "discord":
            from app.modules.integrations.discord import send_discord_notification

            return await send_discord_notification(
                webhook_url=cfg.get("webhook_url", ""),
                title=title,
                message=message,
                action_url=action_url,
            )

        if itype == "whatsapp":
            from app.modules.integrations.whatsapp import send_whatsapp_notification

            phone_number_id = cfg.get("phone_number_id", "")
            access_token = cfg.get("access_token", "")
            to_phone = cfg.get("to_phone", "")
            if not phone_number_id or not access_token or not to_phone:
                return False
            # The body text is passed as the single template parameter so the
            # recipient sees the notification content (the title is folded in
            # because the message template is positional-parameter only). The
            # shared helper avoids a "Title - Title" line when an event sets the
            # body equal to the title.
            body_param = combine_title_body(title, message)
            return await send_whatsapp_notification(
                phone_number_id=phone_number_id,
                access_token=access_token,
                to_phone=to_phone,
                template_name=cfg.get("template_name", "erp_notification"),
                template_language=cfg.get("template_language", "en"),
                template_params=[body_param] if body_param else None,
            )

        # email / webhook are handled by the notifications dispatcher
        # (real SMTP + the WebhookTarget POST sink); chat connectors with no
        # send helper are skipped gracefully rather than inventing network
        # code for a channel that has none.
        logger.debug(
            "integrations bridge: no chat send helper for integration_type=%r (config %s) - skipped",
            itype,
            config.id,
        )
        return False
    except Exception:  # noqa: BLE001 - one connector must not break the others
        logger.debug(
            "integrations bridge: send failed for %s config %s",
            itype,
            config.id,
            exc_info=True,
        )
        return False


async def send_connector_message(
    config: IntegrationConfig,
    title: str,
    message: str,
    action_url: str | None = None,
) -> bool:
    """Send one message through one chat connector; True when it was accepted.

    Public entry for modules that address a chosen connector directly (a
    handover dossier link sent to a project channel). Never raises.
    """
    return await _send_to_connector(config, title, message, action_url)


async def _on_notification_created(event: Event) -> None:
    """``notifications.notification.created`` -> fan out to chat connectors.

    Loads the recipient user's ACTIVE :class:`IntegrationConfig` rows whose
    ``events`` filter matches the notification type and forwards a concise
    rendered message to each. Best-effort and fully isolated: any failure is
    logged at debug and swallowed so the upstream notification write is never
    affected.
    """
    data = event.data or {}
    user_id = data.get("user_id")
    notification_type = data.get("notification_type") or ""
    if not user_id:
        return

    # Resolve the human-readable strings from the i18n template registry so
    # the connector message matches what the in-app bell shows. The created
    # event carries title_key + body_key + body_context, so we interpolate
    # BOTH the title and the body against that context - placeholders like
    # {actual} {currency} are filled exactly as the in-app notification
    # renders them (render() falls back to the raw template if a placeholder
    # is missing, never to a half-substituted string).
    body_context = data.get("body_context") or {}
    title_key = data.get("title_key") or f"notifications.{notification_type}.title"
    title = render_template(title_key, body_context) or notification_type or "Notification"
    body_key = data.get("body_key")
    message = render_template(body_key, body_context) if body_key else ""
    if not message:
        # No distinct body - the bell shows just the title, so do the same.
        message = title

    try:
        async with async_session_factory() as session:
            stmt = select(IntegrationConfig).where(
                IntegrationConfig.user_id == user_id,
                IntegrationConfig.is_active.is_(True),
            )
            configs = list((await session.execute(stmt)).scalars().all())
            if not configs:
                return

            delivered_any = False
            for config in configs:
                pattern = _events_filter_to_pattern(config.events)
                if not _event_filter_matches(pattern, notification_type):
                    continue
                ok = await _send_to_connector(config, title, message, data.get("action_url"))
                if ok:
                    # Best-effort delivery stamp - same string format the Test
                    # button writes.
                    config.last_triggered_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
                    delivered_any = True

            if delivered_any:
                await session.commit()
    except Exception:  # noqa: BLE001 - never break the upstream notification
        logger.debug("integrations bridge: _on_notification_created failed", exc_info=True)


def register_integration_notification_bridge() -> None:
    """Subscribe the connector bridge to ``notifications.notification.created``.

    Idempotent: the event bus stores handlers in a list and would invoke a
    duplicate twice, so we no-op when this exact handler is already wired.
    Called from the integrations module ``on_startup`` hook.

    Idempotency is checked by function IDENTITY, not by ``__qualname__``. The
    notifications dispatcher subscribes its OWN module-level function - also
    named ``_on_notification_created`` (its WebSocket push) - to the SAME
    event. Both bare qualnames are the identical string
    ``"_on_notification_created"``, so a qualname check saw the dispatcher's
    handler "already present" and wrongly skipped wiring THIS bridge whenever
    the notifications module loaded first (it does - it is pulled in early as a
    dependency). The connector then stayed write-only: the Test button worked
    but no real platform notification ever reached Telegram / Slack / Teams /
    Discord / WhatsApp (issue #342). Comparing the actual handler objects
    distinguishes the two functions and still resets when a test calls
    ``event_bus.clear()``.
    """
    event_name = "notifications.notification.created"
    if _on_notification_created in event_bus._handlers.get(event_name, []):
        return
    event_bus.subscribe_once(event_name, _on_notification_created)
    logger.info("Integrations: chat-connector notification bridge wired")


__all__ = [
    "_on_notification_created",
    "_events_filter_to_pattern",
    "_send_to_connector",
    "register_integration_notification_bridge",
]
