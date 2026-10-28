# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integrations API routes.

Endpoints - Chat Connectors (Teams / Slack / Telegram):
    GET    /configs                         - List user's integration configs
    POST   /configs                         - Create integration config
    PATCH  /configs/{config_id}             - Update integration config
    DELETE /configs/{config_id}             - Delete (disconnect) integration config
    POST   /configs/{config_id}/test        - Send test notification

Endpoints - Generic Webhooks:
    GET    /webhooks                        - List user's webhooks
    POST   /webhooks                        - Create webhook
    PATCH  /webhooks/{webhook_id}           - Update webhook
    DELETE /webhooks/{webhook_id}           - Delete webhook
    GET    /webhooks/{webhook_id}/deliveries - Recent deliveries
    POST   /webhooks/{webhook_id}/test      - Send test payload

    GET    /calendar/{project_id}.ics       - iCalendar feed (RFC 5545)
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse

from app.core.i18n import get_locale
from app.core.json_merge import merge_metadata
from app.core.rate_limiter import approval_limiter
from app.core.url_safety import UnsafeUrlError, resolve_and_validate_external_url
from app.core.validation.messages import translate
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.integrations.models import IntegrationConfig
from app.modules.integrations.schemas import (
    DeliveryResponse,
    IntegrationConfigCreate,
    IntegrationConfigListResponse,
    IntegrationConfigResponse,
    IntegrationConfigUpdate,
    TestConnectionRequest,
    TestNotificationResponse,
    WebhookCreate,
    WebhookResponse,
    WebhookUpdate,
)
from app.modules.integrations.service import WebhookService

router = APIRouter(tags=["integrations"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> WebhookService:
    return WebhookService(session)


# ---------------------------------------------------------------------------
# Integration Config CRUD (Teams, Slack, Telegram, Email)
# ---------------------------------------------------------------------------


@router.get("/configs/", response_model=IntegrationConfigListResponse)
async def list_integration_configs(
    user_id: CurrentUserId,
    session: SessionDep,
    integration_type: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("integrations.read")),
) -> IntegrationConfigListResponse:
    """List the current user's integration configs."""
    from sqlalchemy import func, select

    query = select(IntegrationConfig).where(IntegrationConfig.user_id == user_id)
    if integration_type:
        query = query.where(IntegrationConfig.integration_type == integration_type)
    query = query.order_by(IntegrationConfig.created_at.desc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_q)).scalar_one()

    result = await session.execute(query)
    items = list(result.scalars().all())

    return IntegrationConfigListResponse(
        items=[IntegrationConfigResponse.model_validate(c) for c in items],
        total=total,
    )


@router.post(
    "/configs/",
    response_model=IntegrationConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_integration_config(
    body: IntegrationConfigCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("integrations.create")),
) -> IntegrationConfigResponse:
    """Create a new integration config (Teams, Slack, Telegram, etc.)."""
    config = IntegrationConfig(
        user_id=user_id,
        project_id=body.project_id,
        integration_type=body.integration_type,
        name=body.name,
        config=body.config,
        events=body.events,
        is_active=body.is_active,
        metadata_=body.metadata,
    )
    session.add(config)
    await session.flush()
    logger.info(
        "Integration config created: type=%s name=%s user=%s",
        body.integration_type,
        body.name,
        user_id,
    )
    return IntegrationConfigResponse.model_validate(config)


