# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""uvicorn's log lines do not carry a credential from a URL.

The realtime sockets took the access token as ``?token=``, and uvicorn wrote
it twice: on the WebSocket ``[accepted]`` line (``uvicorn.error``, logged even
with the access log off, which is how the desktop CLI runs) and in the access
log. The sockets no longer put it there, but the calendar feed, the portal
link and a browser still running the previous frontend do, so both lines are
masked.

Tested through ``configure_logging`` and uvicorn's own formatter, because the
access formatter unpacks the record's arguments as a fixed tuple: a filter
that got the shape wrong would not leak the token, it would break every
access line, and only formatting a real record shows the difference.
"""

from __future__ import annotations

import io
import logging

import pytest

TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl"


@pytest.fixture
def configured() -> None:
    from app.config import get_settings
    from app.main import configure_logging

    configure_logging(get_settings())


def _capture(logger_name: str, formatter: logging.Formatter) -> tuple[logging.Logger, io.StringIO, logging.Handler]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logger = logging.getLogger(logger_name)
    logger.addHandler(handler)
    return logger, stream, handler


def test_the_access_line_is_masked_and_still_formats(configured: None) -> None:
    from uvicorn.logging import AccessFormatter

    logger, stream, handler = _capture(
        "uvicorn.access",
        AccessFormatter(fmt='%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False),
    )
    try:
        logger.setLevel(logging.INFO)
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:5000",
            "GET",
            f"/api/v1/integrations/calendar/p.ics/?token={TOKEN}&x=1",
            "1.1",
            200,
        )
    finally:
        logger.removeHandler(handler)
    line = stream.getvalue()
    assert TOKEN not in line
    assert "token=[redacted]&x=1" in line
    assert " 200" in line


def test_the_websocket_accepted_line_is_masked(configured: None) -> None:
    logger, stream, handler = _capture("uvicorn.error", logging.Formatter("%(message)s"))
    try:
        logger.setLevel(logging.INFO)
        logger.info(
            '%s - "WebSocket %s" [accepted]',
            "127.0.0.1:5000",
            f"/api/v1/notifications/ws/?token={TOKEN}",
        )
    finally:
        logger.removeHandler(handler)
    line = stream.getvalue()
    assert TOKEN not in line
    assert "/api/v1/notifications/ws/?token=[redacted]" in line


def test_a_query_without_a_credential_is_left_alone() -> None:
    from app.core.log_redaction import redact_secret_query

    assert redact_secret_query("/api/v1/items/?page=2&tokenizer=x") == "/api/v1/items/?page=2&tokenizer=x"
    assert redact_secret_query("/p?access_token=abc") == "/p?access_token=[redacted]"
