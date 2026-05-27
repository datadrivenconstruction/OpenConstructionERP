# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Real notification dispatchers — email + webhook (Epic B / B2).

Pre-Epic-B the email and webhook channels were event-bus stubs: the
service published ``notifications.dispatch.{channel}`` and trusted some
out-of-process sink to pick it up.  Nothing ever did, so those channels
silently dropped every payload.

This module wires real sinks:

* **Email**:  uses :func:`app.core.email.get_email_service` to send a
  rendered HTML message via the configured SMTP/console backend.  The
  body is rendered with :func:`app.modules.notifications.templates.render`
  so digests respect the i18n template registry.

* **Webhook**:  uses ``httpx.AsyncClient`` to POST a JSON envelope to
  every active :class:`WebhookTarget` whose ``event_filter`` matches
  the dispatched event type.  If ``secret`` is set, the body is signed
  with HMAC-SHA256 and surfaced in the ``X-OE-Signature`` header.

Both sinks are subscribed via the event bus to keep the
``NotificationService`` dispatch path identical to before — the
service still publishes ``notifications.dispatch.email`` /
``notifications.dispatch.webhook``; this module simply provides
real handlers for them.

Failure handling: every per-target HTTP call is wrapped in try/except.
Failures are logged at WARNING and recorded on the target row
(``last_status`` + ``failure_count``) so the Admin UI surfaces broken
endpoints.  A single misbehaving target never blocks the rest of the
batch.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.notifications.models import WebhookTarget
from app.modules.notifications.templates import render as render_template

logger = logging.getLogger(__name__)

# Per-process HTTP client — reused across deliveries so we get
# connection pooling for free.  Lazily instantiated inside
# ``_get_http_client`` because the dispatcher module is imported at
# startup before the event loop is running, and ``httpx.AsyncClient``
# wants a running loop for some transports.
_HTTP_CLIENT: httpx.AsyncClient | None = None

# Default per-request timeout.  Webhooks should be fast; we don't want
# a stuck endpoint to back up the notification loop for everyone.
_WEBHOOK_TIMEOUT_SEC = 5.0

# Circuit-breaker thresholds.  A target with consecutive failures at or
# above ``_CIRCUIT_OPEN_THRESHOLD`` is skipped entirely so a dead
# external endpoint cannot slow down the fan-out batch for every
# notification.  Once the operator fixes the endpoint and manually
# resets ``failure_count`` (or re-saves the target), deliveries resume.
# ``_CIRCUIT_DEACTIVATE_THRESHOLD`` is a higher watermark: if a target
# has been silently failing this long it is auto-deactivated with a
# warning so it appears in the Admin UI as "needs attention" rather than
# piling up a growing failure counter that nobody sees.
_CIRCUIT_OPEN_THRESHOLD = 10
_CIRCUIT_DEACTIVATE_THRESHOLD = 50


def _get_http_client() -> httpx.AsyncClient:
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        _HTTP_CLIENT = httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT_SEC)
    return _HTTP_CLIENT


async def close_http_client() -> None:
    """Close the shared httpx client on app shutdown.  Test helper."""
    global _HTTP_CLIENT
    if _HTTP_CLIENT is not None:
        try:
            await _HTTP_CLIENT.aclose()
        except Exception:  # noqa: BLE001
            pass
        _HTTP_CLIENT = None


# ── Email sink ─────────────────────────────────────────────────────────────


async def _resolve_user_email(user_id: str) -> tuple[str | None, str | None]:
    """Look up the user's email + display name.  Returns ``(None, None)``
    when the user has been hard-deleted between the dispatch decision
    and the actual send.
    """
    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return None, None
    try:
        async with async_session_factory() as session:
            from app.modules.users.models import User

            user = await session.get(User, uid)
            if user is None:
                return None, None
            return user.email, user.full_name
    except Exception:  # noqa: BLE001
        logger.debug("dispatcher: user lookup failed", exc_info=True)
        return None, None


