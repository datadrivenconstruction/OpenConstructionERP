# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Webhook dispatch service.

Finds matching webhook endpoints for a given event, signs and sends the JSON
payload, and keeps one delivery row per event with its retry state. A failed
send is retried on a fixed schedule (see ``webhook_signing.RETRY_DELAYS_S``)
by :func:`run_retry_tick`; a delivery that cannot succeed ends as ``dead``.
An endpoint is switched off after 10 consecutive dead deliveries.
"""

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.json_merge import merge_metadata
from app.core.url_safety import UnsafeUrlError, resolve_and_validate_external_url
from app.modules.integrations import webhook_signing as signing
from app.modules.integrations.models import WebhookDelivery, WebhookEndpoint

logger = logging.getLogger(__name__)

_MAX_CONSECUTIVE_FAILURES = 10
_HTTP_TIMEOUT = 10.0  # seconds
MAX_ENDPOINTS_PER_USER = 20
RETRY_BATCH = 50
_RETRY_CONCURRENCY = 4
# A claimed retry is parked this long, so a second worker (or a crash) never
# sends the same delivery twice in a row.
_RETRY_LEASE = timedelta(minutes=2)
_BODY_LIMIT = 1000


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Compute the legacy body-only HMAC-SHA256 hex digest (``X-Webhook-Signature``)."""
    return signing.legacy_signature(secret, payload_bytes)


@dataclass
class SendResult:
    """What one HTTP attempt produced, before it is written to the delivery row."""

    outcome: signing.Outcome
    status_code: int | None = None
    response_body: str | None = None
    duration_ms: int | None = None
    error: str = ""