@router.patch("/configs/{config_id}", response_model=IntegrationConfigResponse)
async def update_integration_config(
    config_id: uuid.UUID,
    body: IntegrationConfigUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("integrations.update")),
) -> IntegrationConfigResponse:
    """Update an existing integration config."""
    config = await session.get(IntegrationConfig, config_id)
    if config is None or str(config.user_id) != str(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        col = "metadata_" if field == "metadata" else field
        if col == "metadata_" and isinstance(value, dict):
            value = merge_metadata(getattr(config, "metadata_", None), value)
        setattr(config, col, value)

    await session.flush()
    # Reload server-computed columns (updated_at onupdate=func.now()) inside the
    # async greenlet so model_validate below doesn't lazy-load them and raise
    # MissingGreenlet.
    await session.refresh(config)
    return IntegrationConfigResponse.model_validate(config)


@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration_config(
    config_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("integrations.delete")),
) -> None:
    """Delete (disconnect) an integration config."""
    config = await session.get(IntegrationConfig, config_id)
    if config is None or str(config.user_id) != str(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    await session.delete(config)
    await session.flush()


def _email_configuration_report() -> TestNotificationResponse:
    """Report whether the server can actually send mail, and where to change it.

    Outbound email is a server-wide setting, not a per-user connector: the
    fields on the Email card are persisted but no send path reads them. Both
    Test buttons used to answer "Test not supported for integration type:
    email", which left people retyping credentials that could never take
    effect. Reporting the real state of the server configuration - and naming
    the settings that carry it - is the only useful answer we can give at the
    point where someone is looking for it.

    This deliberately does not open a connection. Probing an arbitrary host on
    demand is an outbound path of its own and is being designed separately.
    """
    from app.config import get_settings
    from app.core.email.service import EMAIL_SETUP_DOC, diagnose_email_config, email_delivery_enabled

    settings = get_settings()
    problem = diagnose_email_config(settings)

    # A diagnosed contradiction counts as a failure even when a transport and a
    # host are both present: port 465, for instance, satisfies "configured" and
    # still cannot deliver a single message. Reporting that as a pass would be
    # the same green-light-over-silence this whole path exists to remove.
    if email_delivery_enabled(settings) and problem is None:
        return TestNotificationResponse(
            success=True,
            message=(
                f"Outbound email is configured on the server: EMAIL_BACKEND=smtp with SMTP_HOST set, "
                f"sending as {settings.smtp_from}. This checks the settings only - it does not open a "
                f"connection, so it cannot confirm your provider will accept the message."
            ),
        )

    return TestNotificationResponse(
        success=False,
        message=problem
        or (
            "Outbound email is not configured on this server. It is set with the EMAIL_BACKEND and "
            f"SMTP_* environment variables rather than on this screen. See {EMAIL_SETUP_DOC}."
        ),
    )


async def _dispatch_integration_test(itype: str, cfg: dict) -> TestNotificationResponse:
    """Send a test notification for an integration type + ad-hoc config.

    Shared by the saved-config test (``/configs/{id}/test``) and the
    pre-save Connect-modal test (``/configs/test-connection``). Outbound URLs
    are re-validated against the SSRF deny-list right before dispatch. Never
    raises - returns a TestNotificationResponse with the outcome.
    """
    title = "OpenConstructionERP Test"
    message = "This is a test notification. If you see this, the integration is working correctly."
    action_url = None
    cfg = cfg or {}
    success = False
    try:
        if itype == "teams":
            from app.modules.integrations.teams import send_teams_notification

            webhook_url = cfg.get("webhook_url", "")
            if not webhook_url:
                return TestNotificationResponse(success=False, message="Missing webhook_url in config")
            try:
                await resolve_and_validate_external_url(webhook_url)
            except UnsafeUrlError as exc:
                return TestNotificationResponse(success=False, message=f"URL blocked: {exc}")
            success = await send_teams_notification(
                webhook_url=webhook_url,
                title=title,
                message=message,
                action_url=action_url,
                facts=[{"title": "Status", "value": "Test delivery"}],
            )

        elif itype == "slack":
            from app.modules.integrations.slack import send_slack_notification

            webhook_url = cfg.get("webhook_url", "")
            if not webhook_url:
                return TestNotificationResponse(success=False, message="Missing webhook_url in config")
            try:
                await resolve_and_validate_external_url(webhook_url)
            except UnsafeUrlError as exc:
                return TestNotificationResponse(success=False, message=f"URL blocked: {exc}")
            success = await send_slack_notification(
                webhook_url=webhook_url,
                title=title,
                message=message,
                action_url=action_url,
                fields=[{"title": "Status", "value": "Test delivery"}],
            )

        elif itype == "telegram":
            from app.modules.integrations.telegram import send_telegram_notification

            bot_token = cfg.get("bot_token", "")
            chat_id = cfg.get("chat_id", "")
            if not bot_token or not chat_id:
                return TestNotificationResponse(success=False, message="Missing bot_token or chat_id in config")
            success = await send_telegram_notification(
                bot_token=bot_token,
                chat_id=chat_id,
                title=title,
                message=message,
                action_url=action_url,
            )

        elif itype == "discord":
            from app.modules.integrations.discord import send_discord_notification

            webhook_url = cfg.get("webhook_url", "")
            if not webhook_url:
                return TestNotificationResponse(success=False, message="Missing webhook_url in config")
            try:
                await resolve_and_validate_external_url(webhook_url)
            except UnsafeUrlError as exc:
                return TestNotificationResponse(success=False, message=f"URL blocked: {exc}")
            success = await send_discord_notification(
                webhook_url=webhook_url,
                title=title,
                message=message,
                action_url=action_url,
                fields=[{"name": "Status", "value": "Test delivery"}],
            )

        elif itype == "whatsapp":
            from app.modules.integrations.whatsapp import send_whatsapp_notification

            phone_number_id = cfg.get("phone_number_id", "")
            access_token = cfg.get("access_token", "")
            to_phone = cfg.get("to_phone", "")
            if not phone_number_id or not access_token or not to_phone:
                return TestNotificationResponse(
                    success=False,
                    message="Missing phone_number_id, access_token or to_phone in config",
                )
            success = await send_whatsapp_notification(
                phone_number_id=phone_number_id,
                access_token=access_token,
                to_phone=to_phone,
                template_name=cfg.get("template_name", "erp_notification"),
                template_language=cfg.get("template_language", "en"),
                template_params=[message] if message else None,
            )

        elif itype == "email":
            return _email_configuration_report()

        else:
            return TestNotificationResponse(
                success=False,
                message=f"Test not supported for integration type: {itype}",
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Test notification failed for integration type %s", itype)
        return TestNotificationResponse(success=False, message=str(exc)[:500])

    return TestNotificationResponse(
        success=success,
        message="Test notification sent successfully" if success else "Delivery failed",
    )


@router.post("/configs/test-connection/", response_model=TestNotificationResponse)
async def test_connection_adhoc(
    body: TestConnectionRequest,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("integrations.update")),
) -> TestNotificationResponse:
    """Test an integration with ad-hoc field values, before it is saved.

    Backs the "Test Connection" button in the Connect modal, which has no
    persisted config row yet. Rate-limited like the saved-config test.
    """
    allowed, _ = approval_limiter.is_allowed(str(user_id))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again later.",
        )
    return await _dispatch_integration_test(body.integration_type, body.config or {})


