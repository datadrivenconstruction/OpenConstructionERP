"""Telegram Bot API connector.

Setup: User creates a bot via @BotFather, gets bot token,
adds bot to a group/channel, provides chat_id.
Legal: Official Bot API, no restrictions.
"""

import html
import logging

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0
_API_BASE = "https://api.telegram.org"


async def send_telegram_notification(
    bot_token: str,
    chat_id: str,
    title: str,
    message: str,
    action_url: str | None = None,
) -> bool:
    """Send an HTML-formatted notification via Telegram Bot API.

    Args:
        bot_token: The bot token obtained from @BotFather.
        chat_id: The target chat/group/channel ID.
        title: Bold heading for the message.
        message: Body text (plain text, will be HTML-escaped).
        action_url: Optional link appended to the message.

    Returns:
        True if Telegram accepted the message, False otherwise.
    """
    parts = [f"<b>{html.escape(title)}</b>", "", html.escape(message)]

    if action_url:
        parts.append("")
        parts.append(f'<a href="{html.escape(action_url)}">Open in ERP</a>')

    text = "\n".join(parts)

    url = f"{_API_BASE}/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                logger.info("Telegram notification sent: %s", title)
                return True
            logger.warning(
                "Telegram API returned %d: %s",
                resp.status_code,
                data.get("description", resp.text[:200]),
            )
            return False
    except httpx.HTTPError as exc:
        logger.error("Telegram API failed: %s", exc)
        return False
