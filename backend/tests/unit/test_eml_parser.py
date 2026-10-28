# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the stored-message parser.

Builds sample raw messages inline and asserts header, threading, body, and
attachment parsing, plus the contract that malformed or empty input does not
raise.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.modules.inbound_email.eml_parser import (
    EmailAttachment,
    ParsedEmail,
    parse_eml,
)

SIMPLE_TEXT = (
    "Message-ID: <abc123@site.example>\r\n"
    "From: Jane Planner <jane@contractor.example>\r\n"
    "To: pm@employer.example, clerk@employer.example\r\n"
    "Cc: Archive <archive@contractor.example>\r\n"
    "Subject: Weekly progress note\r\n"
    "Date: Tue, 03 Mar 2026 09:30:00 +0000\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
    "\r\n"
    "Pour to level 2 complete. No issues this week.\r\n"
)

MULTIPART_ALTERNATIVE = (
    "From: site@contractor.example\r\n"
    "To: pm@employer.example\r\n"
    "Subject: Site diary\r\n"
    "Date: Wed, 04 Mar 2026 14:00:00 +0200\r\n"
    'Content-Type: multipart/alternative; boundary="BOUND"\r\n'
    "\r\n"
    "--BOUND\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
    "\r\n"
    "Plain body wins.\r\n"
    "--BOUND\r\n"
    "Content-Type: text/html; charset=utf-8\r\n"
    "\r\n"
    "<html><body><p>HTML body loses.</p></body></html>\r\n"
    "--BOUND--\r\n"
)

HTML_ONLY = (
    "From: design@consultant.example\r\n"
    "To: pm@employer.example\r\n"
    "Subject: Revised drawings\r\n"
    "Content-Type: text/html; charset=utf-8\r\n"
    "\r\n"
    "<html><head><title>ignore me</title>"
    "<style>p{color:red}</style></head>"
    "<body><p>Drawings revised.</p>"
    "<script>var x = 1;</script>"
    "<p>Please review.</p></body></html>\r\n"
)

WITH_ATTACHMENT = (
    "From: site@contractor.example\r\n"
    "To: pm@employer.example\r\n"
    "Subject: Photo log\r\n"
    'Content-Type: multipart/mixed; boundary="MIX"\r\n'
    "\r\n"
    "--MIX\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
    "\r\n"
    "See attached photo.\r\n"
    "--MIX\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
    'Content-Disposition: attachment; filename="note.txt"\r\n'
    "\r\n"
    "hello attachment\r\n"
    "--MIX--\r\n"
)

NO_DATE_NO_ID = (
    "From: anon@contractor.example\r\n"
    "To: pm@employer.example\r\n"
    "Subject: No date or id\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
    "\r\n"
    "Body without a Date or Message-ID header.\r\n"
)

THREADED = (
    "Message-ID: <reply@employer.example>\r\n"
    "In-Reply-To: <orig@contractor.example>\r\n"
    "References: <root@contractor.example> <orig@contractor.example>\r\n"
    "From: pm@employer.example\r\n"
    "To: site@contractor.example\r\n"
    "Subject: Re: query\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
    "\r\n"
    "Reply body.\r\n"
)


def test_simple_text_headers_and_body() -> None:
    parsed = parse_eml(SIMPLE_TEXT)
    assert parsed.message_id == "<abc123@site.example>"
    assert parsed.subject == "Weekly progress note"
    assert parsed.from_addr == "jane@contractor.example"
    assert parsed.to_addrs == ["pm@employer.example", "clerk@employer.example"]
    assert parsed.cc_addrs == ["archive@contractor.example"]
    assert "Pour to level 2 complete." in parsed.body_text


def test_date_iso_is_aware_utc() -> None:
    parsed = parse_eml(SIMPLE_TEXT)
    assert parsed.date_iso is not None
    dt = datetime.fromisoformat(parsed.date_iso)
    assert dt.tzinfo is not None
    # 09:30 +0000 normalizes to 09:30 UTC.
    assert parsed.date_iso.startswith("2026-03-03T09:30:00")
    assert dt.utcoffset() is not None
    assert dt.utcoffset().total_seconds() == 0