async def _on_dispatch_email(event: Event) -> None:
    """``notifications.dispatch.email`` → real SMTP send."""
    data = event.data or {}
    user_id = data.get("user_id")
    event_type = data.get("event_type") or ""
    payload = data.get("payload") or {}
    if not user_id:
        return

    to, name = await _resolve_user_email(user_id)
    if not to:
        logger.debug(
            "dispatcher: no email on file for user=%s event=%s",
            user_id,
            event_type,
        )
        return

    title_key = payload.get("title_key") or f"notifications.{event_type}.title"
    body_key = payload.get("body_key") or f"notifications.{event_type}.body"
    ctx = payload.get("body_context") or {}
    subject = render_template(title_key, ctx) or event_type
    body_text = render_template(body_key, ctx) or ""

    # Digest payloads carry an "events" list — render a small bulleted
    # summary so the recipient gets something readable in one glance.
    if event_type == "notifications.digest" and "events" in payload:
        lines = ["", "Recent notifications:", ""]
        for entry in payload.get("events", []):
            etype = entry.get("event_type", "")
            ectx = (entry.get("payload") or {}).get("body_context", {}) or {}
            etitle_key = (entry.get("payload") or {}).get("title_key") or f"notifications.{etype}.title"
            etitle = render_template(etitle_key, ectx) or etype
            lines.append(f"  • {etitle}")
        body_text = (body_text + "\n" + "\n".join(lines)).strip()
        subject = f"OpenEstimate digest — {len(payload.get('events') or [])} updates"

    html_body = _render_email_html(name, subject, body_text, payload.get("action_url"))

    try:
        from app.core.email import EmailMessage, get_email_service

        svc = get_email_service()
        result = await svc.send(
            EmailMessage(
                to=to,
                subject=subject,
                html_body=html_body,
                tags=["notification", event_type],
            ),
        )
        if not result.ok:
            logger.warning(
                "dispatcher: email delivery failed user=%s event=%s reason=%s",
                user_id,
                event_type,
                result.reason,
            )
    except Exception:  # noqa: BLE001
        logger.exception("dispatcher: email send crashed user=%s event=%s", user_id, event_type)


def _render_email_html(
    recipient_name: str | None,
    subject: str,
    body_text: str,
    action_url: str | None,
) -> str:
    """Tiny inline-styled HTML so notifications render cleanly across
    every email client.  We deliberately do not import the marketing
    template (it pulls a full layout) — these are transactional
    one-liners with at most an action button.
    """
    safe_subject = (subject or "").replace("<", "&lt;").replace(">", "&gt;")
    safe_body = (body_text or "").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    greeting = f"Hi {recipient_name}," if recipient_name else "Hi,"
    button = ""
    if action_url:
        safe_url = action_url.replace('"', "")
        button = (
            f'<p style="margin:24px 0"><a href="{safe_url}" '
            f'style="background:#2563eb;color:#fff;padding:10px 18px;'
            f'text-decoration:none;border-radius:6px;display:inline-block">'
            f"Open in OpenEstimate</a></p>"
        )
    return (
        f'<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        f'max-width:560px;margin:0 auto;padding:24px;color:#111827">'
        f'<p style="margin:0 0 12px 0">{greeting}</p>'
        f'<h2 style="margin:0 0 8px 0;font-size:18px">{safe_subject}</h2>'
        f'<p style="margin:0;color:#374151;line-height:1.5">{safe_body}</p>'
        f"{button}"
        f'<hr style="margin:24px 0;border:none;border-top:1px solid #e5e7eb">'
        f'<p style="margin:0;font-size:12px;color:#6b7280">'
        f"You are receiving this because of your notification preferences. "
        f"Manage them in your profile settings.</p>"
        f"</div>"
    )


# ── Webhook sink ───────────────────────────────────────────────────────────


def _event_filter_matches(event_filter: str, event_type: str) -> bool:
    """Match a comma-separated event-filter list against ``event_type``.

    ``*`` matches anything.  A prefix ending in ``.*`` matches by
    namespace (e.g. ``boq.*`` matches ``boq.position.created``).
    Otherwise the comparison is exact.
    """
    if not event_filter:
        return False
    patterns = [p.strip() for p in event_filter.split(",") if p.strip()]
    for pat in patterns:
        if pat == "*":
            return True
        if pat.endswith(".*") and event_type.startswith(pat[:-2] + "."):
            return True
        if pat == event_type:
            return True
    return False


