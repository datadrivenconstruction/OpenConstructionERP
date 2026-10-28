# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the inbound email service wrapper (runs on py3.11).

The service composes the two pure engines, so it imports without the database
or framework stack.
"""

from __future__ import annotations

from app.modules.inbound_email.service import InboundEmailAnalysis, analyze_inbound_email

SAMPLE_EML = (
    "From: Site Manager <site@example.com>\r\n"
    "To: pm@example.com\r\n"
    "Cc: qs@example.com\r\n"
    "Subject: Delay due to heavy rain and missing drawings\r\n"
    "Date: Mon, 22 Jun 2026 09:30:00 +0000\r\n"
    "Message-ID: <abc-123@example.com>\r\n"
    "\r\n"
    "We have lost three days this week to heavy rain and flooding on site.\r\n"
    "We are also still awaiting information on the revised drawings.\r\n"
)


def test_analyze_parses_headers() -> None:
    result = analyze_inbound_email(SAMPLE_EML)
    assert isinstance(result, InboundEmailAnalysis)
    email = result.email
    assert email.subject == "Delay due to heavy rain and missing drawings"
    assert email.from_addr == "site@example.com"
    assert email.to_addrs == ["pm@example.com"]
    assert email.cc_addrs == ["qs@example.com"]
    assert email.message_id == "<abc-123@example.com>"
    assert email.date_iso is not None and email.date_iso.startswith("2026-06-22")
    assert "heavy rain" in email.body_text.lower()


def test_analyze_detects_delay_signals() -> None:
    result = analyze_inbound_email(SAMPLE_EML)
    categories = {s.category for s in result.delay_signals}
    assert "weather" in categories
    assert "late_information" in categories
    # Signals are ordered by confidence descending.
    confidences = [s.confidence for s in result.delay_signals]
    assert confidences == sorted(confidences, reverse=True)


def test_analyze_accepts_bytes() -> None:
    result = analyze_inbound_email(SAMPLE_EML.encode("utf-8"))
    assert result.email.subject == "Delay due to heavy rain and missing drawings"


def test_analyze_empty_message_does_not_raise() -> None:
    result = analyze_inbound_email("")
    assert result.email.subject == ""
    assert result.delay_signals == []
