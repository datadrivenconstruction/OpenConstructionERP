"""Discord webhook connector.

Setup: User creates a webhook in a Discord channel settings
(Server Settings > Integrations > Webhooks > New Webhook), copies the URL.
Legal: Uses official Discord Webhook API. No bot required, no OAuth.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0


async def send_discord_notification(
    webhook_url: str,
    title: str,
    message: str,
    color: int = 0x5865F2,
    action_url: str | None = None,
    fields: list[dict[str, str]] | None = None,
) -> bool:
    """Send an embed notification to a Discord channel via webhook.

    Args:
        webhook_url: The webhook URL from Discord channel settings.
        title: Title of the embed card.
        message: Description text (supports basic markdown).
        color: Sidebar color as integer. Default is Discord blurple.
        action_url: Optional URL added as a link in the embed.
        fields: Optional list of {"name": "...", "value": "..."} pairs.

    Returns:
        True if Discord accepted the message, False otherwise.
    """
    embed: dict[str, Any] = {
        "title": title[:256],
        "description": message[:4096],
        "color": color,
    }

    if action_url:
        embed["url"] = action_url

    if fields:
        embed["fields"] = [
            {"name": f["name"][:256], "value": f["value"][:1024], "inline": True}
            for f in fields[:25]  # Discord allows max 25 fields
        ]

    embed["footer"] = {"text": "OpenConstructionERP"}

    payload: dict[str, Any] = {
        "embeds": [embed],
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code in (200, 204):
                logger.info("Discord notification sent: %s", title)
                return True
            logger.warning(
                "Discord webhook returned %d: %s",
                resp.status_code,
                resp.text[:200],
            )
            return False
    except httpx.HTTPError as exc:
        logger.error("Discord webhook failed: %s", exc)
        return False
