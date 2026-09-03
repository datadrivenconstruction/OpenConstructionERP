# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Replying to, and forwarding, a message read in the reader.

THE RAIL IN THIS FILE IS THE ADDRESSING. A reply is built from ONE
correspondence row and nothing else: its sender, and - for reply-all -
the people that same message was addressed to. It never reads the
register item's recipient list.

That is not a style preference. On an RFQ the item's recipient list is
every supplier quoting the package, so a reply-all that reached for it
would hand each supplier its competitor list on the first "reply all" -
the exact defect the tailored-email rail exists to prevent. Building
only from the row makes the leak impossible rather than merely unlikely,
and ``test_reply_all_never_reaches_the_other_suppliers`` fails if anyone
rewires it.

Subject and quoted body follow ordinary mail convention so the supplier
sees what they expect: ``RE:``/``FW:`` once, never stacked, and the
original beneath a header block.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email.textify import html_to_text
from app.modules.register_workflow.sanitise import sanitise_html
from app.modules.register_workflow.service import WorkflowError, single_line

logger = logging.getLogger(__name__)

MODES = ("reply", "reply_all", "forward")

#: Prefixes already on a subject line, in the forms mail clients emit.
_RE = ("re:", "re :", "aw:", "sv:", "antw:")
_FW = ("fw:", "fwd:", "fw :", "wg:")


def reply_subject(mode: str, subject: str) -> str:
    """``RE:``/``FW:`` applied ONCE.

    A stacked "RE: RE: FW: RE:" is how a thread announces that nobody is
    reading it. If the subject already carries the right prefix it is
    left exactly as the sender wrote it.
    """
    base = single_line(subject or "").strip()
    low = base.lower()
    if mode == "forward":
        if any(low.startswith(p) for p in _FW):
            return base
        # A forwarded reply is a forward, not a reply - strip the RE: it
        # arrived with so the prefix says what is actually happening.
        for p in _RE:
            if low.startswith(p):
                base = base[len(p) :].strip()
                break
        return f"FW: {base}" if base else "FW:"
    if any(low.startswith(p) for p in _RE):
        return base
    return f"RE: {base}" if base else "RE:"


def _addr(person: dict[str, str]) -> str:
    """``Name <a@b.com>`` when both are known, else whichever there is."""
    name = single_line(person.get("name") or "").strip()
    email = single_line(person.get("email") or "").strip()
    if name and email:
        return f"{name} <{email}>"
    return email or name


def _email_of(person: dict[str, str]) -> str:
    return single_line(person.get("email") or "").strip().lower()


def _dedupe(addresses: list[str]) -> list[str]:
    """Case-insensitive on the address part, first spelling wins."""
    seen: set[str] = set()
    out: list[str] = []
    for a in addresses:
        key = a.lower()
        if "<" in a and ">" in a:
            key = a[a.rindex("<") + 1 : a.rindex(">")].strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(a)
    return out


def recipients_for(mode: str, message: dict[str, Any], typed: list[str]) -> list[str]:
    """Who this draft goes to. Built from THIS message only - see the module docstring.

    ``typed`` is what the person entered in the reader's To box; it is
    additive for a reply and the whole answer for a forward.
    """
    extra = [single_line(a).strip() for a in (typed or []) if single_line(a).strip()]
    if mode == "forward":
        # A forward has no implied recipient: the original sender must not
        # be re-mailed their own message by a mis-click.
        return _dedupe(extra)
    senders = [p for p in (message.get("from_people") or []) if _addr(p)]
    out = [_addr(p) for p in senders]
    if mode == "reply_all":
        seen = {_email_of(p) for p in senders}
        for p in message.get("to_people") or []:
            if _addr(p) and _email_of(p) not in seen:
                out.append(_addr(p))
                seen.add(_email_of(p))
    return _dedupe(out + extra)


def _people_line(people: list[dict[str, str]]) -> str:
    return "; ".join(_addr(p) for p in people if _addr(p))


