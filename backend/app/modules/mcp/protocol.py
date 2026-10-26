# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The JSON-RPC 2.0 envelope of the Model Context Protocol, server side.

Only the subset a tool server needs: ``initialize``, ``notifications/initialized``,
``ping``, ``tools/list`` and ``tools/call``, over the streamable HTTP transport
answering every POST with a single ``application/json`` body (the transport
allows that instead of an event stream, and nothing here streams). The server
keeps no session state, so no ``Mcp-Session-Id`` is issued.

Written here rather than taken from the reference SDK: the SDK brings its own
ASGI app, session manager and event-stream stack for a surface of five methods,
which is weight the 3 GB server target does not need and a second request
pipeline beside FastAPI's auth, session and audit dependencies.

The module is transport- and database-free: :class:`Dispatcher` maps method
names to coroutines and turns one parsed message (or a batch) into responses.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

# Newest first; the first entry is what an unknown client version is offered.
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
# Implementation-defined server errors live in -32000..-32099.
RATE_LIMITED = -32001


class JsonRpcError(Exception):
    """A protocol-level error that becomes a JSON-RPC ``error`` member."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def negotiate_version(requested: Any) -> str:
    """The version to answer ``initialize`` with: the client's when supported, else the newest."""
    if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return LATEST_PROTOCOL_VERSION


def result_message(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    """A JSON-RPC success response."""
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def error_message(msg_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    """A JSON-RPC error response (``id`` is null when the request id could not be read)."""
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": error}


def _valid_id(value: Any) -> bool:
    # JSON-RPC allows string or number ids; MCP forbids null. bool is an int subclass and is not an id.
    return isinstance(value, str) or (isinstance(value, int | float) and not isinstance(value, bool))


Method = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class Dispatcher:
    """Routes JSON-RPC messages to method coroutines for one HTTP request."""

    def __init__(self, methods: dict[str, Method]) -> None:
        self.methods = methods
        self.rate_limited = False

    async def handle(self, message: Any) -> dict[str, Any] | None:
        """Answer one message; None for a notification or a client response (nothing to send back)."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return error_message(None, INVALID_REQUEST, "Not a JSON-RPC 2.0 message.")
        method = message.get("method")
        has_id = "id" in message
        if method is None:
            # A response to a server request; this server sends none, so accept and ignore it.
            if has_id and ("result" in message or "error" in message):
                return None
            return error_message(None, INVALID_REQUEST, "Missing 'method'.")
        if not isinstance(method, str):
            return error_message(message.get("id") if has_id else None, INVALID_REQUEST, "'method' must be a string.")
        if not has_id:
            # Notifications get no answer, known or not (notifications/initialized, cancelled, ...).
            return None
        msg_id = message["id"]
        if not _valid_id(msg_id):
            return error_message(None, INVALID_REQUEST, "'id' must be a string or a number.")
        params = message.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return error_message(msg_id, INVALID_PARAMS, "'params' must be an object.")
        handler = self.methods.get(method)
        if handler is None:
            return error_message(msg_id, METHOD_NOT_FOUND, f"Method not found: {method}")
        try:
            return result_message(msg_id, await handler(params))
        except JsonRpcError as exc:
            if exc.code == RATE_LIMITED:
                self.rate_limited = True
            return error_message(msg_id, exc.code, exc.message, exc.data)
        except Exception:
            logger.exception("mcp: method %s failed", method)
            return error_message(msg_id, INTERNAL_ERROR, "Internal error.")

    async def handle_body(self, body: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Answer a parsed POST body: one message or a batch. None when nothing needs an answer."""
        if isinstance(body, list):
            if not body:
                return error_message(None, INVALID_REQUEST, "Empty batch.")
            answers = [a for a in [await self.handle(m) for m in body] if a is not None]
            return answers or None
        return await self.handle(body)
