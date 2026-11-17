# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure parser for a stored RFC-822 message.

Reads a raw message - an exported message file (".eml") or the equivalent raw
``str`` / ``bytes`` - into a normalized :class:`ParsedEmail`. The intake is a
file import, not a live mailbox: the caller already holds the bytes and just
wants them turned into fields the rest of the platform can use.

Only the standard library is used (the ``email`` package with the modern
default policy, plus ``email.utils`` for address and date handling and a small
``html.parser`` subclass to recover text from a markup-only body), so the engine
imports and unit-tests on the local runner without the database or web
framework.

The contract is best-effort: every accessor is defensive and the public
:func:`parse_eml` never raises on malformed or truncated input. A field that
cannot be read comes back empty (``""`` / ``[]``) or ``None`` rather than
throwing, so a bad message degrades to a sparse record instead of failing the
whole import.
"""

from __future__ import annotations

import email
import email.policy
import email.utils
import re
from dataclasses import dataclass, field
from email.message import EmailMessage
from html.parser import HTMLParser

__all__ = ["EmailAttachment", "ParsedEmail", "extract_attachment_payloads", "parse_eml"]


@dataclass(frozen=True)
class EmailAttachment:
    """Lightweight metadata for one message attachment.

    The payload bytes are not retained; only the descriptive fields a listing
    or audit needs. ``size_bytes`` is the length of the decoded payload, or 0
    when the payload cannot be decoded.
    """

    filename: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True)
class ParsedEmail:
    """Normalized view of a single stored message.

    Header essentials, threading identifiers (``message_id``, ``in_reply_to``,
    ``references``), the best available text body, and attachment metadata.
    String fields default to ``""`` and list fields to ``[]`` so a sparse or
    malformed source still yields a usable record.
    """

    message_id: str | None = None
    subject: str = ""
    from_addr: str = ""
    to_addrs: list[str] = field(default_factory=list)
    cc_addrs: list[str] = field(default_factory=list)
    date_iso: str | None = None
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    body_text: str = ""
    attachments: list[EmailAttachment] = field(default_factory=list)


class _TextExtractor(HTMLParser):
    """Collect human-readable text from a markup body.

    Used only as a fallback when a message has no plain-text part. Script and
    style content is dropped, block-level boundaries become line breaks, and
    runs of whitespace are collapsed so the recovered text reads cleanly.
    """

    # Tags whose textual content should never surface in the body.
    _SKIP = frozenset({"script", "style", "head", "title"})
    # Tags that imply a line break around their content.
    _BLOCK = frozenset(
        {
            "p",
            "br",
            "div",
            "li",
            "tr",
            "table",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "ul",
            "ol",
            "blockquote",
            "section",
            "article",
            "header",
            "footer",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        """Return the collected text with whitespace normalized."""
        raw = "".join(self._parts)
        # Collapse spaces and tabs within a line, then trim blank lines.
        lines = [re.sub(r"[ \t\f\v]+", " ", ln).strip() for ln in raw.splitlines()]
        collapsed: list[str] = []
        for ln in lines:
            if ln:
                collapsed.append(ln)
            elif collapsed and collapsed[-1] != "":
                collapsed.append("")
        return "\n".join(collapsed).strip()


def _strip_html(markup: str) -> str:
    """Best-effort conversion of a markup body to readable text."""
    parser = _TextExtractor()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:
        # A malformed markup body should never break the import; return
        # whatever was gathered before the failure.
        pass
    return parser.get_text()


def _coalesce_header(msg: EmailMessage, name: str) -> str | None:
    """Return a stripped single-line header value, or ``None`` if absent/empty."""
    raw = msg.get(name)
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _decoded_bytes(part: EmailMessage) -> bytes:
    """Decoded payload bytes for *part*, or ``b""`` if it cannot be decoded."""
    try:
        payload = part.get_payload(decode=True)
    except Exception:
        return b""
    if isinstance(payload, bytes):
        return payload
    return b""


def _part_text(part: EmailMessage) -> str:
    """Best-effort decoded text content for a text/* part."""
    try:
        content = part.get_content()
    except Exception:
        # Fall back to manual decode using the declared or a forgiving charset.
        data = _decoded_bytes(part)
        charset = part.get_content_charset() or "utf-8"
        try:
            return data.decode(charset, errors="replace")
        except (LookupError, TypeError):
            return data.decode("utf-8", errors="replace")
    if isinstance(content, str):
        return content
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return str(content)


def _is_attachment(part: EmailMessage) -> bool:
    """True when a part should be treated as an attachment."""
    disposition = part.get_content_disposition()
    if disposition == "attachment":
        return True
    # A part that carries a filename is treated as an attachment even when the
    # disposition header is missing or marked inline.
    return bool(part.get_filename())


def _extract_body_and_attachments(
    msg: EmailMessage,
) -> tuple[str, list[EmailAttachment]]:
    """Walk the message, returning the chosen body text and attachments.

    Plain text is preferred; a markup body is stripped to text only when no
    plain-text part exists. Attachments are collected from every part that is
    marked as an attachment or carries a filename.
    """
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[EmailAttachment] = []

    walker = msg.walk() if msg.is_multipart() else iter([msg])

    for part in walker:
        try:
            if part.is_multipart():
                continue
        except Exception:
            continue

        if _is_attachment(part):
            filename = part.get_filename() or ""
            attachments.append(
                EmailAttachment(
                    filename=str(filename).strip(),
                    content_type=_safe_content_type(part),
                    size_bytes=len(_decoded_bytes(part)),
                )
            )
            continue

        ctype = _safe_content_type(part)
        if ctype == "text/plain":
            plain_parts.append(_part_text(part))
        elif ctype == "text/html":
            html_parts.append(_part_text(part))

    if plain_parts:
        body = "\n".join(p for p in plain_parts if p).strip()
    elif html_parts:
        body = _strip_html("\n".join(html_parts))
    else:
        body = ""

    return body, attachments


def _safe_content_type(part: EmailMessage) -> str:
    """Content type of *part*, defaulting to ``text/plain`` on error."""
    try:
        return part.get_content_type()
    except Exception:
        return "text/plain"


def _parse_message(raw: str | bytes) -> EmailMessage:
    """Parse raw input into an :class:`EmailMessage` using the default policy."""
    policy = email.policy.default
    if isinstance(raw, bytes):
        return email.message_from_bytes(raw, policy=policy)
    return email.message_from_string(raw, policy=policy)


def parse_eml(raw: str | bytes) -> ParsedEmail:
    """Parse a raw stored message into a :class:`ParsedEmail`.

    Accepts the message as ``str`` or ``bytes``. Best-effort throughout: any
    field that cannot be read comes back empty or ``None`` and malformed or
    truncated input never raises.
    """
    try:
        msg = _parse_message(raw)
    except Exception:
        # Could not even build a message object; return an empty record.
        return ParsedEmail()

    subject = _coalesce_header(msg, "Subject") or ""

    # Sender: the address portion of the From header.
    from_raw = msg.get("From")
    if from_raw is None:
        from_addr = ""
    else:
        try:
            from_addr = email.utils.parseaddr(str(from_raw))[1] or ""
        except Exception:
            from_addr = ""

    to_addrs = _address_list(msg, "To")
    cc_addrs = _address_list(msg, "Cc")

    date_iso = _parse_date(msg.get("Date"))

    message_id = _coalesce_header(msg, "Message-ID")
    in_reply_to = _coalesce_header(msg, "In-Reply-To")

    references = _split_references(msg.get("References"))

    body_text, attachments = _extract_body_and_attachments(msg)

    return ParsedEmail(
        message_id=message_id,
        subject=subject,
        from_addr=from_addr,
        to_addrs=to_addrs,
        cc_addrs=cc_addrs,
        date_iso=date_iso,
        in_reply_to=in_reply_to,
        references=references,
        body_text=body_text,
        attachments=attachments,
    )


def _address_list(msg: EmailMessage, name: str) -> list[str]:
    """Return the address strings from header *name* (empty list if absent)."""
    values = msg.get_all(name)
    if not values:
        return []
    try:
        pairs = email.utils.getaddresses([str(v) for v in values])
    except Exception:
        return []
    return [addr for _name, addr in pairs if addr]


def _parse_date(raw: object) -> str | None:
    """Parse a Date header into an aware UTC ISO string, or ``None``."""
    if raw is None:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(str(raw))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if dt is None:
        return None
    try:
        from datetime import UTC

        if dt.tzinfo is None:
            # A naive date is taken as UTC rather than dropped.
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    except (ValueError, OverflowError):
        return None


def _split_references(raw: object) -> list[str]:
    """Split a References header into its constituent ids (empty if absent)."""
    if raw is None:
        return []
    return [token for token in str(raw).split() if token]


def extract_attachment_payloads(raw: str | bytes) -> list[tuple[str, str, bytes]]:
    """Return ``(filename, content_type, bytes)`` for every non-empty attachment.

    ``parse_eml`` keeps only attachment metadata; intake flows that must store
    the original file (scan-to-email invoice capture) use this instead.
    """
    try:
        msg = _parse_message(raw)
    except Exception:
        return []
    parts = msg.walk() if msg.is_multipart() else iter([msg])
    out: list[tuple[str, str, bytes]] = []
    for part in parts:
        try:
            if part.is_multipart() or not _is_attachment(part):
                continue
        except Exception:
            continue
        data = _decoded_bytes(part)
        if data:
            out.append((str(part.get_filename() or "").strip(), _safe_content_type(part), data))
    return out