@router.post("/configs/{config_id}/test", response_model=TestNotificationResponse)
async def test_integration_config(
    config_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("integrations.update")),
) -> TestNotificationResponse:
    """Send a test notification through the integration config.

    Rate-limited via ``approval_limiter`` (20 calls/min/user) - without
    a cap, a compromised account could turn the platform into a cheap
    DoS amplifier against arbitrary third-party webhook endpoints.

    Outbound URLs are re-validated against the SSRF deny-list right
    before dispatch so a row that was inserted before a stricter check
    landed (or one whose DNS rebinds to a private IP) cannot exfiltrate
    to the metadata API.
    """
    # Rate-limit BEFORE the DB lookup so a flood doesn't even hit the row.
    allowed, _ = approval_limiter.is_allowed(str(user_id))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again later.",
        )

    config = await session.get(IntegrationConfig, config_id)
    if config is None or str(config.user_id) != str(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    title = "OpenConstructionERP Test"
    message = "This is a test notification. If you see this, the integration is working correctly."
    action_url = None
    itype = config.integration_type
    cfg = config.config or {}
    success = False

    try:
        if itype == "teams":
            from app.modules.integrations.teams import send_teams_notification

            webhook_url = cfg.get("webhook_url", "")
            if not webhook_url:
                return TestNotificationResponse(success=False, message="Missing webhook_url in config")
            try:
                await resolve_and_validate_external_url(webhook_url)
            except UnsafeUrlError as exc:
                return TestNotificationResponse(success=False, message=f"URL blocked: {exc}")
            success = await send_teams_notification(
                webhook_url=webhook_url,
                title=title,
                message=message,
                action_url=action_url,
                facts=[{"title": "Status", "value": "Test delivery"}],
            )

        elif itype == "slack":
            from app.modules.integrations.slack import send_slack_notification

            webhook_url = cfg.get("webhook_url", "")
            if not webhook_url:
                return TestNotificationResponse(success=False, message="Missing webhook_url in config")
            try:
                await resolve_and_validate_external_url(webhook_url)
            except UnsafeUrlError as exc:
                return TestNotificationResponse(success=False, message=f"URL blocked: {exc}")
            success = await send_slack_notification(
                webhook_url=webhook_url,
                title=title,
                message=message,
                action_url=action_url,
                fields=[{"title": "Status", "value": "Test delivery"}],
            )

        elif itype == "telegram":
            from app.modules.integrations.telegram import send_telegram_notification

            bot_token = cfg.get("bot_token", "")
            chat_id = cfg.get("chat_id", "")
            if not bot_token or not chat_id:
                return TestNotificationResponse(success=False, message="Missing bot_token or chat_id in config")
            success = await send_telegram_notification(
                bot_token=bot_token,
                chat_id=chat_id,
                title=title,
                message=message,
                action_url=action_url,
            )

        elif itype == "discord":
            from app.modules.integrations.discord import send_discord_notification

            webhook_url = cfg.get("webhook_url", "")
            if not webhook_url:
                return TestNotificationResponse(success=False, message="Missing webhook_url in config")
            try:
                await resolve_and_validate_external_url(webhook_url)
            except UnsafeUrlError as exc:
                return TestNotificationResponse(success=False, message=f"URL blocked: {exc}")
            success = await send_discord_notification(
                webhook_url=webhook_url,
                title=title,
                message=message,
                action_url=action_url,
                fields=[{"name": "Status", "value": "Test delivery"}],
            )

        elif itype == "whatsapp":
            from app.modules.integrations.whatsapp import send_whatsapp_notification

            phone_number_id = cfg.get("phone_number_id", "")
            access_token = cfg.get("access_token", "")
            to_phone = cfg.get("to_phone", "")
            if not phone_number_id or not access_token or not to_phone:
                return TestNotificationResponse(
                    success=False,
                    message="Missing phone_number_id, access_token or to_phone in config",
                )
            success = await send_whatsapp_notification(
                phone_number_id=phone_number_id,
                access_token=access_token,
                to_phone=to_phone,
                template_name=cfg.get("template_name", "erp_notification"),
                template_language=cfg.get("template_language", "en"),
                template_params=[message] if message else None,
            )

        elif itype == "email":
            return _email_configuration_report()

        else:
            return TestNotificationResponse(
                success=False,
                message=f"Test not supported for integration type: {itype}",
            )

    except Exception as exc:
        logger.exception("Test notification failed for config %s", config_id)
        return TestNotificationResponse(success=False, message=str(exc)[:500])

    # Update last_triggered_at on success
    if success:
        config.last_triggered_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        await session.flush()

    return TestNotificationResponse(
        success=success,
        message="Test notification sent successfully" if success else "Delivery failed",
    )


# ---------------------------------------------------------------------------
# Webhook CRUD
# ---------------------------------------------------------------------------


@router.get("/webhooks/", response_model=list[WebhookResponse])
async def list_webhooks(
    user_id: CurrentUserId,
    svc: WebhookService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("integrations.read")),
):
    """List all webhook endpoints owned by the current user."""
    items = await svc.list_webhooks(user_id)
    return [WebhookResponse.model_validate(w) for w in items]