def test_date_iso_offset_normalized_to_utc() -> None:
    # 14:00 +0200 should become 12:00 UTC after normalization.
    parsed = parse_eml(MULTIPART_ALTERNATIVE)
    assert parsed.date_iso is not None
    dt = datetime.fromisoformat(parsed.date_iso)
    assert dt.utcoffset().total_seconds() == 0
    assert parsed.date_iso.startswith("2026-03-04T12:00:00")


def test_bytes_input_accepted() -> None:
    parsed = parse_eml(SIMPLE_TEXT.encode("utf-8"))
    assert parsed.subject == "Weekly progress note"
    assert parsed.from_addr == "jane@contractor.example"


def test_multipart_prefers_plain_text() -> None:
    parsed = parse_eml(MULTIPART_ALTERNATIVE)
    assert "Plain body wins." in parsed.body_text
    assert "HTML body loses." not in parsed.body_text


def test_html_only_body_is_stripped() -> None:
    parsed = parse_eml(HTML_ONLY)
    assert "Drawings revised." in parsed.body_text
    assert "Please review." in parsed.body_text
    # Tags, script, and style content must not leak into the text body.
    assert "<p>" not in parsed.body_text
    assert "var x" not in parsed.body_text
    assert "color:red" not in parsed.body_text
    assert "ignore me" not in parsed.body_text


def test_attachment_metadata() -> None:
    parsed = parse_eml(WITH_ATTACHMENT)
    assert "See attached photo." in parsed.body_text
    assert len(parsed.attachments) == 1
    att = parsed.attachments[0]
    assert isinstance(att, EmailAttachment)
    assert att.filename == "note.txt"
    assert att.content_type == "text/plain"
    # "hello attachment" is 16 bytes of payload.
    assert att.size_bytes == len(b"hello attachment")


def test_missing_date_and_message_id_are_none() -> None:
    parsed = parse_eml(NO_DATE_NO_ID)
    assert parsed.date_iso is None
    assert parsed.message_id is None
    assert parsed.in_reply_to is None
    assert parsed.references == []
    assert parsed.subject == "No date or id"


def test_threading_headers_parsed() -> None:
    parsed = parse_eml(THREADED)
    assert parsed.message_id == "<reply@employer.example>"
    assert parsed.in_reply_to == "<orig@contractor.example>"
    assert parsed.references == [
        "<root@contractor.example>",
        "<orig@contractor.example>",
    ]


def test_references_absent_is_empty_list() -> None:
    parsed = parse_eml(SIMPLE_TEXT)
    assert parsed.references == []


@pytest.mark.parametrize(
    "bad",
    [
        "",
        b"",
        "not even close to an email",
        "Subject: only a subject and nothing else",
        "\r\n\r\n",
        b"\xff\xfe\x00 garbage bytes \x00",
    ],
)
def test_malformed_input_does_not_raise(bad: str | bytes) -> None:
    # The contract is best-effort; any input must yield a record, not an error.
    parsed = parse_eml(bad)
    assert isinstance(parsed, ParsedEmail)
    assert isinstance(parsed.to_addrs, list)
    assert isinstance(parsed.references, list)
    assert isinstance(parsed.attachments, list)


def test_empty_message_has_defaults() -> None:
    parsed = parse_eml("")
    assert parsed.subject == ""
    assert parsed.from_addr == ""
    assert parsed.to_addrs == []
    assert parsed.body_text == ""
    assert parsed.message_id is None


def test_subject_absent_is_empty_string() -> None:
    raw = "From: x@a.example\r\nTo: y@b.example\r\nContent-Type: text/plain\r\n\r\nno subject here\r\n"
    parsed = parse_eml(raw)
    assert parsed.subject == ""
    assert parsed.from_addr == "x@a.example"
