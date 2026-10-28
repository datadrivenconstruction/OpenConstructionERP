# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Inbound email service - parse a stored message and flag delay signals.

A thin wrapper over the two pure engines: it parses a raw RFC-822 message into
a normalized record and runs the delay detector over its subject and body. It
imports only the dependency-free engines (no database, no framework), so it is
importable and testable on the local runner; the router adapts an uploaded file
to it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.inbound_email.delay_detection import DelaySignal, detect_from_email
from app.modules.inbound_email.eml_parser import ParsedEmail, parse_eml


@dataclass(frozen=True)
class InboundEmailAnalysis:
    """The parsed message together with any delay signals detected in it."""

    email: ParsedEmail
    delay_signals: list[DelaySignal]


def analyze_inbound_email(raw: str | bytes) -> InboundEmailAnalysis:
    """Parse a raw stored message and detect likely delay signals within it."""
    parsed = parse_eml(raw)
    signals = detect_from_email(parsed)
    return InboundEmailAnalysis(email=parsed, delay_signals=signals)
