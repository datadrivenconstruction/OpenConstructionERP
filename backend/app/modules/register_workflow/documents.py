# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Serving evidence safely, and reading .eml/.msg replies.

Two jobs:

- Hand back an attached file for the viewer, refusing anything that
  tries to climb out of the item's own folder.
- Turn a saved ``.eml`` into something readable: headers, a plain-text
  body, and the inner attachments listed. **Remote images are stripped**
  - in a supplier's quote they are read receipts, and rendering one
  tells the sender when the buyer opened the price.
"""

from __future__ import annotations

import email
import email.policy
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ATTACH_ROOT = Path("uploads/register_workflow")

#: Extensions we will render inline. Anything else downloads, and is
#: served as octet-stream so a hostile name cannot execute in a browser.
_INLINE = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".txt": "text/plain",
}


class DocumentError(Exception):
    pass


def resolve(item_id: str, filename: str) -> tuple[Path, str, bool]:
    """(path, media type, inline?) for one of an item's attachments.

    The filename is treated as hostile: it is reduced to its bare name
    and the resolved path must still sit inside this item's folder, so
    ``../../etc/passwd`` and absolute paths both die here rather than
    somewhere further down.
    """
    folder = (ATTACH_ROOT / str(item_id)).resolve()
    bare = Path(str(filename)).name
    if not bare or bare in {".", ".."}:
        raise DocumentError("Bad filename")
    path = (folder / bare).resolve()
    if folder not in path.parents and path.parent != folder:
        raise DocumentError("Outside the item's folder")
    if not path.is_file():
        raise DocumentError("Not found")
    media = _INLINE.get(path.suffix.lower())
    return path, media or "application/octet-stream", media is not None


# ── .eml reading ─────────────────────────────────────────────────────────

# Sanitising lives in `sanitise.py` as a real allowlist. The two
# blocklist regexes that used to be here were both walked around: an
# `<img src=x onerror=...>` has no closing tag so the "strip the whole
# element" pattern never matched it, and a protocol-relative pixel
# (`//tracker/open.gif`) sailed past a pattern anchored on `https?://` -
# the read receipt fired while the viewer told the buyer it had been
# blocked.
from app.modules.register_workflow.sanitise import sanitise_html


def read_eml(raw: bytes) -> dict[str, Any]:
    """Headers, a safe body and the inner attachment names of one message."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    body_text = ""
    body_html = ""
    attachments: list[str] = []
    for part in msg.walk():
        disp = str(part.get("Content-Disposition") or "")
        ctype = part.get_content_type()
        if "attachment" in disp.lower():
            name = part.get_filename()
            if name:
                attachments.append(str(name))
            continue
        if ctype == "text/plain" and not body_text:
            body_text = part.get_content()
        elif ctype == "text/html" and not body_html:
            body_html = part.get_content()

    safe_html = ""
    blocked = False
    if body_html:
        safe_html, blocked = sanitise_html(body_html)
    return {
        "from": str(msg.get("From") or ""),
        "to": str(msg.get("To") or ""),
        "cc": str(msg.get("Cc") or ""),
        "subject": str(msg.get("Subject") or ""),
        "date": str(msg.get("Date") or ""),
        "text": body_text,
        "html": safe_html,
        "attachments": attachments,
        # Said out loud so the reader knows why a logo is missing.
        "remote_content_blocked": blocked,
    }
