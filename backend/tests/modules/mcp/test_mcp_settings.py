# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The settings surface and the ``mcp`` validation rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.core.validation.engine import validation_engine
from app.modules.mcp.validators import MCP_RULE_SET
from tests.modules.mcp.conftest import API_PREFIX, build_app, http_client, make_user

# ── Settings routes ─────────────────────────────────────────────────────────


async def test_settings_start_disabled_and_can_be_switched_on_within_bounds(session) -> None:
    user = await make_user(session)
    async with http_client(build_app(session, caller_id=user.id)) as client:
        initial = (await client.get(f"{API_PREFIX}/settings/")).json()
        assert initial["enabled"] is False
        assert initial["rate_limit_per_minute"] == 60
        assert "2025-06-18" in initial["protocol_versions"]

        on = await client.put(f"{API_PREFIX}/settings/", json={"enabled": True, "rate_limit_per_minute": 120})
        assert on.status_code == 200
        assert on.json()["enabled"] is True
        assert on.json()["rate_limit_per_minute"] == 120

        too_fast = await client.put(f"{API_PREFIX}/settings/", json={"rate_limit_per_minute": 100000})
        assert too_fast.status_code == 422


async def test_token_secret_is_shown_once_and_revoking_another_persons_token_is_404(session) -> None:
    owner = await make_user(session)
    other = await make_user(session)
    async with http_client(build_app(session, caller_id=owner.id)) as client:
        created = await client.post(f"{API_PREFIX}/tokens/", json={"name": "IDE", "can_propose": False})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["token"].startswith("oe_")
        assert body["can_propose"] is False
        assert body["expires_at"] is not None
        listed = (await client.get(f"{API_PREFIX}/tokens/")).json()["items"]
        assert [t["id"] for t in listed] == [body["id"]]
        assert "token" not in listed[0]
        token_id = body["id"]

    async with http_client(build_app(session, caller_id=other.id)) as client:
        assert (await client.delete(f"{API_PREFIX}/tokens/{token_id}/")).status_code == 404
        assert (await client.get(f"{API_PREFIX}/tokens/")).json()["items"] == []


async def test_general_api_keys_are_not_listed_or_revocable_as_mcp_tokens(session) -> None:
    from app.config import get_settings
    from app.modules.users.schemas import APIKeyCreate
    from app.modules.users.service import UserService

    user = await make_user(session)
    general = await UserService(session, get_settings()).create_api_key(user.id, APIKeyCreate(name="CI key"))
    async with http_client(build_app(session, caller_id=user.id)) as client:
        assert (await client.get(f"{API_PREFIX}/tokens/")).json()["items"] == []
        assert (await client.delete(f"{API_PREFIX}/tokens/{general.id}/")).status_code == 404


async def test_tool_catalogue_and_validation_report_are_served(session) -> None:
    user = await make_user(session)
    async with http_client(build_app(session, caller_id=user.id)) as client:
        tools = (await client.get(f"{API_PREFIX}/tools/")).json()
        kinds = {t["kind"] for t in tools}
        assert kinds == {"read", "propose"}
        await client.put(f"{API_PREFIX}/settings/", json={"enabled": True})
        report = (await client.get(f"{API_PREFIX}/validation/")).json()
        keys = {f["key"] for f in report["findings"]}
        assert "mcp.validation.enabled_without_token" in keys


async def test_settings_routes_need_a_signed_in_caller(session) -> None:
    async with http_client(build_app(session)) as client:
        resp = await client.get(f"{API_PREFIX}/settings/")
        assert resp.status_code in (401, 403)


# ── Validation rules ────────────────────────────────────────────────────────


def _token(**kw):
    now = datetime.now(UTC)
    base = {
        "id": uuid4(),
        "name": "Client",
        "key_prefix": "oe_abcdefghi",
        "is_active": True,
        "expires_at": now + timedelta(days=30),
        "last_used_at": now - timedelta(days=1),
        "created_at": now - timedelta(days=5),
    }
    base.update(kw)
    return SimpleNamespace(**base)


async def _run(settings, tokens, denied: int = 0):
    report = await validation_engine.validate(
        data={"now": datetime.now(UTC), "settings": settings, "tokens": tokens, "denied_last_24h": denied},
        rule_sets=[MCP_RULE_SET],
    )
    return {r.rule_id for r in report.results if not r.passed}, report


async def test_a_clean_setup_passes_every_rule() -> None:
    failed, report = await _run(SimpleNamespace(enabled=True, rate_limit_per_minute=60), [_token()])
    assert failed == set()
    assert report.unsupported_rule_sets == []


async def test_each_rule_fires_on_its_own_problem() -> None:
    now = datetime.now(UTC)
    settings = SimpleNamespace(enabled=True, rate_limit_per_minute=5000)
    tokens = [
        _token(expires_at=None),
        _token(last_used_at=now - timedelta(days=120)),
        _token(last_used_at=None, created_at=now - timedelta(days=45)),
        *[_token() for _ in range(4)],
    ]
    failed, _ = await _run(settings, tokens, denied=12)
    assert failed == {
        "mcp.rate_limit_range",
        "mcp.token_without_expiry",
        "mcp.token_unused",
        "mcp.too_many_tokens",
        "mcp.denied_calls",
    }


async def test_revoked_and_expired_tokens_do_not_count_and_enabled_without_token_is_flagged() -> None:
    now = datetime.now(UTC)
    tokens = [_token(is_active=False, expires_at=None), _token(expires_at=now - timedelta(days=1))]
    failed, _ = await _run(SimpleNamespace(enabled=True, rate_limit_per_minute=60), tokens)
    assert failed == {"mcp.enabled_without_token"}
    failed_off, _ = await _run(SimpleNamespace(enabled=False, rate_limit_per_minute=60), [])
    assert failed_off == set()
