# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Global request-body-size backstop middleware.

``MaxBodySizeMiddleware`` is a coarse safety net above the per-endpoint upload
caps: it rejects an absurdly large request body before an endpoint can read it
unbounded and OOM the single worker. These tests drive the pure-ASGI middleware
directly with fabricated scope/receive/send, so they need no server, no
database, and run under the py3.11 DB-free lane.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.middleware.body_size_limit import MaxBodySizeMiddleware

Message = dict[str, object]


def _http_scope(headers: list[tuple[bytes, bytes]] | None = None) -> dict[str, object]:
    return {"type": "http", "method": "POST", "path": "/x", "headers": headers or []}


def _make_receive(chunks: list[bytes]) -> Callable[[], Awaitable[Message]]:
    """Return a receive() that emits one http.request per chunk, then disconnect."""
    events: list[Message] = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    events.append({"type": "http.disconnect"})
    iterator = iter(events)

    async def receive() -> Message:
        return next(iterator)

    return receive


def _collect_send() -> tuple[list[Message], Callable[[Message], Awaitable[None]]]:
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    return messages, send


class _BodyReadingApp:
    """Inner app that drains the request body, then returns 200 with its size."""

    def __init__(self) -> None:
        self.called = False
        self.received = 0

    async def __call__(
        self,
        scope: dict[str, object],
        receive: Callable[[], Awaitable[Message]],
        send: Callable[[Message], Awaitable[None]],
    ) -> None:
        self.called = True
        while True:
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                assert isinstance(body, bytes)
                self.received += len(body)
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _status_of(messages: list[Message]) -> int | None:
    for message in messages:
        if message["type"] == "http.response.start":
            status = message["status"]
            assert isinstance(status, int)
            return status
    return None


async def test_rejects_on_declared_content_length_over_ceiling() -> None:
    app = _BodyReadingApp()
    mw = MaxBodySizeMiddleware(app, max_body_bytes=100)
    scope = _http_scope([(b"content-length", b"101")])
    messages, send = _collect_send()

    await mw(scope, _make_receive([b"x" * 101]), send)

    assert _status_of(messages) == 413
    assert app.called is False  # rejected before the endpoint ran


async def test_allows_declared_content_length_at_ceiling() -> None:
    app = _BodyReadingApp()
    mw = MaxBodySizeMiddleware(app, max_body_bytes=100)
    scope = _http_scope([(b"content-length", b"100")])
    messages, send = _collect_send()

    await mw(scope, _make_receive([b"x" * 100]), send)

    assert _status_of(messages) == 200
    assert app.called is True
    assert app.received == 100


async def test_rejects_streamed_body_without_content_length() -> None:
    # No Content-Length header: the running byte count must trip the ceiling as
    # the endpoint drains the body, and (since the endpoint has not responded
    # yet) the middleware injects a 413.
    app = _BodyReadingApp()
    mw = MaxBodySizeMiddleware(app, max_body_bytes=100)
    scope = _http_scope([])  # chunked / no content-length
    messages, send = _collect_send()

    await mw(scope, _make_receive([b"x" * 60, b"x" * 60]), send)

    assert _status_of(messages) == 413


async def test_allows_small_body_without_content_length() -> None:
    app = _BodyReadingApp()
    mw = MaxBodySizeMiddleware(app, max_body_bytes=100)
    scope = _http_scope([])
    messages, send = _collect_send()

    await mw(scope, _make_receive([b"x" * 40, b"x" * 40]), send)

    assert _status_of(messages) == 200
    assert app.received == 80


async def test_zero_ceiling_disables_the_check() -> None:
    app = _BodyReadingApp()
    mw = MaxBodySizeMiddleware(app, max_body_bytes=0)
    scope = _http_scope([(b"content-length", b"999999999")])
    messages, send = _collect_send()

    await mw(scope, _make_receive([b"x" * 10]), send)

    assert _status_of(messages) == 200
    assert app.called is True


async def test_unparseable_content_length_falls_back_to_streaming() -> None:
    # A garbage Content-Length must not crash the middleware; it falls through
    # to the streaming counter, which here stays under the ceiling.
    app = _BodyReadingApp()
    mw = MaxBodySizeMiddleware(app, max_body_bytes=100)
    scope = _http_scope([(b"content-length", b"not-a-number")])
    messages, send = _collect_send()

    await mw(scope, _make_receive([b"x" * 10]), send)

    assert _status_of(messages) == 200


async def test_non_http_scope_passes_through() -> None:
    seen: list[str] = []

    async def inner(
        scope: dict[str, object],
        receive: Callable[[], Awaitable[Message]],
        send: Callable[[Message], Awaitable[None]],
    ) -> None:
        assert isinstance(scope["type"], str)
        seen.append(scope["type"])

    mw = MaxBodySizeMiddleware(inner, max_body_bytes=100)
    messages, send = _collect_send()

    await mw({"type": "lifespan"}, _make_receive([]), send)

    assert seen == ["lifespan"]
