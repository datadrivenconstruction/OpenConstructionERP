# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Partner API keys: issuing rules, scopes, address allow-list, per-key limits, rotation.

Runs on an in-memory SQLite database of its own, so it needs neither the shared
PostgreSQL fixtures nor a running app.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.core.audit_log  # noqa: F401 - registers the audit table the service writes to
from app import dependencies as deps
from app.core.permissions import Role, permission_registry
from app.core.rate_limiter import RateLimiter
from app.dependencies import RequirePermissionOrApiKey
from app.modules.users import validators as rules
from app.modules.users.models import APIKey, User
from app.modules.users.repository import APIKeyRepository
from app.modules.users.schemas import APIKeyCreate
from app.modules.users.service import UserService, generate_api_key
from tests.modules._partner_db import partner_engine

PERM_A = "partnertest.read"
PERM_B = "partnertest.write"


@pytest.fixture(autouse=True)
def _registry():
    permission_registry.register_module_permissions("partnertest", {PERM_A: Role.VIEWER, PERM_B: Role.EDITOR})
    yield
    permission_registry.unregister_module_permissions("partnertest")


@pytest_asyncio.fixture
async def factory(monkeypatch):
    async with partner_engine([User.__table__, APIKey.__table__, _audit_table()]) as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(deps, "async_session_factory", maker)
        yield maker


def _audit_table():
    from app.core.audit_log import ActivityLog

    return ActivityLog.__table__


