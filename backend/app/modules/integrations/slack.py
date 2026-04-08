"""Slack incoming webhook connector.

Setup: User creates an Incoming Webhook in Slack app settings,
copies the webhook URL.
Legal: Uses official Slack Incoming Webhooks API. No bot required.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0


async def send_slack_notification(
    webhook_url: str,
    title: str,
    message: str,
    color: str = "#4A154B",
    action_url: str | None = None,
    fields: list[dict[str, str]] | None = None,
) -> bool:
    """Send a Block Kit notification to a Slack channel via incoming webhook.

    Args:
        webhook_url: The incoming webhook URL from the Slack app.
        title: Header text for the notification.
        message: Body text (supports mrkdwn syntax).
        color: Attachment sidebar color hex. Default is Slack purple.
        action_url: Optional URL for the "Open in ERP" button.
        fields: Optional list of {"title": "...", "value": "..."} key-value pairs.

    Returns:
        True if Slack accepted the message, False otherwise.
    """
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": title[:150], "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": message},
        },
    ]

    if fields:
        field_blocks = [
            {"type": "mrkdwn", "text": f"*{f['title']}*\n{f['value']}"}
            for f in fields[:10]  # Slack allows max 10 fields
        ]
        blocks.append({"type": "section", "fields": field_blocks})

    if action_url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open in ERP"},
                        "url": action_url,
                        "style": "primary",
                    }
                ],
            }
        )

    payload: dict[str, Any] = {"blocks": blocks}

    # Also include a fallback text for notifications and accessibility
    payload["text"] = f"{title}: {message[:200]}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code == 200 and resp.text == "ok":
                logger.info("Slack notification sent: %s", title)
                return True
            logger.warning(
                "Slack webhook returned %d: %s",
                resp.status_code,
                resp.text[:200],
            )
            return False
    except httpx.HTTPError as exc:
        logger.error("Slack webhook failed: %s", exc)
        return False
