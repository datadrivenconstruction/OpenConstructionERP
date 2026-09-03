# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Build a downloadable .eml draft - the browser/server delivery path.

When the backend runs on a server, COM cannot reach the user's desktop
Outlook. The same email payload instead downloads as an RFC-822 file
carrying ``X-Unsent: 1`` - Outlook opens that as an EDITABLE, UNSENT
draft with To/CC/Subject and the HTML body already filled; the user
reviews and presses Send themselves. The one difference from the COM
path is that Outlook does not auto-insert the saved signature into an
.eml draft.
"""

from __future__ import annotations

import mimetypes
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from app.core.email.textify import html_to_text

#: Where an attachment is allowed to come from. `build_eml` is an
#: unguarded sink otherwise - hand it any path and it reads the bytes and
#: embeds them - so it refuses on its own account rather than trusting
#: whichever caller assembled the list.
ATTACH_ROOTS = ("uploads",)


def _header(value: str) -> str:
    """A header value with CR/LF collapsed.

    Any newline here is a mail-header injection (`\r\nBcc: ...`), and on
    Python 3.12 it is also a hard ValueError that 500s the download.
    """
    return " ".join(str(value or "").split())


def _under_allowed_root(p: Path) -> bool:
    try:
        resolved = p.resolve()
    except OSError:  # pragma: no cover - unreadable path
        return False
    for root in ATTACH_ROOTS:
        base = Path(root).resolve()
        if base == resolved or base in resolved.parents:
            return True
    return False


def build_eml(payload: dict[str, Any]) -> bytes:
    """One .eml from the shared email payload (see service.build_email_payload)."""
    msg = EmailMessage()
    # THE header that makes Outlook open this as a draft, not a received
    # message. Without it the file opens read-only with a phantom sender.
    msg["X-Unsent"] = "1"
    if payload.get("to"):
        msg["To"] = ", ".join(_header(a) for a in payload["to"])
    if payload.get("cc"):
        msg["Cc"] = ", ".join(_header(a) for a in payload["cc"])
    # BCC is deliberately omitted: a BCC header inside a forwarded .eml is
    # visible to anyone who opens the file - the whole point of BCC undone.
    msg["Subject"] = _header(payload.get("subject", ""))
    # A REAL text/plain part, not a stub. Every builder that produces one
    # of these payloads renders the same content twice (see
    # outbound.build_register_email_text), and the plain part is what a
    # gateway, a phone client set to plain text and a spam filter all
    # read. It carried one line - "This message requires an HTML-capable
    # mail client" - for every RFQ, RFI, order and variation the system
    # has ever generated, so a supplier whose client preferred plain text
    # was sent a request containing no request.
    #
    # The fallback converts the HTML rather than restoring the stub: a
    # payload assembled somewhere that has no structured content still
    # has to say what it is about.
    msg.set_content(payload.get("text") or html_to_text(payload.get("html", "")))
    msg.add_alternative(payload.get("html", ""), subtype="html")

    for path_str in payload.get("attachments") or []:
        p = Path(path_str)
        if not p.is_file() or not _under_allowed_root(p):
            # Refuse rather than skip quietly? No - a caller that already
            # filtered will never land here, and the one that does is
            # trying to exfiltrate a file. Drop it and move on.
            continue
        ctype, _ = mimetypes.guess_type(p.name)
        maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
        msg.add_attachment(
            p.read_bytes(),
            maintype=maintype,
            subtype=subtype or "octet-stream",
            filename=p.name,
        )
    return bytes(msg)
