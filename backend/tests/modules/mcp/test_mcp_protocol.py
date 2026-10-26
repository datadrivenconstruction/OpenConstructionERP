# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The JSON-RPC envelope on its own: no database, no HTTP."""

from __future__ import annotations

from typing import Any

from app.modules.mcp.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    RATE_LIMITED,
    Dispatcher,
    JsonRpcError,
    negotiate_version,
)


async def _echo(params: dict[str, Any]) -> dict[str, Any]:
    return {"echo": params}


async def _boom(params: dict[str, Any]) -> dict[str, Any]:
    raise RuntimeError("secret detail")


async def _limited(params: dict[str, Any]) -> dict[str, Any]:
    raise JsonRpcError(RATE_LIMITED, "Rate limit exceeded.")


def _dispatcher() -> Dispatcher:
    return Dispatcher({"echo": _echo, "boom": _boom, "limited": _limited})


def test_version_negotiation_echoes_a_supported_version_and_offers_the_newest_otherwise() -> None:
    assert negotiate_version("2025-03-26") == "2025-03-26"
    assert negotiate_version("1999-01-01") == LATEST_PROTOCOL_VERSION
    assert negotiate_version(None) == LATEST_PROTOCOL_VERSION


async def test_a_request_gets_its_result_under_its_own_id() -> None:
    answer = await _dispatcher().handle({"jsonrpc": "2.0", "id": "a1", "method": "echo", "params": {"x": 1}})
    assert answer == {"jsonrpc": "2.0", "id": "a1", "result": {"echo": {"x": 1}}}


async def test_notifications_and_client_responses_get_no_answer() -> None:
    d = _dispatcher()
    assert await d.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert await d.handle({"jsonrpc": "2.0", "method": "no/such/notification"}) is None
    assert await d.handle({"jsonrpc": "2.0", "id": 7, "result": {}}) is None


async def test_malformed_messages_are_invalid_requests() -> None:
    d = _dispatcher()
    for message in ([], "x", {"id": 1, "method": "echo"}, {"jsonrpc": "1.0", "id": 1, "method": "echo"}):
        answer = await d.handle(message)
        assert answer is not None
        assert answer["error"]["code"] == INVALID_REQUEST
    null_id = await d.handle({"jsonrpc": "2.0", "id": None, "method": "echo"})
    assert null_id["error"]["code"] == INVALID_REQUEST
    bool_id = await d.handle({"jsonrpc": "2.0", "id": True, "method": "echo"})
    assert bool_id["error"]["code"] == INVALID_REQUEST


async def test_unknown_method_and_bad_params_have_their_own_codes() -> None:
    d = _dispatcher()
    missing = await d.handle({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
    assert missing["error"]["code"] == METHOD_NOT_FOUND
    bad = await d.handle({"jsonrpc": "2.0", "id": 2, "method": "echo", "params": [1, 2]})
    assert bad["error"]["code"] == INVALID_PARAMS


async def test_an_unexpected_failure_is_an_internal_error_without_the_exception_text() -> None:
    answer = await _dispatcher().handle({"jsonrpc": "2.0", "id": 1, "method": "boom"})
    assert answer["error"]["code"] == INTERNAL_ERROR
    assert "secret" not in answer["error"]["message"]


async def test_rate_limit_errors_are_flagged_for_the_transport() -> None:
    d = _dispatcher()
    answer = await d.handle({"jsonrpc": "2.0", "id": 1, "method": "limited"})
    assert answer["error"]["code"] == RATE_LIMITED
    assert d.rate_limited is True


async def test_a_batch_answers_requests_only_and_an_empty_batch_is_invalid() -> None:
    d = _dispatcher()
    answers = await d.handle_body(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "echo"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "nope"},
        ]
    )
    assert isinstance(answers, list)
    assert [a["id"] for a in answers] == [1, 2]
    assert await d.handle_body([{"jsonrpc": "2.0", "method": "notifications/initialized"}]) is None
    empty = await d.handle_body([])
    assert empty["error"]["code"] == INVALID_REQUEST