async def _post(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, str]:
    """POST once, never following redirects. Separate so tests can replace the network."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=False) as client:
        resp = await client.post(url, content=body, headers=headers)
        return resp.status_code, (resp.text or "")[:_BODY_LIMIT]


async def send_signed(
    *,
    url: str,
    secret: str | None,
    event_type: str,
    delivery_id: UUID | str,
    body: bytes,
    now: int | None = None,
) -> SendResult:
    """Re-check the target against DNS, sign and send ``body``. Touches no database."""
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        signing.EVENT_HEADER: event_type,
        signing.DELIVERY_HEADER: str(delivery_id),
    }
    if secret:
        headers[signing.SIGNATURE_HEADER] = signing.signature_header(secret, body, now)
        headers[signing.LEGACY_SIGNATURE_HEADER] = signing.legacy_signature(secret, body)

    start = time.monotonic()
    try:
        # Resolve and verify right before sending, so a row saved before the
        # SSRF rules existed, or a name that now resolves to a private address
        # (DNS rebinding), cannot reach internal services.
        await resolve_and_validate_external_url(url)
        status_code, text = await _post(url, body, headers)
    except UnsafeUrlError as exc:
        return SendResult("dead", None, f"URL blocked: {exc}"[:_BODY_LIMIT], _ms(start), f"URL blocked: {exc}")
    except Exception as exc:  # noqa: BLE001 - timeouts and connection errors are retried
        return SendResult("retry", None, str(exc)[:_BODY_LIMIT], _ms(start), f"{type(exc).__name__}: {exc}"[:500])

    outcome = signing.classify_status(status_code)
    error = "" if outcome == "delivered" else f"HTTP {status_code}"
    return SendResult(outcome, status_code, text or None, _ms(start), error)


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


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

    async def count_webhooks(self, user_id: str) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(WebhookEndpoint).where(WebhookEndpoint.user_id == user_id)
        )
        return int(result.scalar_one())

    async def create_webhook(self, data: dict[str, Any], user_id: str) -> WebhookEndpoint:
        """Create an endpoint. Generates a 32-byte signing secret when none is given.

        The plaintext secret stays readable on the returned row's ``secret``
        attribute for the caller to show once.
        """
        if await self.count_webhooks(user_id) >= MAX_ENDPOINTS_PER_USER:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "webhook.too_many",
                    "message": f"At most {MAX_ENDPOINTS_PER_USER} webhook endpoints",
                },
            )
        webhook = WebhookEndpoint(
            user_id=user_id,
            project_id=data.get("project_id"),
            name=data["name"],
            url=data["url"],
            secret=data.get("secret") or secrets.token_urlsafe(32),
            events=data["events"],
            is_active=data.get("is_active", True),
            metadata_=data.get("metadata", {}),
        )
        self.session.add(webhook)
        await self.session.flush()
        return webhook

    async def update_webhook(self, webhook: WebhookEndpoint, data: dict[str, Any]) -> WebhookEndpoint:
        if data.get("is_active") is True and not webhook.is_active:
            # Switching a tripped endpoint back on starts it clean, or one more failure would trip it again.
            webhook.failure_count = 0
        for field in ("name", "url", "secret", "events", "is_active", "metadata"):
            if field in data and data[field] is not None:
                col = "metadata_" if field == "metadata" else field
                value = data[field]
                if col == "metadata_" and isinstance(value, dict):
                    value = merge_metadata(getattr(webhook, "metadata_", None), value)
                setattr(webhook, col, value)
        await self.session.flush()
        # Reload server-computed columns (updated_at onupdate=func.now()) inside
        # the async greenlet so model_validate after return doesn't lazy-load them.
        await self.session.refresh(webhook)
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

    async def get_delivery(self, delivery_id: UUID) -> WebhookDelivery | None:
        return await self.session.get(WebhookDelivery, delivery_id)

    async def redeliver(self, delivery: WebhookDelivery, now: datetime | None = None) -> WebhookDelivery:
        """Put a delivery back to ``pending`` with a fresh retry schedule; the worker sends it."""
        delivery.status = "pending"
        delivery.attempt = 0
        delivery.next_retry_at = now or datetime.now(UTC)
        delivery.last_error = ""
        await self.session.flush()
        return delivery

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
            # A scoped endpoint requires a matching project. A missing or
            # malformed event project must not turn it into a global endpoint.
            # Explicitly global endpoints retain their existing behaviour.
            if hook.project_id is not None and str(hook.project_id) != str(project_id):
                continue
            # Filter by event subscription (support wildcard "*")
            events = hook.events or []
            if "*" not in events and event_type not in events:
                continue
            matched.append(hook)

        # An endpoint is its owner's eyes: it may only carry events of projects
        # the owner can open themselves, global ("*") endpoints included.
        reach: dict[str, set[UUID] | None] = {}
        visible = []
        for hook in matched:
            if await self._owner_reaches(hook, project_id, reach):
                visible.append(hook)
        matched = visible

        for hook in matched:
            await self._deliver(hook, event_type, payload)

        return len(matched)

    async def _owner_reaches(
        self,
        hook: WebhookEndpoint,
        project_id: Any,
        reach: dict[str, set[UUID] | None],
    ) -> bool:
        """Whether the endpoint owner may see an event of ``project_id``.

        Events that name no valid project are not project data and stay open
        to every subscriber. ``reach`` caches the owner's project set per call.
        """
        from app.dependencies import accessible_project_ids

        try:
            pid = UUID(str(project_id))
        except (ValueError, TypeError):
            return True
        owner = str(hook.user_id)
        if owner not in reach:
            reach[owner] = await accessible_project_ids(self.session, owner)
        allowed = reach[owner]
        return allowed is None or pid in allowed

    async def deliver_to(
        self,
        webhook: WebhookEndpoint,
        event_type: str,
        payload: dict[str, Any],
    ) -> WebhookDelivery:
        """Send one payload to one endpoint now, logged like any other delivery.

        For callers that address a specific endpoint (a handover dossier sent to
        the client's system) rather than broadcasting an event to subscribers.
        """
        return await self._deliver(webhook, event_type, payload)

    async def send_test(self, webhook: WebhookEndpoint) -> WebhookDelivery:
        """Send a ``ping`` to the endpoint once and return the delivery record. Never retried."""
        ping = {
            "event": "ping",
            "message": "This is a test delivery from OpenConstructionERP.",
            "webhook_id": str(webhook.id),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        return await self._deliver(webhook, "ping", ping, retry=False)

    # ------------------------------------------------------------------
    # Retry worker
    # ------------------------------------------------------------------

    async def run_due_retries(self, now: datetime | None = None, limit: int = RETRY_BATCH) -> int:
        """Send up to ``limit`` deliveries whose ``next_retry_at`` has passed. Returns how many.

        Claimed rows are parked for two minutes first and committed, so a
        concurrent worker or a crash cannot double-send. The HTTP calls run
        four at a time; results are written back in order on this session.
        """
        now = now or datetime.now(UTC)
        result = await self.session.execute(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status.in_(("pending", "retrying")),
                WebhookDelivery.next_retry_at.is_not(None),
                WebhookDelivery.next_retry_at <= now,
            )
            .order_by(WebhookDelivery.next_retry_at)
            .limit(limit)
        )
        due = list(result.scalars().all())
        if not due:
            return 0

        jobs: list[tuple[WebhookDelivery, WebhookEndpoint | None]] = []
        for delivery in due:
            hook = await self.session.get(WebhookEndpoint, delivery.webhook_id)
            delivery.next_retry_at = now + _RETRY_LEASE
            jobs.append((delivery, hook))
        await self.session.commit()

        gate = asyncio.Semaphore(_RETRY_CONCURRENCY)

        async def send(delivery: WebhookDelivery, hook: WebhookEndpoint | None) -> SendResult | None:
            if hook is None or not hook.is_active:
                return None
            async with gate:
                return await send_signed(
                    url=hook.url,
                    secret=hook.secret,
                    event_type=delivery.event_type,
                    delivery_id=delivery.id,
                    body=_encode(delivery.payload),
                )

        results = await asyncio.gather(*(send(d, h) for d, h in jobs))
        for (delivery, hook), outcome in zip(jobs, results, strict=True):
            if outcome is None:
                delivery.status = "dead"
                delivery.next_retry_at = None
                delivery.last_error = "Endpoint removed or disabled"
                continue
            self._apply(delivery, hook, outcome, now=now, retry=True)
        await self.session.commit()
        return len(jobs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _deliver(
        self,
        hook: WebhookEndpoint,
        event_type: str,
        payload: dict[str, Any],
        *,
        retry: bool = True,
    ) -> WebhookDelivery:
        """Create the delivery row, make the first attempt now, record the outcome."""
        delivery = WebhookDelivery(
            webhook_id=hook.id,
            event_type=event_type,
            payload=payload,
            status="pending",
            attempt=0,
        )
        self.session.add(delivery)
        await self.session.flush()

        result = await send_signed(
            url=hook.url,
            secret=hook.secret,
            event_type=event_type,
            delivery_id=delivery.id,
            body=_encode(payload),
        )
        self._apply(delivery, hook, result, now=datetime.now(UTC), retry=retry)

        # Commit, not just flush. A delivery is a self-contained side effect:
        # the delivery row plus the hook's failure_count / last_status_code /
        # auto-disable state must persist on their own, whether _deliver was
        # reached from the event bus or an HTTP request.
        await self.session.commit()
        return delivery

    def _apply(
        self,
        delivery: WebhookDelivery,
        hook: WebhookEndpoint | None,
        result: SendResult,
        *,
        now: datetime,
        retry: bool,
    ) -> None:
        """Write one attempt's outcome to the delivery row and the endpoint's counters."""
        delivery.attempt = (delivery.attempt or 0) + 1
        delivery.status_code = result.status_code
        delivery.response_body = result.response_body
        delivery.duration_ms = result.duration_ms
        delivery.last_error = result.error

        outcome = result.outcome
        retry_at = signing.next_retry_at(delivery.attempt, now) if outcome == "retry" and retry else None
        if outcome == "delivered":
            delivery.status = "delivered"
            delivery.next_retry_at = None
        elif retry_at is not None:
            delivery.status = "retrying"
            delivery.next_retry_at = retry_at
        else:
            delivery.status = "dead"
            delivery.next_retry_at = None

        if hook is None:
            return
        hook.last_triggered_at = now.strftime("%Y-%m-%dT%H:%M:%S")
        hook.last_status_code = result.status_code
        if delivery.status == "delivered":
            hook.failure_count = 0
        elif delivery.status == "dead":
            hook.failure_count = (hook.failure_count or 0) + 1
            if hook.failure_count >= _MAX_CONSECUTIVE_FAILURES:
                hook.is_active = False
                logger.warning(
                    "Webhook %s disabled after %d consecutive failures",
                    hook.name,
                    hook.failure_count,
                )
        if delivery.status != "delivered":
            logger.warning("Webhook delivery %s for %s: %s", delivery.status, hook.name, result.error)


def _encode(payload: dict[str, Any]) -> bytes:
    import orjson

    return orjson.dumps(payload)


async def run_retry_tick() -> None:
    """Process-registry tick: send the deliveries that are due."""
    from app.database import async_session_factory

    async with async_session_factory() as session:
        sent = await WebhookService(session).run_due_retries()
    if sent:
        logger.info("Webhook retry: %d deliveries attempted", sent)
