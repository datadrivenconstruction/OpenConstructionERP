# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Outlook Bridge - the desktop Outlook link for the correspondence register.

OUTBOUND only. Any register email opens as a real Outlook DRAFT with the
user's saved signature preserved (Windows-with-Outlook), and the same
payload downloads as an editable ``.eml`` on any platform. Send always stays
human.

Reading the Inbox (mailbox capture) is deliberately NOT part of this build:
the correspondence register is fed by hand-filed replies instead, so nothing
here connects to or reads a mailbox.
"""

import logging

logger = logging.getLogger(__name__)


async def on_startup() -> None:
    """Nothing to start: this build has no background inbox poller."""
    return
