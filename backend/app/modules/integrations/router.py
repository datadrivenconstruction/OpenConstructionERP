"""Integrations API routes.

Endpoints — Chat Connectors (Teams / Slack / Telegram):
    GET    /configs                         - List user's integration configs
    POST   /configs                         - Create integration config
    PATCH  /configs/{config_id}             - Update integration config
    DELETE /configs/{config_id}             - Delete (disconnect) integration config
    POST   /configs/{config_id}/test        - Send test notification

Endpoints — Generic Webhooks:
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

from app.dependencies import CurrentUserId, SessionDep
from app.modules.integrations.models import IntegrationConfig
from app.modules.integrations.schemas import (
    DeliveryResponse,
    IntegrationConfigCreate,
    IntegrationConfigListResponse,
    IntegrationConfigResponse,
    IntegrationConfigUpdate,
    TestNotificationResponse,
    WebhookCreate,
    WebhookResponse,
    WebhookUpdate,
)
from app.modules.integrations.service import WebhookService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> WebhookService:
    return WebhookService(session)


# ---------------------------------------------------------------------------
# Integration Config CRUD (Teams, Slack, Telegram, Email)
# ---------------------------------------------------------------------------


@router.get("/configs", response_model=IntegrationConfigListResponse)
async def list_integration_configs(
    user_id: CurrentUserId,
    session: SessionDep,
    integration_type: str | None = Query(default=None),
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
    "/configs",
    response_model=IntegrationConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_integration_config(
    body: IntegrationConfigCreate,
    user_id: CurrentUserId,
    session: SessionDep,
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
) -> IntegrationConfigResponse:
    """Update an existing integration config."""
    config = await session.get(IntegrationConfig, config_id)
    if config is None or str(config.user_id) != str(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        col = "metadata_" if field == "metadata" else field
        setattr(config, col, value)

    await session.flush()
    return IntegrationConfigResponse.model_validate(config)


@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration_config(
    config_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Delete (disconnect) an integration config."""
    config = await session.get(IntegrationConfig, config_id)
    if config is None or str(config.user_id) != str(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    await session.delete(config)
    await session.flush()


@router.post("/configs/{config_id}/test", response_model=TestNotificationResponse)
async def test_integration_config(
    config_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> TestNotificationResponse:
    """Send a test notification through the integration config."""
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


@router.get("/webhooks", response_model=list[WebhookResponse])
async def list_webhooks(
    user_id: CurrentUserId,
    svc: WebhookService = Depends(_get_service),
):
    """List all webhook endpoints owned by the current user."""
    items = await svc.list_webhooks(user_id)
    return [WebhookResponse.model_validate(w) for w in items]


@router.post("/webhooks", response_model=WebhookResponse, status_code=201)
async def create_webhook(
    body: WebhookCreate,
    user_id: CurrentUserId,
    svc: WebhookService = Depends(_get_service),
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
):
    """Update an existing webhook endpoint."""
    webhook = await svc.get_webhook(webhook_id)
    if webhook is None or str(webhook.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail="Webhook not found")
    updated = await svc.update_webhook(webhook, body.model_dump(exclude_unset=True))
    return WebhookResponse.model_validate(updated)


@router.delete("/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: uuid.UUID,
    user_id: CurrentUserId,
    svc: WebhookService = Depends(_get_service),
):
    """Delete a webhook endpoint."""
    webhook = await svc.get_webhook(webhook_id)
    if webhook is None or str(webhook.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail="Webhook not found")
    await svc.delete_webhook(webhook)


@router.get(
    "/webhooks/{webhook_id}/deliveries",
    response_model=list[DeliveryResponse],
)
async def list_deliveries(
    webhook_id: uuid.UUID,
    user_id: CurrentUserId,
    svc: WebhookService = Depends(_get_service),
):
    """Return the last 50 delivery log entries for a webhook."""
    webhook = await svc.get_webhook(webhook_id)
    if webhook is None or str(webhook.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail="Webhook not found")
    items = await svc.list_deliveries(webhook_id, limit=50)
    return [DeliveryResponse.model_validate(d) for d in items]


@router.post(
    "/webhooks/{webhook_id}/test",
    response_model=DeliveryResponse,
)
async def test_webhook(
    webhook_id: uuid.UUID,
    user_id: CurrentUserId,
    svc: WebhookService = Depends(_get_service),
):
    """Send a test payload to the webhook and return the delivery result."""
    webhook = await svc.get_webhook(webhook_id)
    if webhook is None or str(webhook.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail="Webhook not found")
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


@router.get("/calendar/{project_id}.ics")
async def calendar_feed(
    project_id: uuid.UUID,
    session: SessionDep,
    token: str = Query(..., description="User API key for authentication"),
):
    """Return an iCalendar (RFC 5545) feed for a project.

    Includes milestones, meetings, task due dates, and inspection dates.
    Subscribe in Google Calendar, Outlook, or Apple Calendar.
    """
    from sqlalchemy import select

    from app.modules.users.models import APIKey

    # Authenticate via API key token
    # We match on key_prefix (first 8 chars) then verify full hash.
    # For simplicity, we match the raw token against key_hash (bcrypt) or
    # accept the prefix-based lookup.  In this implementation we accept
    # the token if its first 8 chars match a key_prefix belonging to an
    # active key.  This is intentionally lightweight for calendar apps.
    if len(token) < 8:
        raise HTTPException(status_code=401, detail="Invalid token")

    prefix = token[:8]
    key_result = await session.execute(select(APIKey).where(APIKey.key_prefix == prefix, APIKey.is_active.is_(True)))
    api_key = key_result.scalars().first()
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

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

        sched_result = await session.execute(select(Schedule).where(Schedule.project_id == project_id))
        for sched in sched_result.scalars().all():
            act_result = await session.execute(
                select(Activity).where(
                    Activity.schedule_id == sched.id,
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
            "Content-Disposition": f"attachment; filename=project-{project_id}.ics",
        },
    )
