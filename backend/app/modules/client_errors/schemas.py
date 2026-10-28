# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the client-error sink endpoint.

The payload mirrors the anonymised entry produced by
``frontend/src/shared/lib/errorLogger.ts`` - emails, UUIDs, API keys,
bearer tokens, long numeric ids, and well-known PII JSON fields are
already scrubbed client-side before the POST is fired.

We enforce hard caps on every string field so a misbehaving client (or
an attacker bypassing the client-side scrub) cannot drive arbitrarily
large lines into the log pipeline.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClientErrorReport(BaseModel):
    """Incoming anonymised client-error payload."""

    timestamp: str = Field(
        ...,
        max_length=64,
        description="ISO-8601 timestamp the error was captured in the browser.",
    )
    error_id: str = Field(
        ...,
        max_length=64,
        description=(
            "Client-generated short id (e.g. ``err_001``). Stable within a "
            "browser session so log readers can correlate repeat reports."
        ),
    )
    message: str = Field(
        ...,
        max_length=2048,
        description="Anonymised error message.",
    )
    stack_lines: list[str] = Field(
        default_factory=list,
        max_length=128,
        description="Anonymised stack trace, already split into lines.",
    )
    user_agent: str = Field(
        default="",
        max_length=512,
        description="navigator.userAgent of the originating browser.",
    )
    path: str = Field(
        default="",
        max_length=512,
        description="Pathname of the page that produced the error (no query string).",
    )
