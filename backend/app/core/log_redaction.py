# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Keep secrets that ride in a URL out of the server's own log lines.

Several URLs still carry a credential as a query value: the calendar feed
(``.ics?token=``), the portal magic link, and, for one release, the realtime
sockets of a browser running the previous frontend (see
:mod:`app.core.ws_auth`). uvicorn writes the path with its query string twice:
the access log (``uvicorn.access``) and the WebSocket ``[accepted]`` line
(``uvicorn.error``, which is logged even when the access log is off). Both
lines are masked here.

The filter edits ``record.args`` element by element and keeps the tuple's
shape. uvicorn's ``AccessFormatter`` unpacks those args as a fixed five-tuple,
so a filter that pre-formatted the message and cleared ``args`` would break
every access line rather than mask it.

This cannot reach a reverse proxy's access log, which is why the sockets no
longer put the token in the URL at all.
"""

from __future__ import annotations

import logging
import re
from typing import Any

#: Query keys whose value is a credential.
_SECRET_QUERY_KEYS = ("token", "access_token", "ticket")

_SECRET_QUERY_RE = re.compile(
    r"(?P<key>(?:[?&]|%3F|%26)(?:" + "|".join(_SECRET_QUERY_KEYS) + r")=)[^&\s\"'#]+",
    re.IGNORECASE,
)

REDACTED = "[redacted]"

#: The loggers uvicorn writes request paths to.
URL_LOGGERS = ("uvicorn.access", "uvicorn.error")


def redact_secret_query(text: str) -> str:
    """Replace the value of every credential query parameter in ``text``."""
    return _SECRET_QUERY_RE.sub(lambda m: m.group("key") + REDACTED, text)


def _redact(value: Any) -> Any:
    if isinstance(value, str) and "=" in value:
        return redact_secret_query(value)
    return value


class SecretQueryRedactionFilter(logging.Filter):
    """Mask credential query values in a record without changing its shape."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(_redact(a) for a in args)
        elif isinstance(args, dict):
            record.args = {k: _redact(v) for k, v in args.items()}
        return True


def install_url_redaction() -> None:
    """Attach the filter to uvicorn's loggers, once each.

    Called from ``configure_logging``, which runs after uvicorn has configured
    its own loggers; ``dictConfig`` replaces handlers but leaves a logger's
    filters alone, so a later reconfiguration does not undo this.
    """
    for name in URL_LOGGERS:
        target = logging.getLogger(name)
        if not any(isinstance(f, SecretQueryRedactionFilter) for f in target.filters):
            target.addFilter(SecretQueryRedactionFilter())
