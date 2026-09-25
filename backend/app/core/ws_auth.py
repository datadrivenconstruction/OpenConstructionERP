# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Getting a WebSocket's access token out of the URL.

The browser ``WebSocket`` API cannot set an ``Authorization`` header, so the
three realtime sockets (notifications, global presence, collaboration-lock
presence) took the JWT as ``?token=`` on the upgrade URL. A URL is the one part
of a request every layer writes down: uvicorn prints it on the WebSocket
``[accepted]`` line (``uvicorn.error``, logged even with the access log off),
the access log prints it again, and an nginx or other reverse proxy in front
prints it in its own access log, which no code in this process can reach. Each
of those lines held a working session token for as long as the token lived.

So the token now travels in the first frame after the handshake::

    client -> {"type": "auth", "token": "<access token>"}

The server accepts the upgrade, reads exactly one frame, and authenticates it
before it joins any hub or sends anything. A client that sends nothing, or
anything other than that frame, within :data:`WS_AUTH_TIMEOUT_SECONDS` is
closed with 1008 like any other refusal.

The ``?token=`` spelling is still read for one release, so a browser holding a
cached copy of the previous frontend keeps working until it reloads. It is the
old leak, which is why :mod:`app.core.log_redaction` masks ``token=`` values in
the uvicorn lines regardless. Remove the fallback in the release after 18.1.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

#: How long an accepted but not yet authenticated socket may stay open.
WS_AUTH_TIMEOUT_SECONDS = 10.0

#: The ``type`` of the frame that carries the token.
WS_AUTH_FRAME_TYPE = "auth"


async def receive_auth_token(websocket: WebSocket, *, timeout: float | None = None) -> str | None:
    """Read the authentication frame from an accepted socket.

    Returns the token, or ``None`` when the first frame is missing, late,
    malformed or of another type. The caller answers ``None`` exactly as it
    answers a rejected token: a 1008 close, having joined nothing.

    Args:
        websocket: A socket the caller has already accepted.
        timeout: Seconds to wait for the frame; :data:`WS_AUTH_TIMEOUT_SECONDS`
            (read at call time) when omitted.
    """
    wait = WS_AUTH_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        message = await asyncio.wait_for(websocket.receive(), timeout=wait)
    except TimeoutError:
        return None
    if message.get("type") != "websocket.receive":
        return None
    raw = message.get("text")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("type") != WS_AUTH_FRAME_TYPE:
        return None
    token = data.get("token")
    if not isinstance(token, str) or not token:
        return None
    return token


async def resolve_socket_token(websocket: WebSocket, query_token: str | None) -> tuple[str | None, bool]:
    """The token for this handshake, and whether the socket is already accepted.

    A ``?token=`` (the previous frontend) is used as given and the socket is
    left unaccepted, so the caller keeps its close-before-accept behaviour for
    that path. Otherwise the socket is accepted and the token read from the
    first frame.
    """
    if query_token:
        return query_token, False
    await websocket.accept()
    return await receive_auth_token(websocket), True


async def refuse_socket(websocket: WebSocket, *, code: int, reason: str) -> None:
    """Close a socket that was refused, whether or not its client is still there.

    Once the upgrade is accepted to read the auth frame, a client that gave up
    has already gone by the time the refusal is sent, and sending a close to a
    gone client raises. The refusal is the outcome either way.
    """
    try:
        await websocket.close(code=code, reason=reason)
    except (WebSocketDisconnect, RuntimeError, OSError):
        logger.debug("WebSocket closed by its client before the refusal (%s)", reason)