def _escape(value: str) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def quoted_original(message: dict[str, Any]) -> str:
    """The original beneath a header block, the way a mail client shows it.

    The body is re-sanitised here even though the reader already received
    it clean: this string is going into a draft that leaves the building,
    and the sanitiser is cheap.
    """
    header_rows = [
        ("From", _people_line(message.get("from_people") or [])),
        ("Sent", single_line(message.get("date") or "")),
        ("To", _people_line(message.get("to_people") or [])),
        ("Subject", single_line(message.get("subject") or "")),
    ]
    rows = "".join(f"<div><b>{label}:</b> {_escape(value)}</div>" for label, value in header_rows if value)
    raw = message.get("html") or ""
    if raw:
        body, _blocked = sanitise_html(raw)
    else:
        text = _escape(message.get("text") or "")
        body = f'<pre style="white-space:pre-wrap;font:inherit;margin:0">{text}</pre>'
    return (
        '<div style="border-top:1px solid #c9d3e0;margin-top:18px;padding-top:12px">'
        f'<div style="font-size:12px;color:#5a6b80;margin-bottom:10px">{rows}</div>'
        f"{body}</div>"
    )


def quoted_original_text(message: dict[str, Any]) -> str:
    """The same quoted original, for the text/plain part of the draft.

    Mail convention rather than markup: the "-----Original message-----"
    rule, the four headers, then the body. The original is taken as TEXT
    where the capture kept one and converted from its HTML where it did
    not, so nothing reaches the reader as ``&#x27;`` or a bare tag.
    """
    header_rows = [
        ("From", _people_line(message.get("from_people") or [])),
        ("Sent", single_line(message.get("date") or "")),
        ("To", _people_line(message.get("to_people") or [])),
        ("Subject", single_line(message.get("subject") or "")),
    ]
    lines = ["", "-----Original message-----"]
    lines += [f"{label}: {value}" for label, value in header_rows if value]
    body = str(message.get("text") or "").strip() or html_to_text(message.get("html") or "")
    if body:
        lines += ["", body]
    return "\n".join(lines)


async def build_reply(
    session: AsyncSession,
    item: Any,
    *,
    correspondence_id: str,
    mode: str,
    to: list[str],
    body: str,
) -> dict[str, Any]:
    """The ONE builder behind both the reply preview and the Outlook draft.

    Preview and draft built by different code is how a flow ends up
    sending something the screen never showed.
    """
    if mode not in MODES:
        raise WorkflowError("A draft is a reply, a reply-all or a forward")

    from app.modules.register_workflow import comparing

    # message_for_viewing scopes the lookup to THIS item, so a message id
    # from another job cannot be quoted into a draft on this one.
    message = await comparing.message_for_viewing(session, item, correspondence_id)
    if message is None:
        raise WorkflowError("That message is not on this item")

    recipients = recipients_for(mode, message, to)
    if not recipients:
        raise WorkflowError(
            "Type an address to forward it to."
            if mode == "forward"
            else "There is no address on this message to reply to - type one."
        )

    typed, _blocked = sanitise_html(body or "")
    html = (
        '<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1f2b3a">'
        f"{typed}{quoted_original(message)}</div>"
    )
    # THE PLAIN PART, built the same way the HTML one is: what was typed,
    # then the quoted original. A reply whose text/plain alternative said
    # only "this message requires an HTML-capable mail client" is a reply
    # the supplier's gateway may show as blank.
    text = "\n".join(x for x in [html_to_text(typed), quoted_original_text(message)] if x.strip())
    # A FORWARD CARRIES THE FILES; A REPLY DOES NOT. Replying attaches the
    # supplier's own quote back to them, which is noise at best and, on a
    # reply-all, hands it to whoever else was on the message.
    documents = list(message.get("documents") or []) if mode == "forward" else []
    return {
        "mode": mode,
        "correspondence_id": str(correspondence_id),
        "to": recipients,
        "subject": reply_subject(mode, message.get("subject") or ""),
        "html": html,
        "text": text,
        # NAMES for the screen, PATHS for the draft. The path is a
        # server-side detail and the preview endpoint strips it before
        # answering the browser.
        "attachment_names": [d.get("filename", "") for d in documents if d.get("filename")],
        "attachment_paths": [d["stored"] for d in documents if d.get("stored")],
        "in_reply_to": {
            "subject": message.get("subject") or "",
            "from": _people_line(message.get("from_people") or []),
            "date": message.get("date") or "",
            "reference_number": message.get("reference_number") or "",
        },
    }