@router.post("/webhooks/", response_model=WebhookResponse, status_code=201)
async def create_webhook(
    body: WebhookCreate,
    user_id: CurrentUserId,
    svc: WebhookService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("integrations.create")),
):
    """Create a new webhook endpoint."""
    webhook = await svc.create_webhook(body.model_dump(), user_id)
    return WebhookResponse.model_validate(webhook)


@router.patch("/webhooks/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: uuid.UUID,
    body: WebhookUpdate,
    user_id: CurrentUserId,
    svc: WebhookService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("integrations.update")),
):
    """Update an existing webhook endpoint."""
    webhook = await svc.get_webhook(webhook_id)
    if webhook is None or str(webhook.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail=translate("errors.webhook_not_found", locale=get_locale()))
    updated = await svc.update_webhook(webhook, body.model_dump(exclude_unset=True))
    return WebhookResponse.model_validate(updated)


@router.delete("/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: uuid.UUID,
    user_id: CurrentUserId,
    svc: WebhookService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("integrations.delete")),
):
    """Delete a webhook endpoint."""
    webhook = await svc.get_webhook(webhook_id)
    if webhook is None or str(webhook.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail=translate("errors.webhook_not_found", locale=get_locale()))
    await svc.delete_webhook(webhook)


@router.get(
    "/webhooks/{webhook_id}/deliveries/",
    response_model=list[DeliveryResponse],
)
async def list_deliveries(
    webhook_id: uuid.UUID,
    user_id: CurrentUserId,
    svc: WebhookService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("integrations.read")),
):
    """Return the last 50 delivery log entries for a webhook."""
    webhook = await svc.get_webhook(webhook_id)
    if webhook is None or str(webhook.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail=translate("errors.webhook_not_found", locale=get_locale()))
    items = await svc.list_deliveries(webhook_id, limit=50)
    return [DeliveryResponse.model_validate(d) for d in items]


