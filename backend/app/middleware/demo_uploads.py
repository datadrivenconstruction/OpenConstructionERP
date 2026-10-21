# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Refuse file uploads on the public hosted demo.

Off by default. The hosted demo turns it on with ``OE_DEMO_BLOCK_UPLOADS=true``
(``demo_block_uploads`` on :class:`app.config.Settings`). Visitors there work on
the seeded example projects only: nobody reviews what a stranger uploads to a
shared public box, so the box does not accept files at all.

A request counts as an upload when it carries a body as ``multipart/form-data``
or ``application/octet-stream``. Every file endpoint in the application takes
one of the two, and no JSON call does, so sign-in, search and ordinary edits
are untouched. The check reads only the headers and refuses before a single
body byte is read.

The refusal contract mirrors :mod:`app.core.demo_read_only`::

    HTTP 403
    {"detail": {"error": "demo_uploads_disabled", "message": "<plain English>"}}

The frontend matches on ``error`` and shows its own translated text.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Receive, Scope, Send

DEMO_UPLOADS_ERROR = "demo_uploads_disabled"

DEMO_UPLOADS_MESSAGE = (
    "File uploads are turned off on the public demo. Please use the demo projects and their example data. "
    "To work with your own files, install the platform on your own computer or server."
)

_UPLOAD_TYPES = (b"multipart/form-data", b"application/octet-stream")
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


def is_upload_request(scope: Scope) -> bool:
    """Return whether an HTTP scope carries a file body.

    Args:
        scope: The ASGI HTTP connection scope.

    Returns:
        True for a POST, PUT or PATCH whose ``Content-Type`` is multipart or a
        raw octet stream.
    """
    if scope.get("method", "").upper() not in _BODY_METHODS:
        return False
    for key, value in scope.get("headers", []):
        if key == b"content-type":
            return value.strip().lower().startswith(_UPLOAD_TYPES)
    return False


class DemoUploadBlockMiddleware:
    """Answer 403 to every upload when the deployment is the public demo.

    Args:
        app: The wrapped ASGI application.
        enabled: When False the middleware passes every request through.
    """

    def __init__(self, app: ASGIApp, *, enabled: bool) -> None:
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] != "http" or not is_upload_request(scope):
            await self.app(scope, receive, send)
            return
        body = json.dumps({"detail": {"error": DEMO_UPLOADS_ERROR, "message": DEMO_UPLOADS_MESSAGE}}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
