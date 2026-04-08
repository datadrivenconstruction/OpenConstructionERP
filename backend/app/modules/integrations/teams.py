"""Microsoft Teams incoming webhook connector.

Setup: User creates an Incoming Webhook in their Teams channel,
copies the webhook URL, pastes it in OpenConstructionERP settings.
Legal: Uses official MS Teams webhook API. No OAuth, no app review.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0


async def send_teams_notification(
    webhook_url: str,
    title: str,
    message: str,
    color: str = "0078D4",
    action_url: str | None = None,
    facts: list[dict[str, str]] | None = None,
) -> bool:
    """Send an Adaptive Card notification to a Microsoft Teams channel.

    Args:
        webhook_url: The incoming webhook URL from the Teams channel.
        title: Bold heading for the notification card.
        message: Body text of the notification.
        color: Accent color hex (without #). Default is Teams blue.
        action_url: Optional URL for the "Open in ERP" button.
        facts: Optional list of {"title": "...", "value": "..."} key-value pairs.

    Returns:
        True if the webhook accepted the message, False otherwise.
    """
    body_elements: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": title,
            "weight": "bolder",
            "size": "medium",
            "color": "accent",
        },
        {
            "type": "TextBlock",
            "text": message,
            "wrap": True,
        },
    ]

    if facts:
        body_elements.append(
            {
                "type": "FactSet",
                "facts": [{"title": f["title"], "value": f["value"]} for f in facts],
            }
        )

    actions: list[dict[str, Any]] = []
    if action_url:
        actions.append(
            {
                "type": "Action.OpenUrl",
                "title": "Open in ERP",
                "url": action_url,
            }
        )

    payload: dict[str, Any] = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "version": "1.4",
                    "body": body_elements,
                    **({"actions": actions} if actions else {}),
                },
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code in (200, 202):
                logger.info("Teams notification sent: %s", title)
                return True
            logger.warning(
                "Teams webhook returned %d: %s",
                resp.status_code,
                resp.text[:200],
            )
            return False
    except httpx.HTTPError as exc:
        logger.error("Teams webhook failed: %s", exc)
        return False