@router.post(
    "/webhooks/{webhook_id}/test/",
    response_model=DeliveryResponse,
)
async def test_webhook(
    webhook_id: uuid.UUID,
    user_id: CurrentUserId,
    svc: WebhookService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("integrations.update")),
):
    """Send a test payload to the webhook and return the delivery result.

    Rate-limited at 20/min/user via ``approval_limiter`` - without a
    cap, a compromised account could fan out test deliveries against
    arbitrary third-party hosts and turn the platform into a DoS
    amplifier.
    """
    allowed, _ = approval_limiter.is_allowed(str(user_id))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again later.",
        )
    webhook = await svc.get_webhook(webhook_id)
    if webhook is None or str(webhook.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail=translate("errors.webhook_not_found", locale=get_locale()))
    delivery = await svc.send_test(webhook)
    return DeliveryResponse.model_validate(delivery)


# ---------------------------------------------------------------------------
# Calendar feed (iCal / ICS)
# ---------------------------------------------------------------------------


def _ical_escape(text: str) -> str:
    """Escape special characters for iCalendar text values."""
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ical_dt(iso_str: str | None) -> str | None:
    """Convert an ISO date or datetime string to iCal DTSTART format (UTC)."""
    if not iso_str:
        return None
    # Strip to just the date portion if only date provided
    clean = iso_str.replace("-", "").replace(":", "").replace(" ", "T")
    if len(clean) == 8:
        # Date only -> treat as all-day start
        return clean + "T090000Z"
    # Remove any timezone suffix and assume UTC
    clean = clean.split("+")[0].split("Z")[0]
    if "T" in clean:
        # Ensure exactly 6 digits after T
        parts = clean.split("T")
        time_part = parts[1].replace(".", "")[:6].ljust(6, "0")
        return parts[0] + "T" + time_part + "Z"
    return clean + "T090000Z"