def _sign_payload(secret: str, body: bytes) -> str:
    """HMAC-SHA256 hex digest of ``body`` keyed by ``secret``."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


async def _on_dispatch_webhook(event: Event) -> None:
    """``notifications.dispatch.webhook`` → POST to every matching target."""
    data = event.data or {}
    event_type = data.get("event_type") or ""
    if not event_type:
        return

    try:
        async with async_session_factory() as session:
            stmt = select(WebhookTarget).where(WebhookTarget.active.is_(True))
            targets = list((await session.execute(stmt)).scalars().all())

            if not targets:
                return

            envelope = {
                "id": str(uuid.uuid4()),
                "event_type": event_type,
                "user_id": data.get("user_id"),
                "channel": data.get("channel", "webhook"),
                "payload": data.get("payload") or {},
                "timestamp": datetime.now(UTC).isoformat(),
            }
            body = json.dumps(envelope, default=str).encode("utf-8")

            client = _get_http_client()
            for target in targets:
                if not _event_filter_matches(target.event_filter, event_type):
                    continue

                # Circuit-breaker: skip targets that have been failing
                # consecutively for too long so a dead endpoint doesn't
                # slow down every notification batch.
                current_failures = target.failure_count or 0
                if current_failures >= _CIRCUIT_DEACTIVATE_THRESHOLD:
                    # Auto-deactivate so the Admin UI surfaces it.
                    target.active = False
                    logger.warning(
                        "dispatcher: webhook target %s (%s) auto-deactivated "
                        "after %d consecutive failures — re-activate once fixed",
                        target.id,
                        target.url[:60],
                        current_failures,
                    )
                    continue
                if current_failures >= _CIRCUIT_OPEN_THRESHOLD:
                    logger.debug(
                        "dispatcher: circuit open for webhook target %s "
                        "(%d failures) — skipping delivery",
                        target.id,
                        current_failures,
                    )
                    continue

                headers = {
                    "Content-Type": "application/json",
                    "X-OE-Event-Type": event_type,
                    "X-OE-Idempotency-Key": envelope["id"],
                }
                if target.secret:
                    headers["X-OE-Signature"] = f"sha256={_sign_payload(target.secret, body)}"
                status_code: int | None = None
                ok = False
                try:
                    resp = await client.post(
                        target.url,
                        content=body,
                        headers=headers,
                    )
                    status_code = resp.status_code
                    ok = 200 <= resp.status_code < 300
                except (httpx.HTTPError, httpx.TimeoutException, Exception):  # noqa: BLE001
                    logger.warning(
                        "dispatcher: webhook target %s (%s) crashed",
                        target.id,
                        target.url[:60],
                        exc_info=True,
                    )
                target.last_status = status_code
                target.last_attempt_at = datetime.now(UTC)
                if not ok:
                    target.failure_count = (target.failure_count or 0) + 1
                else:
                    target.failure_count = 0
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("dispatcher: webhook batch crashed")


# ── In-app push (WebSocket) — see ws_hub.py ────────────────────────────────


async def _on_notification_created(event: Event) -> None:
    """Bridge ``notifications.notification.created`` → WebSocket push.

    Lives here so the dispatcher subscriptions are colocated.  The
    actual fan-out is delegated to ``notifications_ws_hub`` so the
    websocket bookkeeping stays in one place.
    """
    from app.modules.notifications.ws_hub import notifications_ws_hub

    data = event.data or {}
    user_id = data.get("user_id")
    if not user_id:
        return
    await notifications_ws_hub.push_to_user(
        user_id,
        {
            "event": "notification.created",
            "data": data,
            "ts": datetime.now(UTC).isoformat(),
        },
    )


# ── Registration ───────────────────────────────────────────────────────────


def register_dispatchers() -> None:
    """Wire the real email + webhook + WS sinks into the event bus.

    Idempotent: subscribing the same handler twice would duplicate
    sends, so we no-op when the bus already has each handler.
    """
    handlers_to_register = [
        ("notifications.dispatch.email", _on_dispatch_email),
        ("notifications.dispatch.webhook", _on_dispatch_webhook),
        ("notifications.notification.created", _on_notification_created),
    ]
    existing = event_bus.list_handlers()
    for event_name, handler in handlers_to_register:
        names = existing.get(event_name, [])
        if handler.__qualname__ in names:
            continue
        event_bus.subscribe(event_name, handler)
    logger.info("Notifications dispatchers wired (email/webhook/ws)")


__all__ = [
    "_on_dispatch_email",
    "_on_dispatch_webhook",
    "_on_notification_created",
    "_event_filter_matches",
    "_sign_payload",
    "close_http_client",
    "register_dispatchers",
]
