"""WhatsApp Business connector via Meta Cloud API.

Setup: Requires a Meta Business account with WhatsApp Business API access.
The user needs a verified Business phone number ID and a permanent access token.
Messages are sent as pre-approved templates (Meta requires template approval).

Legal: Uses official Meta Cloud API v20.0. Requires Meta Business verification.
Status: Coming Soon — requires Meta Business verification before production use.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0
_API_BASE = "https://graph.facebook.com/v20.0"


async def send_whatsapp_notification(
    phone_number_id: str,
    access_token: str,
    to_phone: str,
    template_name: str = "erp_notification",
    template_language: str = "en",
    template_params: list[str] | None = None,
) -> bool:
    """Send a template message via WhatsApp Business Cloud API.

    Args:
        phone_number_id: The WhatsApp Business phone number ID from Meta dashboard.
        access_token: Permanent access token from Meta Business settings.
        to_phone: Recipient phone number in international format (e.g. '+491234567890').
        template_name: Pre-approved message template name. Default 'erp_notification'.
        template_language: Template language code. Default 'en'.
        template_params: Optional list of parameter values for the template body.

    Returns:
        True if Meta accepted the message, False otherwise.
    """
    url = f"{_API_BASE}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # Build the template component with parameters
    components: list[dict[str, Any]] = []
    if template_params:
        components.append({
            "type": "body",
            "parameters": [
                {"type": "text", "text": param} for param in template_params
            ],
        })

    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": template_language},
            **({"components": components} if components else {}),
        },
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
            data = resp.json()
            if resp.status_code == 200 and "messages" in data:
                msg_id = data["messages"][0].get("id", "unknown")
                logger.info("WhatsApp message sent: id=%s", msg_id)
                return True
            error = data.get("error", {})
            logger.warning(
                "WhatsApp API returned %d: %s (code=%s)",
                resp.status_code,
                error.get("message", resp.text[:200]),
                error.get("code", "?"),
            )
            return False
    except httpx.HTTPError as exc:
        logger.error("WhatsApp API failed: %s", exc)
        return False