@router.get("/calendar/{project_id}.ics/")
async def calendar_feed(
    project_id: uuid.UUID,
    session: SessionDep,
    token: str = Query(
        ...,
        description="API key declaring the integrations.calendar_feed permission",
    ),
):
    """Return an iCalendar (RFC 5545) feed for a project.

    Includes milestones, meetings, task due dates, and inspection dates.
    Subscribe in Google Calendar, Outlook, or Apple Calendar.

    The credential travels in the query string because calendar clients cannot
    send headers, which makes it the most exposed credential the platform
    issues: it sits in a third-party calendar service's configuration and any
    intermediary that logs URLs logs it. So this route demands the NARROWEST
    key we can express - one that names ``integrations.calendar_feed`` outright.
    A general-purpose key does not open the feed merely by existing.
    """
    import hashlib

    from sqlalchemy import select

    from app.core.permissions import permission_registry
    from app.dependencies import key_scopes_allow, verify_project_access
    from app.modules.integrations.permissions import CALENDAR_FEED_PERMISSION
    from app.modules.users.models import APIKey, User

    # Authenticate via the FULL API-key token: compare its SHA-256 hash against
    # APIKey.key_hash. A prefix match alone is NOT sufficient - key_prefix is
    # the first 8 chars and is non-secret (shown in key listings), so matching
    # on it would let anyone read the feed (auth bypass). The token is also
    # bound to its owner, who must have access to this project.
    if len(token) < 8:
        raise HTTPException(status_code=401, detail="Invalid token")

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    key_result = await session.execute(
        select(APIKey).where(APIKey.key_hash == token_hash, APIKey.is_active.is_(True)),
    )
    api_key = key_result.scalars().first()
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    expires_at = api_key.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < datetime.now(UTC):
            raise HTTPException(status_code=401, detail="Invalid or expired token")

    # The key row alone is not the caller: a deactivated account's keys stay in
    # the table with is_active true, so resolve the owner and check them too.
    owner = await session.get(User, api_key.user_id)
    if owner is None or not owner.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Effective authority is the intersection of the owner's live permissions
    # and the key's declared list. Key half first, with require_declared=True:
    # unlike every other route, an empty list does NOT mean "no narrowing" here,
    # it means the key never asked for the feed and so cannot have it.
    if not key_scopes_allow(api_key.permissions, CALENDAR_FEED_PERMISSION, require_declared=True):
        raise HTTPException(
            status_code=403,
            detail=f"API key does not carry permission: {CALENDAR_FEED_PERMISSION}",
        )
    owner_role = getattr(owner, "role", "") or ""
    if not permission_registry.role_has_permission(owner_role, CALENDAR_FEED_PERMISSION):
        raise HTTPException(
            status_code=403,
            detail=f"Missing permission: {CALENDAR_FEED_PERMISSION}",
        )

    # Cross-project IDOR guard: the key owner must be able to read this project.
    # Project reach stays the owner's - the key carries no project column - so a
    # narrow permission list is the only thing holding an admin's key back here.
    await verify_project_access(project_id, str(api_key.user_id), session)

    # Build iCal content
    from app.config import get_settings

    settings = get_settings()
    version = settings.app_version

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//OpenConstructionERP//v{version}//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Project Calendar",
    ]

    uid_ns = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

    # 1. Meetings
    try:
        from app.modules.meetings.models import Meeting

        meeting_result = await session.execute(select(Meeting).where(Meeting.project_id == project_id))
        for m in meeting_result.scalars().all():
            dt = _ical_dt(m.meeting_date)
            if not dt:
                continue
            uid = str(uuid.uuid5(uid_ns, f"meeting-{m.id}"))
            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{uid}",
                    f"DTSTART:{dt}",
                    f"SUMMARY:{_ical_escape(m.title)}",
                    f"DESCRIPTION:{_ical_escape(m.meeting_type or '')}",
                    "END:VEVENT",
                ]
            )
    except Exception:
        logger.debug("Meetings not available for calendar feed")

    # 2. Task due dates (as VTODO)
    try:
        from app.modules.tasks.models import Task

        task_result = await session.execute(
            select(Task).where(
                Task.project_id == project_id,
                Task.due_date.isnot(None),
            )
        )
        for t in task_result.scalars().all():
            dt = _ical_dt(t.due_date)
            if not dt:
                continue
            uid = str(uuid.uuid5(uid_ns, f"task-{t.id}"))
            status_map = {
                "open": "NEEDS-ACTION",
                "in_progress": "IN-PROCESS",
                "completed": "COMPLETED",
                "cancelled": "CANCELLED",
            }
            ical_status = status_map.get(t.status, "NEEDS-ACTION")
            lines.extend(
                [
                    "BEGIN:VTODO",
                    f"UID:{uid}",
                    f"DUE:{dt}",
                    f"SUMMARY:{_ical_escape(t.title)}",
                    f"STATUS:{ical_status}",
                    "END:VTODO",
                ]
            )
    except Exception:
        logger.debug("Tasks not available for calendar feed")

    # 3. Inspection dates (as VEVENT)
    try:
        from app.modules.inspections.models import QualityInspection

        insp_result = await session.execute(
            select(QualityInspection).where(
                QualityInspection.project_id == project_id,
                QualityInspection.inspection_date.isnot(None),
            )
        )
        for insp in insp_result.scalars().all():
            dt = _ical_dt(insp.inspection_date)
            if not dt:
                continue
            uid = str(uuid.uuid5(uid_ns, f"inspection-{insp.id}"))
            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{uid}",
                    f"DTSTART:{dt}",
                    f"SUMMARY:Inspection: {_ical_escape(insp.title)}",
                    f"DESCRIPTION:{_ical_escape(insp.inspection_type or '')}",
                    "END:VEVENT",
                ]
            )
    except Exception:
        logger.debug("Inspections not available for calendar feed")

    # 4. Schedule milestones (activity_type == "milestone")
    try:
        from app.modules.schedule.models import Activity, Schedule

        # Single JOIN query across all of the project's schedules - avoids the
        # 1 + N pattern of fetching every schedule and then querying activities
        # once per schedule.
        act_result = await session.execute(
            select(Activity)
            .join(Schedule, Activity.schedule_id == Schedule.id)
            .where(
                Schedule.project_id == project_id,
                Activity.activity_type == "milestone",
            )
        )
        for act in act_result.scalars().all():
            dt = _ical_dt(act.start_date)
            if not dt:
                continue
            uid = str(uuid.uuid5(uid_ns, f"milestone-{act.id}"))
            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{uid}",
                    f"DTSTART:{dt}",
                    f"SUMMARY:Milestone: {_ical_escape(act.name)}",
                    f"DESCRIPTION:{_ical_escape(act.description or '')}",
                    "END:VEVENT",
                ]
            )
    except Exception:
        logger.debug("Schedule milestones not available for calendar feed")

    lines.append("END:VCALENDAR")

    content = "\r\n".join(lines) + "\r\n"
    return PlainTextResponse(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="project-{project_id}.ics"',
        },
    )