async def _user(maker, role: str = "editor") -> uuid.UUID:
    async with maker() as s:
        user = User(email=f"{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role=role, is_active=True)
        s.add(user)
        await s.commit()
        return user.id


async def _key(maker, user_id, **fields) -> tuple[str, uuid.UUID]:
    full, key_hash, prefix = generate_api_key()
    async with maker() as s:
        row = APIKey(
            user_id=user_id,
            name=fields.pop("name", uuid.uuid4().hex[:6]),
            key_hash=key_hash,
            key_prefix=prefix,
            **fields,
        )
        s.add(row)
        await s.commit()
        return full, row.id


class _Request:
    def __init__(self, key: str | None, ip: str = "203.0.113.9") -> None:
        self.headers = {"x-api-key": key} if key else {}
        self.client = SimpleNamespace(host=ip)


async def _resolve(key: str, ip: str = "203.0.113.9"):
    return await deps.resolve_api_key_principal(_Request(key, ip))


# ── Pure rules ────────────────────────────────────────────────────────────


def test_scope_catalogue_comes_from_the_registry():
    rows = {r["name"]: r for r in rules.scope_catalogue()}
    assert rows[PERM_A]["module"] == "partnertest"
    assert rows[PERM_A]["action"] == "read"
    assert rows[PERM_A]["i18n_key"] == "developer.scope.partnertest.read"
    assert rows[PERM_B]["min_role"] == "editor"


def test_unknown_scope_is_rejected_and_known_ones_deduplicated():
    assert rules.validate_scopes([PERM_A, PERM_A, PERM_B]) == [PERM_A, PERM_B]
    with pytest.raises(rules.ApiKeyRuleError) as exc:
        rules.validate_scopes([PERM_A, "nope.nothing"])
    assert exc.value.code == "api_key.unknown_scope"


def test_expiry_must_be_future_and_within_two_years():
    now = datetime(2026, 11, 3, tzinfo=UTC)
    rules.validate_expiry(None, now)
    rules.validate_expiry(now + timedelta(days=1), now)
    rules.validate_expiry(now + timedelta(days=730), now)
    with pytest.raises(rules.ApiKeyRuleError) as past:
        rules.validate_expiry(now - timedelta(seconds=1), now)
    assert past.value.code == "api_key.expiry_in_past"
    with pytest.raises(rules.ApiKeyRuleError) as far:
        rules.validate_expiry(now + timedelta(days=731), now)
    assert far.value.code == "api_key.expiry_too_far"


def test_name_unique_and_cap():
    rules.validate_name_unique("ci", ["other"])
    with pytest.raises(rules.ApiKeyRuleError) as taken:
        rules.validate_name_unique(" CI ", ["ci"])
    assert taken.value.status == 409
    rules.validate_active_cap(rules.MAX_ACTIVE_KEYS_PER_USER - 1)
    with pytest.raises(rules.ApiKeyRuleError):
        rules.validate_active_cap(rules.MAX_ACTIVE_KEYS_PER_USER)


@pytest.mark.parametrize(
    ("ip", "cidrs", "expected"),
    [
        ("10.1.2.3", [], True),
        ("10.1.2.3", ["10.0.0.0/8"], True),
        ("11.1.2.3", ["10.0.0.0/8"], False),
        ("2001:db8::5", ["2001:db8::/32"], True),
        ("2001:db9::5", ["2001:db8::/32"], False),
        ("2001:db8::5", ["10.0.0.0/8"], False),
        ("10.1.2.3", ["2001:db8::/32"], False),
        ("::ffff:10.1.2.3", ["10.0.0.0/8"], True),
        ("[2001:db8::1]", ["2001:db8::/32"], True),
        (None, ["10.0.0.0/8"], False),
        ("not-an-ip", ["10.0.0.0/8"], False),
    ],
)
def test_ip_allowed(ip, cidrs, expected):
    assert rules.ip_allowed(ip, cidrs) is expected


# ── Request schema ────────────────────────────────────────────────────────


@pytest.mark.parametrize("limit", [0, -1, 6001])
def test_rate_limit_out_of_range_is_rejected(limit):
    with pytest.raises(ValidationError):
        APIKeyCreate(name="k", rate_limit_per_min=limit)


@pytest.mark.parametrize("limit", [1, 6000])
def test_rate_limit_bounds_are_accepted(limit):
    assert APIKeyCreate(name="k", rate_limit_per_min=limit).rate_limit_per_min == limit


def test_cidrs_are_validated_normalised_and_capped():
    data = APIKeyCreate(name="k", allowed_cidrs=["10.0.0.5/24", "10.0.0.0/24", "2001:db8::1/64"])
    assert data.allowed_cidrs == ["10.0.0.0/24", "2001:db8::/64"]
    with pytest.raises(ValidationError):
        APIKeyCreate(name="k", allowed_cidrs=["300.1.1.1/8"])
    with pytest.raises(ValidationError):
        APIKeyCreate(name="k", allowed_cidrs=[f"10.{i}.0.0/16" for i in range(21)])


def test_only_one_expiry_form():
    with pytest.raises(ValidationError):
        APIKeyCreate(name="k", expires_in_days=5, expires_at=datetime.now(UTC) + timedelta(days=1))


# ── Resolution: expiry, scopes, address, limits, usage ─────────────────────


async def test_expired_key_is_401(factory):
    uid = await _user(factory)
    key, _ = await _key(factory, uid, expires_at=datetime.now(UTC) - timedelta(minutes=1))
    with pytest.raises(HTTPException) as exc:
        await _resolve(key)
    assert exc.value.status_code == 401


async def test_scope_deny_is_403_and_allow_passes(factory):
    uid = await _user(factory, role="admin")
    key, _ = await _key(factory, uid, permissions=[PERM_A])
    principal = await _resolve(key)
    gate_b = RequirePermissionOrApiKey(PERM_B)
    with pytest.raises(HTTPException) as exc:
        gate_b._authorize("admin", None, principal.scopes)
    assert exc.value.status_code == 403
    RequirePermissionOrApiKey(PERM_A)._authorize("admin", None, principal.scopes)


async def test_gate_sets_rate_limit_headers(factory):
    uid = await _user(factory)
    key, _ = await _key(factory, uid, rate_limit_per_min=5)
    response = SimpleNamespace(headers={})
    gate = RequirePermissionOrApiKey(PERM_A)
    assert await gate(_Request(key), None, response) == str(uid)
    assert response.headers == {"X-RateLimit-Limit": "5", "X-RateLimit-Remaining": "4"}


async def test_cidr_deny_and_allow_ipv4_and_ipv6(factory):
    uid = await _user(factory)
    v4, _ = await _key(factory, uid, allowed_cidrs=["203.0.113.0/24"])
    v6, _ = await _key(factory, uid, allowed_cidrs=["2001:db8::/32"])
    assert (await _resolve(v4, "203.0.113.9")).user.id == uid
    with pytest.raises(HTTPException) as denied:
        await _resolve(v4, "198.51.100.7")
    assert denied.value.status_code == 403
    assert denied.value.detail == "api_key.ip_denied"
    assert (await _resolve(v6, "2001:db8::77")).user.id == uid
    with pytest.raises(HTTPException) as denied6:
        await _resolve(v6, "2001:db9::77")
    assert denied6.value.detail == "api_key.ip_denied"
    with pytest.raises(HTTPException):
        await _resolve(v6, "203.0.113.9")  # an IPv4 client is outside an IPv6-only list


async def test_per_key_limit_returns_429_with_retry_after_and_spares_other_keys(factory):
    uid = await _user(factory)
    tight, _ = await _key(factory, uid, rate_limit_per_min=2)
    other, _ = await _key(factory, uid)
    await _resolve(tight)
    await _resolve(tight)
    with pytest.raises(HTTPException) as exc:
        await _resolve(tight)
    assert exc.value.status_code == 429
    assert 1 <= int(exc.value.headers["Retry-After"]) <= 60
    assert exc.value.headers["X-RateLimit-Limit"] == "2"
    assert exc.value.headers["X-RateLimit-Remaining"] == "0"
    # a key with no limit of its own keeps using the global one
    for _ in range(5):
        await _resolve(other)


async def test_usage_is_counted_once_per_allowed_request(factory):
    uid = await _user(factory)
    key, key_id = await _key(factory, uid, rate_limit_per_min=3, allowed_cidrs=["203.0.113.0/24"])
    with pytest.raises(HTTPException):
        await _resolve(key, "198.51.100.1")  # denied: not counted
    for _ in range(3):
        await _resolve(key)
    with pytest.raises(HTTPException):
        await _resolve(key)  # limited: not counted
    async with factory() as s:
        row = await s.get(APIKey, key_id)
        assert row.request_count == 3
        assert row.last_used_at is not None


def test_limiter_override_and_retry_after():
    limiter = RateLimiter(max_requests=100, window_seconds=60)
    assert limiter.is_allowed("k", 1) == (True, 0)
    assert limiter.is_allowed("k", 1) == (False, 0)
    assert 1 <= limiter.retry_after("k") <= 61
    assert limiter.is_allowed("other", 1)[0] is True


# ── Issuing and rotation ───────────────────────────────────────────────────


def _service(session) -> UserService:
    return UserService(session, settings=None)  # type: ignore[arg-type]


async def test_create_enforces_rules(factory):
    uid = await _user(factory)
    async with factory() as s:
        svc = _service(s)
        created = await svc.create_api_key(
            uid, APIKeyCreate(name="ci", permissions=[PERM_A], rate_limit_per_min=10, allowed_cidrs=["10.0.0.0/8"])
        )
        assert created.key.startswith("oe_")
        assert created.rate_limit_per_min == 10
        assert created.allowed_cidrs == ["10.0.0.0/8"]
        with pytest.raises(HTTPException) as dup:
            await svc.create_api_key(uid, APIKeyCreate(name="CI"))
        assert dup.value.status_code == 409
        with pytest.raises(HTTPException) as scope:
            await svc.create_api_key(uid, APIKeyCreate(name="x", permissions=["nope.nothing"]))
        assert scope.value.status_code == 422
        with pytest.raises(HTTPException):
            await svc.create_api_key(uid, APIKeyCreate(name="old", expires_at=datetime.now(UTC) - timedelta(days=1)))
        with pytest.raises(HTTPException):
            await svc.create_api_key(uid, APIKeyCreate(name="far", expires_at=datetime.now(UTC) + timedelta(days=800)))


async def test_active_key_cap(factory):
    uid = await _user(factory)
    for i in range(rules.MAX_ACTIVE_KEYS_PER_USER):
        await _key(factory, uid, name=f"k{i}")
    async with factory() as s:
        with pytest.raises(HTTPException) as exc:
            await _service(s).create_api_key(uid, APIKeyCreate(name="one-too-many"))
        assert exc.value.status_code == 409


async def test_audit_trail_names_the_key_but_never_the_secret(factory):
    from sqlalchemy import select

    from app.core.audit_log import ActivityLog

    uid = await _user(factory)
    async with factory() as s:
        created = await _service(s).create_api_key(uid, APIKeyCreate(name="audited"))
        await s.commit()
    async with factory() as s:
        rows = (await s.execute(select(ActivityLog))).scalars().all()
    assert [r.action for r in rows] == ["api_key.created"]
    assert created.key_prefix in str(rows[0].after_state)
    assert created.key not in str(rows[0].__dict__)


async def test_rotation_overlap(factory, monkeypatch):
    uid = await _user(factory)
    async with factory() as s:
        svc = _service(s)
        old = await svc.create_api_key(
            uid, APIKeyCreate(name="ci", permissions=[PERM_A], rate_limit_per_min=50, allowed_cidrs=["203.0.113.0/24"])
        )
        new = await svc.rotate_api_key(uid, old.id)
        await s.commit()
    assert new.rotated_from_id == old.id
    assert (new.name, new.permissions, new.rate_limit_per_min, new.allowed_cidrs) == (
        "ci",
        [PERM_A],
        50,
        ["203.0.113.0/24"],
    )
    assert new.key != old.key

    # inside the overlap both keys work
    assert (await _resolve(old.key)).user.id == uid
    assert (await _resolve(new.key)).user.id == uid
    async with factory() as s:
        row = await s.get(APIKey, old.id)
        expires = row.expires_at.replace(tzinfo=UTC)
    assert timedelta(hours=23, minutes=59) < expires - datetime.now(UTC) <= timedelta(hours=24)

    # 24 hours and a minute later the old key is refused, the new one is not
    later = datetime.now(UTC) + timedelta(hours=24, minutes=1)

    class _Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return later

    import app.modules.users.repository as repo

    monkeypatch.setattr(repo, "datetime", _Later)
    with pytest.raises(HTTPException) as exc:
        await _resolve(old.key)
    assert exc.value.status_code == 401
    assert (await _resolve(new.key)).user.id == uid


async def test_rotate_ownership_and_state(factory):
    owner = await _user(factory)
    stranger = await _user(factory)
    async with factory() as s:
        svc = _service(s)
        key = await svc.create_api_key(owner, APIKeyCreate(name="ci"))
        with pytest.raises(HTTPException) as foreign:
            await svc.rotate_api_key(stranger, key.id)
        assert foreign.value.status_code == 404
        with pytest.raises(HTTPException) as missing:
            await svc.rotate_api_key(owner, uuid.uuid4())
        assert missing.value.status_code == 404

        await svc.rotate_api_key(owner, key.id)
        with pytest.raises(HTTPException) as again:
            await svc.rotate_api_key(owner, key.id)
        assert again.value.status_code == 409

        other = await svc.create_api_key(owner, APIKeyCreate(name="revoked-one"))
        await svc.revoke_api_key(owner, other.id)
        with pytest.raises(HTTPException) as inactive:
            await svc.rotate_api_key(owner, other.id)
        assert inactive.value.status_code == 409


async def test_rotation_keeps_the_old_keys_earlier_expiry(factory):
    uid = await _user(factory)
    soon = datetime.now(UTC) + timedelta(hours=2)
    _, key_id = await _key(factory, uid, name="short", expires_at=soon)
    async with factory() as s:
        await _service(s).rotate_api_key(uid, key_id)
        await s.commit()
    async with factory() as s:
        row = await s.get(APIKey, key_id)
        assert abs((row.expires_at.replace(tzinfo=UTC) - soon).total_seconds()) < 1


async def test_rotated_pair_counts_once_for_name_and_quota(factory):
    uid = await _user(factory)
    async with factory() as s:
        svc = _service(s)
        key = await svc.create_api_key(uid, APIKeyCreate(name="ci"))
        await svc.rotate_api_key(uid, key.id)
        live = await APIKeyRepository(s).list_live_for_user(uid)
        assert len(live) == 1


def test_key_hash_is_sha256_of_the_plaintext():
    full, key_hash, prefix = generate_api_key()
    assert key_hash == hashlib.sha256(full.encode()).hexdigest()
    assert full.startswith(prefix)


async def test_scopes_endpoint_serves_the_catalogue():
    from app.modules.users.router import list_api_key_scopes

    rows = await list_api_key_scopes("any-user")
    assert PERM_A in {r.name for r in rows}


def test_partner_routes_are_tagged_for_openapi():
    from app.modules.integrations.router import router as integrations
    from app.modules.users.router import router as users

    def tagged(router, suffix):
        return {r.path for r in router.routes if "Partner API" in (getattr(r, "tags", None) or []) and suffix in r.path}

    assert tagged(users, "/me/api-keys/scopes/") and tagged(users, "/rotate/")
    assert tagged(integrations, "/webhooks/events/")
    assert tagged(integrations, "/redeliver/")
    assert tagged(integrations, "/test/")
