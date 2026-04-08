"""Webhook dispatch service.

Finds matching webhook endpoints for a given event, sends HTTP POST requests
with JSON payloads, records delivery logs, and auto-disables endpoints after
10 consecutive failures.
"""

import hashlib
import hmac
import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.integrations.models import WebhookDelivery, WebhookEndpoint

logger = logging.getLogger(__name__)

_MAX_CONSECUTIVE_FAILURES = 10
_HTTP_TIMEOUT = 10.0  # seconds


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 hex digest of *payload_bytes* using *secret*."""
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


class WebhookService:
    """Manages webhook CRUD and event dispatching."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_webhooks(self, user_id: str) -> list[WebhookEndpoint]:
        """Return all webhook endpoints owned by *user_id*."""
        result = await self.session.execute(
            select(WebhookEndpoint)
            .where(WebhookEndpoint.user_id == user_id)
            .order_by(WebhookEndpoint.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_webhook(self, webhook_id: UUID) -> WebhookEndpoint | None:
        return await self.session.get(WebhookEndpoint, webhook_id)

    async def create_webhook(self, data: dict[str, Any], user_id: str) -> WebhookEndpoint:
        webhook = WebhookEndpoint(
            user_id=user_id,
            project_id=data.get("project_id"),
            name=data["name"],
            url=data["url"],
            secret=data.get("secret"),
            events=data["events"],
            is_active=data.get("is_active", True),
            metadata_=data.get("metadata", {}),
        )
        self.session.add(webhook)
        await self.session.flush()
        return webhook

    async def update_webhook(self, webhook: WebhookEndpoint, data: dict[str, Any]) -> WebhookEndpoint:
        for field in ("name", "url", "secret", "events", "is_active", "metadata"):
            if field in data and data[field] is not None:
                col = "metadata_" if field == "metadata" else field
                setattr(webhook, col, data[field])
        await self.session.flush()
        return webhook

    async def delete_webhook(self, webhook: WebhookEndpoint) -> None:
        await self.session.delete(webhook)
        await self.session.flush()

    async def list_deliveries(self, webhook_id: UUID, limit: int = 50) -> list[WebhookDelivery]:
        result = await self.session.execute(
            select(WebhookDelivery)
            .where(WebhookDelivery.webhook_id == webhook_id)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        project_id: str | None = None,
    ) -> int:
        """Send *event_type* to all matching active webhooks.

        Returns the number of webhooks that were notified.
        """
        query = select(WebhookEndpoint).where(WebhookEndpoint.is_active.is_(True))
        result = await self.session.execute(query)
        all_hooks = result.scalars().all()

        matched = []
        for hook in all_hooks:
            # Filter by project scope
            if hook.project_id is not None and project_id is not None:
                if str(hook.project_id) != str(project_id):
                    continue
            # Filter by event subscription (support wildcard "*")
            events = hook.events or []
            if "*" not in events and event_type not in events:
                continue
            matched.append(hook)

        for hook in matched:
            await self._deliver(hook, event_type, payload)

        return len(matched)

    async def send_test(self, webhook: WebhookEndpoint) -> WebhookDelivery:
        """Send a test payload to the webhook and return the delivery record."""
        test_payload = {
            "event": "webhook.test",
            "message": "This is a test delivery from OpenConstructionERP.",
            "webhook_id": str(webhook.id),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        return await self._deliver(webhook, "webhook.test", test_payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _deliver(
        self,
        hook: WebhookEndpoint,
        event_type: str,
        payload: dict[str, Any],
    ) -> WebhookDelivery:
        """POST *payload* to *hook.url*, log delivery, handle failures."""
        import orjson

        body = orjson.dumps(payload)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if hook.secret:
            headers["X-Webhook-Signature"] = _sign_payload(body, hook.secret)

        status_code: int | None = None
        response_body: str | None = None
        duration_ms: int | None = None
        start = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(hook.url, content=body, headers=headers)
                status_code = resp.status_code
                response_body = resp.text[:1000] if resp.text else None
                duration_ms = int((time.monotonic() - start) * 1000)

                # Retry once on 5xx
                if status_code >= 500:
                    resp = await client.post(hook.url, content=body, headers=headers)
                    status_code = resp.status_code
                    response_body = resp.text[:1000] if resp.text else None
                    duration_ms = int((time.monotonic() - start) * 1000)

        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            response_body = str(exc)[:1000]
            logger.warning("Webhook delivery failed for %s: %s", hook.name, exc)

        # Record delivery
        delivery = WebhookDelivery(
            webhook_id=hook.id,
            event_type=event_type,
            payload=payload,
            status_code=status_code,
            response_body=response_body,
            duration_ms=duration_ms,
        )
        self.session.add(delivery)

        # Update hook stats
        now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        hook.last_triggered_at = now_str
        hook.last_status_code = status_code

        if status_code is not None and 200 <= status_code < 300:
            hook.failure_count = 0
        else:
            hook.failure_count = (hook.failure_count or 0) + 1
            if hook.failure_count >= _MAX_CONSECUTIVE_FAILURES:
                hook.is_active = False
                logger.warning(
                    "Webhook %s disabled after %d consecutive failures",
                    hook.name,
                    hook.failure_count,
                )

        await self.session.flush()
        return delivery
